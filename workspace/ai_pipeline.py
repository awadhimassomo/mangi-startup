from datetime import timedelta

from django.utils import timezone

from .models import FundingOpportunity, Notification, PostedOpportunity, Startup, Task


def _tokens(*values):
    words = set()
    for value in values:
        for token in (value or "").replace(",", " ").replace("/", " ").lower().split():
            cleaned = "".join(ch for ch in token if ch.isalnum() or ch in {"-", "_"})
            if len(cleaned) > 2:
                words.add(cleaned)
    return words


def assess_posted_opportunity_fit(startup, posted_opportunity):
    startup_terms = _tokens(
        startup.sector,
        startup.business_model,
        startup.short_description,
        startup.problem_statement,
        startup.solution_statement,
        startup.target_market,
        startup.current_traction,
        startup.country,
        startup.city,
    )
    opportunity_terms = _tokens(
        posted_opportunity.title,
        posted_opportunity.short_description,
        posted_opportunity.eligibility,
        posted_opportunity.sector_focus,
        posted_opportunity.geographic_focus,
        posted_opportunity.tags,
    )
    overlap = startup_terms & opportunity_terms

    score = 1
    reasons = []
    warnings = []

    if posted_opportunity.sector_focus:
        sector_terms = _tokens(posted_opportunity.sector_focus)
        if sector_terms & startup_terms:
            score += 2
            reasons.append("Sector focus appears to match the startup profile.")
        else:
            warnings.append("Sector focus may need manual review.")

    if posted_opportunity.geographic_focus:
        geo_terms = _tokens(posted_opportunity.geographic_focus)
        startup_geo = _tokens(startup.country, startup.city)
        if geo_terms & startup_geo:
            score += 1
            reasons.append("Geographic focus appears compatible.")
        else:
            warnings.append("Geographic eligibility may need confirmation.")

    if len(overlap) >= 4:
        score += 2
        reasons.append("Several keywords overlap with the startup profile.")
    elif len(overlap) >= 2:
        score += 1
        reasons.append("Some keywords overlap with the startup profile.")

    if posted_opportunity.deadline:
        days_left = (posted_opportunity.deadline - timezone.localdate()).days
        if days_left < 0:
            warnings.append("The deadline has passed.")
            score = min(score, 2)
        elif days_left <= 14:
            warnings.append("Deadline is close, prioritize quickly.")

    score = max(1, min(score, 5))
    probability = min(90, max(20, score * 15 + len(overlap) * 2))

    if not reasons:
        reasons.append("Added for review because it is available on the shared board.")

    return {
        "score": score,
        "probability": probability,
        "reasons": reasons,
        "warnings": warnings,
        "matched_terms": sorted(overlap)[:10],
    }


def build_pipeline_notes(posted_opportunity, assessment):
    sections = [
        "AI pipeline assessment",
        "",
        "Why it may fit:",
        *[f"- {reason}" for reason in assessment["reasons"]],
    ]
    if assessment["warnings"]:
        sections += ["", "Review before applying:", *[f"- {warning}" for warning in assessment["warnings"]]]
    if assessment["matched_terms"]:
        sections += ["", f"Matched keywords: {', '.join(assessment['matched_terms'])}"]
    if posted_opportunity.short_description:
        sections += ["", "Board overview:", posted_opportunity.short_description]
    if posted_opportunity.eligibility:
        sections += ["", "Eligibility notes:", posted_opportunity.eligibility]
    return "\n".join(sections)


def create_pipeline_from_posted_opportunity(startup, user, posted_opportunity):
    existing = startup.opportunities.filter(source_posted_opportunity=posted_opportunity).first()
    if existing:
        return existing, False, assess_posted_opportunity_fit(startup, posted_opportunity)

    assessment = assess_posted_opportunity_fit(startup, posted_opportunity)
    status = FundingOpportunity.Status.QUALIFYING if assessment["score"] >= 3 else FundingOpportunity.Status.RESEARCHING
    opportunity = FundingOpportunity.objects.create(
        startup=startup,
        source_posted_opportunity=posted_opportunity,
        name=posted_opportunity.title,
        funder_name=posted_opportunity.funder_name,
        opportunity_type=posted_opportunity.opportunity_type,
        sector=posted_opportunity.sector_focus,
        deadline_date=posted_opportunity.deadline,
        application_link=posted_opportunity.application_link,
        amount_min=posted_opportunity.amount_min or 0,
        amount=posted_opportunity.amount_max or posted_opportunity.amount_min or 0,
        currency=posted_opportunity.currency,
        geographic_eligibility=posted_opportunity.geographic_focus,
        source_of_lead="Mangi Opportunity Board",
        status=status,
        fit_score=assessment["score"],
        probability=assessment["probability"],
        tags=posted_opportunity.tags,
        notes=build_pipeline_notes(posted_opportunity, assessment),
        required_documents=posted_opportunity.eligibility,
        created_by=user,
        updated_by=user,
    )

    due_date = posted_opportunity.deadline
    if due_date:
        due_date = max(timezone.localdate(), due_date - timedelta(days=7))

    Task.objects.create(
        startup=startup,
        title=f"Review fit for {posted_opportunity.title}",
        description="Confirm eligibility, required documents, owner, and application plan.",
        related_opportunity=opportunity,
        assigned_to=user,
        due_date=due_date,
        priority=Task.Priority.HIGH if posted_opportunity.is_deadline_soon else Task.Priority.MEDIUM,
        created_by=user,
    )
    return opportunity, True, assessment


# ─── Bulk Matching Agent ────────────────────────────────────────────────────

MIN_AUTO_SCORE = 3  # only add to pipeline if fit score >= this


def run_matching_agent(trigger="manual", triggered_by=None, target_opportunity=None):
    """
    Iterate every active Startup × every open PostedOpportunity.
    If fit score >= MIN_AUTO_SCORE and not already in pipeline, add it automatically.
    Returns an AgentRun instance with run stats.
    """
    from .models import AgentRun  # local import to avoid circular at module load

    run = AgentRun.objects.create(trigger=trigger, triggered_by=triggered_by)

    try:
        startups = Startup.objects.prefetch_related("memberships").all()

        if target_opportunity:
            open_opps = PostedOpportunity.objects.filter(pk=target_opportunity.pk, status=PostedOpportunity.Status.OPEN)
        else:
            open_opps = PostedOpportunity.objects.filter(status=PostedOpportunity.Status.OPEN)

        pipelines_created = 0
        startups_processed = 0

        for startup in startups:
            startups_processed += 1
            # Use the first admin/owner of the startup as the acting user
            admin_membership = (
                startup.memberships.filter(is_active=True)
                .order_by("joined_at")
                .first()
            )
            if not admin_membership:
                continue
            agent_user = admin_membership.user

            for opp in open_opps:
                assessment = assess_posted_opportunity_fit(startup, opp)
                if assessment["score"] < MIN_AUTO_SCORE:
                    continue

                existing = startup.opportunities.filter(source_posted_opportunity=opp).first()
                if existing:
                    continue

                _, created, _ = create_pipeline_from_posted_opportunity(startup, agent_user, opp)
                if created:
                    pipelines_created += 1
                    # Notify all active members of the startup
                    for membership in startup.memberships.filter(is_active=True).select_related("user"):
                        Notification.objects.create(
                            user=membership.user,
                            startup=startup,
                            title=f"New match: {opp.title}",
                            body=(
                                f"The Mangi agent found a {assessment['score']}/5 fit opportunity — "
                                f"{opp.title} by {opp.funder_name}. It has been added to your pipeline for review."
                            ),
                            level=Notification.Level.INFO,
                            link=opp.get_absolute_url(),
                        )

        run.startups_processed = startups_processed
        run.opportunities_processed = open_opps.count()
        run.pipelines_created = pipelines_created
        run.status = AgentRun.Status.DONE
        run.finished_at = timezone.now()
        run.notes = (
            f"Processed {startups_processed} startups × {open_opps.count()} opportunities. "
            f"Created {pipelines_created} new pipeline entries."
        )

    except Exception as exc:  # noqa: BLE001
        run.status = AgentRun.Status.FAILED
        run.finished_at = timezone.now()
        run.notes = f"Agent failed: {exc}"

    run.save()
    return run
