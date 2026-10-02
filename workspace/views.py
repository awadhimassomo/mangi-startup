import calendar as cal_module
import csv
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Count, Sum
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .ai_pipeline import assess_posted_opportunity_fit, create_pipeline_from_posted_opportunity, run_matching_agent
from .forms import (
    BudgetItemForm,
    BudgetPlanForm,
    CashAdvanceForm,
    CashAdvanceReconcileForm,
    ContactForm,
    DisbursementForm,
    DocumentForm,
    DocumentVersionForm,
    ExchangeRateForm,
    ExpenseForm,
    GrantBudgetCategoryForm,
    InteractionLogForm,
    ManagedGrantForm,
    MilestoneEvidenceForm,
    MilestoneForm,
    MilestoneStatusForm,
    OpportunityForm,
    PostedOpportunityForm,
    QuickExpenseForm,
    SignUpForm,
    StartupForm,
    StartupMemberForm,
    StageUpdateForm,
    TaskForm,
)
from .models import (
    ActivityLog,
    BudgetPlan,
    CashAdvance,
    Contact,
    Disbursement,
    ExchangeRate,
    Expense,
    FundingOpportunity,
    GrantBudgetCategory,
    InteractionLog,
    ManagedGrant,
    Milestone,
    MilestoneEvidence,
    Notification,
    OpportunityStageHistory,
    AgentRun,
    PostedOpportunity,
    Startup,
    StartupDocument,
    StartupMember,
    Task,
)
from .utils import (
    build_dashboard_metrics,
    build_readiness_summary,
    check_write_permission,
    ensure_default_document_categories,
    get_current_membership,
    get_current_startup,
    log_activity,
)


def home_redirect(request):
    if not request.user.is_authenticated:
        return render(request, "workspace/landing.html")
    if request.user.is_superuser:
        return redirect("ops_dashboard")
    if get_current_startup(request.user):
        return redirect("dashboard")
    return redirect("onboarding")


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("onboarding")
    return render(request, "registration/signup.html", {"form": form, "auth_form": AuthenticationForm()})


@login_required
def onboarding_view(request):
    if get_current_startup(request.user):
        return redirect("dashboard")
    form = StartupForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        startup = form.save()
        StartupMember.objects.create(
            startup=startup,
            user=request.user,
            role=StartupMember.Role.STARTUP_ADMIN,
            is_active=True,
        )
        log_activity(startup, request.user, "created", startup, "Created startup workspace.")
        messages.success(request, "Workspace created. You can now start tracking fundraising.")
        return redirect("dashboard")
    return render(request, "workspace/onboarding.html", {"form": form})


def require_startup_access(request):
    ensure_default_document_categories()
    startup = get_current_startup(request.user)
    membership = get_current_membership(request.user)
    if not startup or not membership:
        return None, None, redirect("onboarding")
    return startup, membership, None


@login_required
def dashboard_view(request):
    if request.user.is_superuser:
        return redirect("ops_dashboard")
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    context = build_dashboard_metrics(startup)
    context["startup"] = startup
    context["membership"] = membership
    return render(request, "workspace/dashboard.html", context)


@login_required
def startup_profile_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    form = StartupForm(request.POST or None, request.FILES or None, instance=startup)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_activity(startup, request.user, "updated", startup, "Updated startup profile.")
        messages.success(request, "Startup profile updated.")
        return redirect("startup_profile")
    readiness = build_readiness_summary(startup)
    return render(
        request,
        "workspace/startup_profile.html",
        {"form": form, "startup": startup, "readiness": readiness, "membership": membership},
    )


@login_required
def opportunity_list_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    opportunities = startup.opportunities.all()
    status = request.GET.get("status", "")
    opp_type = request.GET.get("type", "")
    if status:
        opportunities = opportunities.filter(status=status)
    if opp_type:
        opportunities = opportunities.filter(opportunity_type=opp_type)
    type_counts = (
        startup.opportunities.values("opportunity_type")
        .annotate(total=Count("id"))
        .order_by("opportunity_type")
    )
    return render(
        request,
        "workspace/opportunity_list.html",
        {
            "opportunities": opportunities,
            "status_choices": FundingOpportunity.Status.choices,
            "type_choices": FundingOpportunity.OpportunityType.choices,
            "type_counts": type_counts,
            "active_status": status,
            "active_type": opp_type,
            "membership": membership,
        },
    )


@login_required
def opportunity_create_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    form = OpportunityForm(request.POST or None, startup=startup)
    if request.method == "POST" and form.is_valid():
        opportunity = form.save(commit=False)
        opportunity.startup = startup
        opportunity.created_by = request.user
        opportunity.updated_by = request.user
        opportunity.save()
        log_activity(startup, request.user, "created", opportunity, f"Added opportunity {opportunity.name}.")
        messages.success(request, "Opportunity added.")
        return redirect(opportunity.get_absolute_url())
    return render(request, "workspace/opportunity_form.html", {"form": form, "mode": "Add"})


@login_required
def opportunity_update_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    opportunity = get_object_or_404(FundingOpportunity, pk=pk, startup=startup)
    form = OpportunityForm(request.POST or None, instance=opportunity, startup=startup)
    if request.method == "POST" and form.is_valid():
        opportunity = form.save(commit=False)
        opportunity.updated_by = request.user
        opportunity.save()
        log_activity(startup, request.user, "updated", opportunity, f"Updated opportunity {opportunity.name}.")
        messages.success(request, "Opportunity updated.")
        return redirect(opportunity.get_absolute_url())
    return render(request, "workspace/opportunity_form.html", {"form": form, "mode": "Edit", "opportunity": opportunity})


@login_required
def opportunity_detail_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    opportunity = get_object_or_404(FundingOpportunity, pk=pk, startup=startup)
    stage_form = StageUpdateForm(initial={"status": opportunity.status})
    tasks = opportunity.tasks.all()
    documents = opportunity.documents.filter(parent_document__isnull=True)
    budgets = opportunity.budget_plans.all()
    stage_history = opportunity.stage_history.select_related("changed_by").all()[:10]
    activity = startup.activity_logs.filter(object_id=opportunity.pk)[:8]
    fit_assessment = None
    if opportunity.source_posted_opportunity:
        fit_assessment = assess_posted_opportunity_fit(startup, opportunity.source_posted_opportunity)
    return render(
        request,
        "workspace/opportunity_detail.html",
        {
            "opportunity": opportunity,
            "stage_form": stage_form,
            "tasks": tasks,
            "documents": documents,
            "budgets": budgets,
            "stage_history": stage_history,
            "activity": activity,
            "membership": membership,
            "status_choices": FundingOpportunity.Status.choices,
            "fit_assessment": fit_assessment,
        },
    )


@login_required
def document_list_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    documents = startup.documents.select_related("category", "linked_opportunity", "uploaded_by")
    categories = startup.documents.values("category__name").annotate(total=Count("id"))
    readiness = build_readiness_summary(startup)
    return render(
        request,
        "workspace/document_list.html",
        {"documents": documents, "categories": categories, "readiness": readiness, "membership": membership},
    )


@login_required
def document_create_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    form = DocumentForm(request.POST or None, request.FILES or None, startup=startup)
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        document.startup = startup
        document.uploaded_by = request.user
        document.save()
        log_activity(startup, request.user, "created", document, f"Uploaded document {document.title}.")
        messages.success(request, "Document uploaded.")
        return redirect("document_list")
    return render(request, "workspace/document_form.html", {"form": form, "mode": "Upload"})


@login_required
def document_update_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    document = get_object_or_404(StartupDocument, pk=pk, startup=startup)
    form = DocumentForm(request.POST or None, request.FILES or None, instance=document, startup=startup)
    if request.method == "POST" and form.is_valid():
        document = form.save(commit=False)
        if request.FILES:
            document.uploaded_by = request.user
        document.save()
        log_activity(startup, request.user, "updated", document, f"Updated document {document.title}.")
        messages.success(request, "Document updated.")
        return redirect("document_list")
    return render(request, "workspace/document_form.html", {"form": form, "mode": "Edit", "document": document})


@login_required
def budget_list_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    plans = startup.budget_plans.select_related("funding_source")
    return render(request, "workspace/budget_list.html", {"plans": plans, "membership": membership})


@login_required
def budget_create_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    form = BudgetPlanForm(request.POST or None, startup=startup)
    if request.method == "POST" and form.is_valid():
        plan = form.save(commit=False)
        plan.startup = startup
        plan.created_by = request.user
        plan.save()
        log_activity(startup, request.user, "created", plan, f"Created budget plan {plan.title}.")
        messages.success(request, "Budget plan created.")
        return redirect("budget_detail", pk=plan.pk)
    return render(request, "workspace/budget_form.html", {"form": form, "mode": "Add"})


@login_required
def budget_detail_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    plan = get_object_or_404(BudgetPlan, pk=pk, startup=startup)
    item_form = BudgetItemForm(request.POST or None)
    if request.method == "POST" and item_form.is_valid():
        item = item_form.save(commit=False)
        item.budget_plan = plan
        item.save()
        log_activity(startup, request.user, "created", item, f"Added budget line in {plan.title}.")
        messages.success(request, "Budget item added.")
        return redirect("budget_detail", pk=plan.pk)
    return render(
        request,
        "workspace/budget_detail.html",
        {
            "plan": plan,
            "item_form": item_form,
            "membership": membership,
        },
    )


@login_required
def task_list_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    tasks = startup.tasks.select_related("assigned_to", "related_opportunity", "related_document")
    return render(request, "workspace/task_list.html", {"tasks": tasks, "membership": membership})


@login_required
def task_create_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    form = TaskForm(request.POST or None, startup=startup)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.startup = startup
        task.created_by = request.user
        task.save()
        log_activity(startup, request.user, "created", task, f"Created task {task.title}.")
        messages.success(request, "Task created.")
        return redirect("task_list")
    return render(request, "workspace/task_form.html", {"form": form, "mode": "Add"})


@login_required
def task_update_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    task = get_object_or_404(Task, pk=pk, startup=startup)
    form = TaskForm(request.POST or None, instance=task, startup=startup)
    if request.method == "POST" and form.is_valid():
        task = form.save()
        log_activity(startup, request.user, "updated", task, f"Updated task {task.title}.")
        messages.success(request, "Task updated.")
        return redirect("task_list")
    return render(request, "workspace/task_form.html", {"form": form, "mode": "Edit", "task": task})


@login_required
def team_list_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    members = startup.memberships.select_related("user")
    return render(request, "workspace/team_list.html", {"members": members, "membership": membership})


@login_required
def team_add_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    if membership.role not in [StartupMember.Role.STARTUP_ADMIN, StartupMember.Role.SUPER_ADMIN]:
        return HttpResponseForbidden("Only startup admins can add team members.")
    if startup.seats_available == 0:
        messages.error(
            request,
            f"Your {startup.get_plan_display()} plan allows {startup.seat_limit} seat{'s' if startup.seat_limit != 1 else ''}. "
            f"Upgrade to Team ($29/mo) to add more members."
        )
        return redirect("team_list")
    form = StartupMemberForm(request.POST or None, startup=startup)
    if request.method == "POST" and form.is_valid():
        if startup.seats_available == 0:
            messages.error(request, "Seat limit reached. Please upgrade your plan.")
            return redirect("team_list")
        member = form.save(commit=False)
        member.startup = startup
        member.save()
        log_activity(startup, request.user, "created", member, f"Added {member.user} to the team.")
        messages.success(request, "Team member added.")
        return redirect("team_list")
    return render(request, "workspace/team_form.html", {"form": form, "startup": startup})


@login_required
def reports_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    readiness = build_readiness_summary(startup)
    opportunities = startup.opportunities.all()
    won_qs = opportunities.filter(status=FundingOpportunity.Status.WON)
    lost_qs = opportunities.filter(status=FundingOpportunity.Status.LOST)
    decided = won_qs.count() + lost_qs.count()
    win_rate = round(won_qs.count() / decided * 100) if decided else 0

    context = {
        "membership": membership,
        "readiness": readiness,
        "pipeline_total": opportunities.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "weighted_total": sum((op.weighted_amount for op in opportunities), Decimal("0.00")),
        "won_total": won_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "won_count": won_qs.count(),
        "lost_count": lost_qs.count(),
        "win_rate": win_rate,
        "win_by_type": list(
            won_qs.values("opportunity_type").annotate(count=Count("id")).order_by("-count")
        ),
        "loss_by_type": list(
            lost_qs.values("opportunity_type").annotate(count=Count("id")).order_by("-count")
        ),
        "win_by_sector": list(
            won_qs.exclude(sector="").values("sector").annotate(count=Count("id")).order_by("-count")[:8]
        ),
        "win_reasons": list(
            won_qs.exclude(outcome_reason="")
            .values("outcome_reason").annotate(count=Count("id")).order_by("-count")
        ),
        "loss_reasons": list(
            lost_qs.exclude(outcome_reason="")
            .values("outcome_reason").annotate(count=Count("id")).order_by("-count")
        ),
        "task_summary": startup.tasks.values("status").annotate(total=Count("id")).order_by("status"),
        "recent_activity": ActivityLog.objects.filter(startup=startup)[:10],
    }
    return render(request, "workspace/reports.html", context)


@login_required
def kanban_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    board = [
        {
            "value": value,
            "label": label,
            "opportunities": list(
                startup.opportunities.filter(status=value).order_by("deadline_date")
            ),
        }
        for value, label in FundingOpportunity.Status.choices
    ]
    return render(request, "workspace/kanban.html", {
        "board": board,
        "stages": FundingOpportunity.Status.choices,
        "membership": membership,
    })


@login_required
def opportunity_stage_update(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    opportunity = get_object_or_404(FundingOpportunity, pk=pk, startup=startup)
    if request.method == "POST":
        form = StageUpdateForm(request.POST)
        if form.is_valid():
            new_status = form.cleaned_data["status"]
            note = form.cleaned_data.get("note", "")
            outcome_reason = form.cleaned_data.get("outcome_reason", "")
            outcome_notes = form.cleaned_data.get("outcome_notes", "")
            old_status = opportunity.status
            if old_status != new_status:
                OpportunityStageHistory.objects.create(
                    opportunity=opportunity,
                    from_status=old_status,
                    to_status=new_status,
                    changed_by=request.user,
                    note=note,
                )
                update_fields = ["status", "updated_by", "updated_at"]
                opportunity.status = new_status
                opportunity.updated_by = request.user
                if new_status in FundingOpportunity.TERMINAL_STATUSES:
                    opportunity.outcome_reason = outcome_reason
                    opportunity.outcome_notes = outcome_notes
                    update_fields += ["outcome_reason", "outcome_notes"]
                opportunity.save(update_fields=update_fields)
                log_activity(
                    startup, request.user, "stage_update", opportunity,
                    f"Moved '{opportunity.name}' from {old_status} \u2192 {new_status}.",
                )
                messages.success(request, f"Stage updated to \"{opportunity.get_status_display()}\".")
        else:
            next_url = request.POST.get("next", opportunity.get_absolute_url())
            return render(request, "workspace/opportunity_detail.html", {
                "opportunity": opportunity,
                "stage_form": form,
                "tasks": opportunity.tasks.all(),
                "documents": opportunity.documents.filter(parent_document__isnull=True),
                "budgets": opportunity.budget_plans.all(),
                "stage_history": opportunity.stage_history.select_related("changed_by").all()[:10],
                "activity": startup.activity_logs.filter(object_id=opportunity.pk)[:8],
                "membership": membership,
                "status_choices": FundingOpportunity.Status.choices,
            })
    next_url = request.POST.get("next", opportunity.get_absolute_url())
    return redirect(next_url)


@login_required
def calendar_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        if month < 1 or month > 12:
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    opportunities = startup.opportunities.filter(
        deadline_date__year=year, deadline_date__month=month
    ).order_by("deadline_date")

    deadline_map = {}
    for opp in opportunities:
        deadline_map.setdefault(opp.deadline_date.day, []).append(opp)

    raw_weeks = cal_module.monthcalendar(year, month)
    calendar_weeks = [
        [
            {
                "day": day,
                "events": deadline_map.get(day, []),
                "is_today": (
                    day != 0 and day == today.day and year == today.year and month == today.month
                ),
                "is_empty": day == 0,
            }
            for day in week
        ]
        for week in raw_weeks
    ]

    prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)

    return render(request, "workspace/calendar.html", {
        "calendar_weeks": calendar_weeks,
        "year": year,
        "month": month,
        "month_name": cal_module.month_name[month],
        "today": today,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "membership": membership,
    })


@login_required
def document_version_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    parent = get_object_or_404(StartupDocument, pk=pk, startup=startup)
    form = DocumentVersionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        doc = form.save(commit=False)
        doc.startup = startup
        doc.uploaded_by = request.user
        doc.parent_document = parent
        doc.category = parent.category
        doc.title = parent.title
        doc.linked_opportunity = parent.linked_opportunity
        doc.completion_status = parent.completion_status
        doc.save()
        log_activity(startup, request.user, "created", doc, f"Uploaded new version of '{doc.title}'.")
        messages.success(request, "New version uploaded.")
        return redirect("document_list")
    all_versions = list(parent.versions.order_by("-created_at"))
    return render(request, "workspace/document_version_form.html", {
        "form": form,
        "parent": parent,
        "versions": all_versions,
        "membership": membership,
    })


@login_required
def contact_list_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    q = request.GET.get("q", "").strip()
    contacts = startup.contacts.select_related("linked_opportunity")
    if q:
        from django.db.models import Q
        contacts = contacts.filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(role__icontains=q) |
            Q(linked_opportunity__name__icontains=q)
        )
    return render(request, "workspace/contact_list.html", {
        "contacts": contacts,
        "q": q,
        "membership": membership,
    })


@login_required
def contact_create_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    form = ContactForm(request.POST or None, startup=startup)
    if request.method == "POST" and form.is_valid():
        contact = form.save(commit=False)
        contact.startup = startup
        contact.save()
        log_activity(startup, request.user, "created", contact, f"Added contact '{contact.name}'.")
        messages.success(request, f"Contact \"{contact.name}\" added.")
        return redirect("contact_list")
    return render(request, "workspace/contact_form.html", {
        "form": form, "mode": "Add", "membership": membership,
    })


@login_required
def contact_update_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    contact = get_object_or_404(Contact, pk=pk, startup=startup)
    form = ContactForm(request.POST or None, instance=contact, startup=startup)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_activity(startup, request.user, "updated", contact, f"Updated contact '{contact.name}'.")
        messages.success(request, "Contact updated.")
        return redirect("contact_detail", pk=contact.pk)
    return render(request, "workspace/contact_form.html", {
        "form": form, "mode": "Edit", "contact": contact, "membership": membership,
    })


@login_required
def contact_detail_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    contact = get_object_or_404(Contact, pk=pk, startup=startup)
    interactions = contact.interactions.select_related("logged_by").all()
    interaction_form = InteractionLogForm()
    return render(request, "workspace/contact_detail.html", {
        "contact": contact,
        "interactions": interactions,
        "interaction_form": interaction_form,
        "membership": membership,
    })


@login_required
def interaction_create_view(request, contact_pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    contact = get_object_or_404(Contact, pk=contact_pk, startup=startup)
    if request.method == "POST":
        form = InteractionLogForm(request.POST)
        if form.is_valid():
            interaction = form.save(commit=False)
            interaction.contact = contact
            interaction.logged_by = request.user
            interaction.save()
            contact.last_interaction_date = interaction.date
            contact.save(update_fields=["last_interaction_date", "updated_at"])
            log_activity(
                startup, request.user, "created", interaction,
                f"Logged {interaction.get_interaction_type_display()} with '{contact.name}'.",
            )
            messages.success(request, "Interaction logged.")
    return redirect("contact_detail", pk=contact.pk)


# ── Phase 2: Grant Management ─────────────────────────────────────────────────

@login_required
def grant_list_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    status_filter = request.GET.get("status", "")
    grants = startup.managed_grants.select_related("opportunity")
    if status_filter:
        grants = grants.filter(status=status_filter)
    return render(request, "workspace/grant_list.html", {
        "grants": grants,
        "status_filter": status_filter,
        "status_choices": ManagedGrant.Status.choices,
        "membership": membership,
    })


@login_required
def grant_create_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    guard = check_write_permission(membership)
    if guard:
        return guard
    form = ManagedGrantForm(request.POST or None, request.FILES or None, startup=startup)
    if request.method == "POST" and form.is_valid():
        grant = form.save(commit=False)
        grant.startup = startup
        grant.created_by = request.user
        if grant.opportunity and not grant.funder_name:
            grant.funder_name = grant.opportunity.funder_name
        grant.save()
        log_activity(startup, request.user, "created", grant, f"Created grant '{grant.name}'.")
        messages.success(request, f"Grant \"{grant.name}\" created.")
        return redirect("grant_detail", pk=grant.pk)
    return render(request, "workspace/grant_form.html", {
        "form": form, "mode": "Create", "membership": membership,
    })


@login_required
def grant_update_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    grant = get_object_or_404(ManagedGrant, pk=pk, startup=startup)
    form = ManagedGrantForm(request.POST or None, request.FILES or None, instance=grant, startup=startup)
    if request.method == "POST" and form.is_valid():
        before = {
            "name": grant.name, "status": grant.status,
            "total_amount": str(grant.total_amount), "currency": grant.currency,
            "start_date": str(grant.start_date), "end_date": str(grant.end_date),
        }
        form.save()
        after = {
            "name": grant.name, "status": grant.status,
            "total_amount": str(grant.total_amount), "currency": grant.currency,
            "start_date": str(grant.start_date), "end_date": str(grant.end_date),
        }
        log_activity(startup, request.user, "updated", grant, f"Updated grant '{grant.name}'.",
                     before_state=before, after_state=after)
        messages.success(request, "Grant updated.")
        return redirect("grant_detail", pk=grant.pk)
    return render(request, "workspace/grant_form.html", {
        "form": form, "mode": "Edit", "grant": grant, "membership": membership,
    })


@login_required
def grant_detail_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    grant = get_object_or_404(ManagedGrant, pk=pk, startup=startup)
    disbursements = grant.disbursements.all()
    milestones = grant.milestones.prefetch_related("evidence").all()
    budget_cats = grant.budget_categories.all()
    expenses = grant.expenses.select_related("category", "milestone", "paid_by").all()
    advances = grant.cash_advances.all()
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    cat_filter = request.GET.get("category", "")
    ms_filter = request.GET.get("milestone_f", "")
    if date_from:
        expenses = expenses.filter(date__gte=date_from)
    if date_to:
        expenses = expenses.filter(date__lte=date_to)
    if cat_filter:
        expenses = expenses.filter(category_id=cat_filter)
    if ms_filter:
        expenses = expenses.filter(milestone_id=ms_filter)
    return render(request, "workspace/grant_detail.html", {
        "grant": grant,
        "disbursements": disbursements,
        "milestones": milestones,
        "budget_cats": budget_cats,
        "expenses": expenses,
        "advances": advances,
        "disbursement_form": DisbursementForm(),
        "milestone_form": MilestoneForm(),
        "milestone_evidence_form": MilestoneEvidenceForm(),
        "milestone_status_choices": Milestone.Status.choices,
        "budget_cat_form": GrantBudgetCategoryForm(grant=grant),
        "expense_form": ExpenseForm(grant=grant),
        "advance_form": CashAdvanceForm(),
        "date_from": date_from,
        "date_to": date_to,
        "cat_filter": cat_filter,
        "ms_filter": ms_filter,
        "membership": membership,
    })


@login_required
def disbursement_add_view(request, grant_pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    grant = get_object_or_404(ManagedGrant, pk=grant_pk, startup=startup)
    if request.method == "POST":
        form = DisbursementForm(request.POST)
        if form.is_valid():
            d = form.save(commit=False)
            d.grant = grant
            d.save()
            messages.success(request, "Disbursement added.")
    return redirect(grant.get_absolute_url() + "#disbursements")


@login_required
def disbursement_update_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    disbursement = get_object_or_404(Disbursement, pk=pk, grant__startup=startup)
    form = DisbursementForm(request.POST or None, instance=disbursement)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Disbursement updated.")
        return redirect(disbursement.grant.get_absolute_url() + "#disbursements")
    return render(request, "workspace/disbursement_form.html", {
        "form": form, "disbursement": disbursement, "membership": membership,
    })


@login_required
def milestone_add_view(request, grant_pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    grant = get_object_or_404(ManagedGrant, pk=grant_pk, startup=startup)
    if request.method == "POST":
        form = MilestoneForm(request.POST)
        if form.is_valid():
            m = form.save(commit=False)
            m.grant = grant
            m.save()
            messages.success(request, "Milestone added.")
    return redirect(grant.get_absolute_url() + "#milestones")


@login_required
def milestone_status_update_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    milestone = get_object_or_404(Milestone, pk=pk, grant__startup=startup)
    if request.method == "POST":
        form = MilestoneStatusForm(request.POST, instance=milestone)
        if form.is_valid():
            form.save()
            messages.success(request, f"Milestone updated to {milestone.get_status_display()}.")
    return redirect(milestone.grant.get_absolute_url() + "#milestones")


@login_required
def milestone_evidence_add_view(request, milestone_pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    milestone = get_object_or_404(Milestone, pk=milestone_pk, grant__startup=startup)
    if request.method == "POST":
        form = MilestoneEvidenceForm(request.POST, request.FILES)
        if form.is_valid():
            ev = form.save(commit=False)
            ev.milestone = milestone
            ev.uploaded_by = request.user
            ev.save()
            messages.success(request, "Evidence uploaded.")
    return redirect(milestone.grant.get_absolute_url() + "#milestones")


@login_required
def budget_category_add_view(request, grant_pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    grant = get_object_or_404(ManagedGrant, pk=grant_pk, startup=startup)
    if request.method == "POST":
        form = GrantBudgetCategoryForm(request.POST, grant=grant)
        if form.is_valid():
            cat = form.save(commit=False)
            cat.grant = grant
            cat.save()
            messages.success(request, "Budget category added.")
    return redirect(grant.get_absolute_url() + "#budget")


@login_required
def expense_add_view(request, grant_pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    grant = get_object_or_404(ManagedGrant, pk=grant_pk, startup=startup)
    if request.method == "POST":
        guard = check_write_permission(membership)
        if guard:
            return guard
        form = ExpenseForm(request.POST, request.FILES, grant=grant)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.grant = grant
            from .utils import is_field_staff
            if is_field_staff(membership):
                expense.paid_by = request.user
            expense.save()
            messages.success(request, "Expense logged.")
    return redirect(grant.get_absolute_url() + "#expenses")


@login_required
def cash_advance_add_view(request, grant_pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    guard = check_write_permission(membership)
    if guard:
        return guard
    grant = get_object_or_404(ManagedGrant, pk=grant_pk, startup=startup)
    if request.method == "POST":
        form = CashAdvanceForm(request.POST)
        if form.is_valid():
            advance = form.save(commit=False)
            advance.grant = grant
            advance.save()
            messages.success(request, "Cash advance recorded.")
    return redirect(grant.get_absolute_url() + "#advances")


@login_required
def cash_advance_reconcile_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    advance = get_object_or_404(CashAdvance, pk=pk, grant__startup=startup)
    if request.method == "POST":
        guard = check_write_permission(membership)
        if guard:
            return guard
        form = CashAdvanceReconcileForm(request.POST, instance=advance)
        if form.is_valid():
            before = {
                "receipts_submitted": str(advance.receipts_submitted),
                "cash_returned": str(advance.cash_returned),
                "balance_outstanding": str(advance.balance_outstanding),
            }
            form.save()
            after = {
                "receipts_submitted": str(advance.receipts_submitted),
                "cash_returned": str(advance.cash_returned),
                "balance_outstanding": str(advance.balance_outstanding),
            }
            log_activity(startup, request.user, "updated", advance,
                         f"Reconciled advance for {advance.person}.",
                         before_state=before, after_state=after)
            messages.success(request, "Advance reconciled.")
    return redirect(advance.grant.get_absolute_url() + "#advances")


@login_required
def grant_report_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    grant = get_object_or_404(ManagedGrant, pk=pk, startup=startup)
    milestones = grant.milestones.prefetch_related("evidence").all()
    budget_cats = grant.budget_categories.all()
    expenses = grant.expenses.select_related("category", "milestone", "paid_by").all()
    advances = grant.cash_advances.all()
    return render(request, "workspace/grant_report.html", {
        "grant": grant,
        "budget_cats": budget_cats,
        "milestones": milestones,
        "expenses": expenses,
        "advances": advances,
        "startup": startup,
    })


@login_required
def grant_export_csv_view(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    grant = get_object_or_404(ManagedGrant, pk=pk, startup=startup)
    export_type = request.GET.get("type", "expenses")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="{grant.name}_{export_type}.csv"'
    )
    writer = csv.writer(response)
    if export_type == "expenses":
        writer.writerow([
            "Date", "Description", "Category", "Milestone", "Vendor",
            "Receipt No.", "Amount", "Currency", "Payment Method",
            "Paid By", "Approved By", "Notes",
        ])
        for e in grant.expenses.select_related(
            "category", "milestone", "paid_by", "approved_by"
        ).all():
            writer.writerow([
                e.date, e.description,
                e.category.name if e.category else "",
                e.milestone.name if e.milestone else "",
                e.vendor, e.receipt_number, e.amount, e.currency,
                e.get_payment_method_display(),
                e.paid_by.get_full_name() if e.paid_by else "",
                e.approved_by.get_full_name() if e.approved_by else "",
                e.notes,
            ])
    elif export_type == "disbursements":
        writer.writerow([
            "Tranche", "Amount", "Currency", "Expected Date",
            "Receipt Date", "Status", "Bank Account", "Exchange Rate", "Notes",
        ])
        for d in grant.disbursements.all():
            writer.writerow([
                d.name, d.amount, d.currency, d.expected_date,
                d.actual_receipt_date or "", d.get_status_display(),
                d.bank_account, d.exchange_rate or "", d.notes,
            ])
    elif export_type == "advances":
        writer.writerow([
            "Date Issued", "Person", "Purpose", "Amount Given",
            "Receipts Submitted", "Cash Returned", "Balance", "Aging",
        ])
        for a in grant.cash_advances.all():
            writer.writerow([
                a.date_issued, a.person, a.purpose,
                a.amount_given, a.receipts_submitted, a.cash_returned,
                a.balance_outstanding, "Yes" if a.is_aging else "No",
            ])
    elif export_type == "budget":
        writer.writerow([
            "Category", "Linked Milestone", "Allocated", "Spent", "Remaining", "Utilization %",
        ])
        for c in grant.budget_categories.all():
            writer.writerow([
                c.name,
                c.milestone.name if c.milestone else "",
                c.allocated_amount, c.spent, c.remaining, f"{c.utilization_pct}%",
            ])
    return response


# ── Phase 3: Cross-Cutting ────────────────────────────────────────────────────

@login_required
def audit_log_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    if membership.role not in StartupMember.ADMIN_ROLES:
        return HttpResponseForbidden("Audit log is restricted to admins.")
    qs = startup.activity_logs.select_related("user").all()
    model_filter = request.GET.get("model", "")
    action_filter = request.GET.get("action", "")
    if model_filter:
        qs = qs.filter(model_name__icontains=model_filter)
    if action_filter:
        qs = qs.filter(action=action_filter)
    return render(request, "workspace/audit_log.html", {
        "logs": qs[:200],
        "model_filter": model_filter,
        "action_filter": action_filter,
        "membership": membership,
    })


@login_required
def notification_list_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    notifications = Notification.objects.filter(
        user=request.user, startup=startup
    ).order_by("-created_at")
    return render(request, "workspace/notifications.html", {
        "notifications": notifications,
        "membership": membership,
    })


@login_required
def settings_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    return render(request, "workspace/settings.html", {
        "membership": membership,
        "is_ops_admin": request.user.is_superuser,
    })


@login_required
def notification_mark_read_view(request, pk=None):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    if pk:
        Notification.objects.filter(pk=pk, user=request.user).update(is_read=True)
    else:
        Notification.objects.filter(user=request.user, startup=startup, is_read=False).update(is_read=True)
    return redirect("notifications")


@login_required
def quick_expense_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    guard = check_write_permission(membership)
    if guard:
        return guard
    from .utils import is_field_staff
    form = QuickExpenseForm(
        request.POST or None,
        request.FILES or None,
        startup=startup,
        user=request.user,
    )
    saved = False
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.grant = form.cleaned_data["grant"]
        if is_field_staff(membership):
            expense.paid_by = request.user
        expense.save()
        messages.success(request, "Expense logged.")
        saved = True
        form = QuickExpenseForm(startup=startup, user=request.user)
    return render(request, "workspace/quick_expense.html", {
        "form": form, "saved": saved, "membership": membership,
    })


@login_required
def exchange_rate_list_view(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    if membership.role not in StartupMember.ADMIN_ROLES:
        return HttpResponseForbidden("Exchange rate management is admin-only.")
    rates = ExchangeRate.objects.all()[:100]
    form = ExchangeRateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        rate = form.save(commit=False)
        rate.updated_by = request.user
        rate.save()
        messages.success(request, f"Rate saved: {rate}")
        return redirect("exchange_rates")
    return render(request, "workspace/exchange_rates.html", {
        "rates": rates, "form": form, "membership": membership,
    })


@login_required
def posted_opportunity_list(request):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    qs = PostedOpportunity.objects.all()
    opp_type = request.GET.get("type", "")
    status = request.GET.get("status", "")
    search = request.GET.get("q", "")
    if opp_type:
        qs = qs.filter(opportunity_type=opp_type)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(title__icontains=search) | qs.filter(funder_name__icontains=search)
    pipeline_source_ids = set(
        startup.opportunities.filter(source_posted_opportunity__isnull=False)
        .values_list("source_posted_opportunity_id", flat=True)
    )
    return render(request, "workspace/posted_opportunity_list.html", {
        "opportunities": qs,
        "type_choices": PostedOpportunity.OpportunityType.choices,
        "status_choices": PostedOpportunity.Status.choices,
        "active_type": opp_type,
        "active_status": status,
        "search": search,
        "membership": membership,
        "is_staff": request.user.is_staff,
        "pipeline_source_ids": pipeline_source_ids,
    })


@login_required
def posted_opportunity_detail(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    opp = get_object_or_404(PostedOpportunity, pk=pk)
    pipeline_opportunity = startup.opportunities.filter(source_posted_opportunity=opp).first()
    fit_assessment = assess_posted_opportunity_fit(startup, opp)
    return render(request, "workspace/posted_opportunity_detail.html", {
        "opp": opp,
        "membership": membership,
        "is_staff": request.user.is_staff,
        "pipeline_opportunity": pipeline_opportunity,
        "fit_assessment": fit_assessment,
    })


@login_required
def posted_opportunity_add_to_pipeline(request, pk):
    startup, membership, redirect_response = require_startup_access(request)
    if redirect_response:
        return redirect_response
    guard = check_write_permission(membership)
    if guard:
        return guard
    opp = get_object_or_404(PostedOpportunity, pk=pk, status=PostedOpportunity.Status.OPEN)
    opportunity, created, assessment = create_pipeline_from_posted_opportunity(startup, request.user, opp)
    if created:
        log_activity(
            startup,
            request.user,
            "created",
            opportunity,
            f"Added '{opportunity.name}' to pipeline from the Opportunity Board.",
        )
        messages.success(
            request,
            f"Added to your pipeline with fit score {assessment['score']}/5.",
        )
    else:
        messages.info(request, "This opportunity is already in your pipeline.")
    return redirect(opportunity.get_absolute_url())


@login_required
def posted_opportunity_create(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("Only Mangi staff can post opportunities.")
    form = PostedOpportunityForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        opp = form.save(commit=False)
        opp.posted_by = request.user
        opp.save()
        messages.success(request, f"Opportunity '{opp.title}' posted.")
        return redirect("ops_dashboard")
    return render(request, "workspace/posted_opportunity_form.html", {
        "form": form, "action": "Post new opportunity",
    })


@login_required
def posted_opportunity_edit(request, pk):
    if not request.user.is_staff:
        return HttpResponseForbidden("Only Mangi staff can edit posted opportunities.")
    opp = get_object_or_404(PostedOpportunity, pk=pk)
    form = PostedOpportunityForm(request.POST or None, request.FILES or None, instance=opp)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Opportunity updated.")
        return redirect("posted_opportunity_detail", pk=opp.pk)
    return render(request, "workspace/posted_opportunity_form.html", {
        "form": form, "action": "Edit opportunity", "opp": opp,
    })


def pricing_view(request):
    return render(request, "workspace/pricing.html")


@login_required
def posted_opportunity_manage(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("Only Mangi staff can access this page.")
    qs = PostedOpportunity.objects.all()
    opp_type = request.GET.get("type", "")
    status = request.GET.get("status", "")
    search = request.GET.get("q", "")
    if opp_type:
        qs = qs.filter(opportunity_type=opp_type)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(title__icontains=search) | qs.filter(funder_name__icontains=search)
    return render(request, "workspace/posted_opportunity_manage.html", {
        "opportunities": qs,
        "type_choices": PostedOpportunity.OpportunityType.choices,
        "status_choices": PostedOpportunity.Status.choices,
        "active_type": opp_type,
        "active_status": status,
        "search": search,
        "total": PostedOpportunity.objects.count(),
        "open_count": PostedOpportunity.objects.filter(status="open").count(),
        "featured_count": PostedOpportunity.objects.filter(is_featured=True).count(),
    })


@login_required
def posted_opportunity_delete(request, pk):
    if not request.user.is_staff:
        return HttpResponseForbidden("Only Mangi staff can delete posted opportunities.")
    opp = get_object_or_404(PostedOpportunity, pk=pk)
    if request.method == "POST":
        title = opp.title
        opp.delete()
        messages.success(request, f"'{title}' has been deleted.")
        return redirect("posted_opportunity_manage")
    return render(request, "workspace/posted_opportunity_confirm_delete.html", {"opp": opp})


# ─── Superadmin Ops Dashboard ────────────────────────────────────────────────

@login_required
def ops_dashboard(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superadmin access only.")

    qs = PostedOpportunity.objects.all()
    opp_type = request.GET.get("type", "")
    status = request.GET.get("status", "")
    search = request.GET.get("q", "")
    if opp_type:
        qs = qs.filter(opportunity_type=opp_type)
    if status:
        qs = qs.filter(status=status)
    if search:
        qs = qs.filter(title__icontains=search) | qs.filter(funder_name__icontains=search)

    last_run = AgentRun.objects.first()
    recent_runs = AgentRun.objects.all()[:5]

    total_startups = Startup.objects.count()
    total_pipeline_from_board = FundingOpportunity.objects.filter(
        source_posted_opportunity__isnull=False
    ).count()

    return render(request, "workspace/ops_dashboard.html", {
        "opportunities": qs,
        "type_choices": PostedOpportunity.OpportunityType.choices,
        "status_choices": PostedOpportunity.Status.choices,
        "active_type": opp_type,
        "active_status": status,
        "search": search,
        "total": PostedOpportunity.objects.count(),
        "open_count": PostedOpportunity.objects.filter(status="open").count(),
        "closed_count": PostedOpportunity.objects.filter(status="closed").count(),
        "featured_count": PostedOpportunity.objects.filter(is_featured=True).count(),
        "total_startups": total_startups,
        "total_pipeline_from_board": total_pipeline_from_board,
        "last_run": last_run,
        "recent_runs": recent_runs,
    })


@login_required
def ops_run_agent(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superadmin access only.")
    if request.method != "POST":
        return redirect("ops_dashboard")
    run = run_matching_agent(trigger="manual", triggered_by=request.user)
    messages.success(
        request,
        f"Agent completed — {run.pipelines_created} new pipeline entries created "
        f"across {run.startups_processed} startups.",
    )
    return redirect("ops_dashboard")


@login_required
def ops_opportunity_toggle_status(request, pk):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superadmin access only.")
    if request.method != "POST":
        return redirect("ops_dashboard")
    opp = get_object_or_404(PostedOpportunity, pk=pk)
    new_status = request.POST.get("status", opp.status)
    opp.status = new_status
    opp.save(update_fields=["status", "updated_at"])
    messages.success(request, f"'{opp.title}' status updated to {opp.get_status_display()}.")
    return redirect("ops_dashboard")


@login_required
def ops_run_scraper(request):
    """Triggers the automated opportunity web scraper agent."""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superadmin access only.")
    if request.method != "POST":
        return redirect("ops_dashboard")

    from .scraper_agent import run_opportunity_scraper

    custom_url = request.POST.get("custom_url", "").strip()
    custom_urls = [custom_url] if custom_url else None

    stats = run_opportunity_scraper(acting_user=request.user, custom_urls=custom_urls)
    
    if stats["created"] > 0:
        messages.success(
            request,
            f"Scraper Agent finished: Ingested {stats['created']} new opportunities "
            f"({stats['skipped_duplicates']} duplicates skipped). Auto-match & notifications dispatched!"
        )
    else:
        messages.info(
            request,
            f"Scraper Agent finished: {stats['scraped']} items analyzed. No new opportunities found "
            f"({stats['skipped_duplicates']} already exist in database)."
        )

    return redirect("ops_dashboard")



# ── PWA & Web Push Endpoints ──────────────────────────────────────────────────

def pwa_service_worker_view(request):
    """Serve the service worker from the origin root so it can control the app."""
    from django.conf import settings

    worker_path = settings.BASE_DIR / "static" / "workspace" / "sw.js"
    response = HttpResponse(worker_path.read_text(encoding="utf-8"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


@login_required
def pwa_vapid_public_key_view(request):
    """Returns VAPID public key for web push subscription."""
    from .push_service import get_vapid_public_key
    try:
        public_key = get_vapid_public_key()
        return JsonResponse({"publicKey": public_key})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def pwa_subscribe_view(request):
    """Saves a browser push subscription for the logged-in user."""
    from .models import PushSubscription
    try:
        data = json.loads(request.body.decode("utf-8"))
        endpoint = data.get("endpoint")
        keys = data.get("keys", {})
        p256dh = keys.get("p256dh")
        auth = keys.get("auth")
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]

        if not endpoint or not p256dh or not auth:
            return JsonResponse({"error": "Missing subscription parameters"}, status=400)

        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "user": request.user,
                "p256dh": p256dh,
                "auth": auth,
                "user_agent": user_agent,
            },
        )
        return JsonResponse({"status": "subscribed"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def pwa_unsubscribe_view(request):
    """Removes a browser push subscription."""
    from .models import PushSubscription
    try:
        data = json.loads(request.body.decode("utf-8"))
        endpoint = data.get("endpoint")
        if endpoint:
            PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return JsonResponse({"status": "unsubscribed"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def pwa_test_push_view(request):
    """Allows only operations admins to trigger a test push notification."""
    if not request.user.is_superuser:
        return JsonResponse(
            {"error": "Only operations admins can send test push notifications."},
            status=403,
        )

    from .push_service import send_push_to_user
    sent_count = send_push_to_user(
        user=request.user,
        title="FundOS Mobile Notifications Active!",
        body="You will now receive milestone, budget, and funding updates directly on your device.",
        link="/notifications/",
        tag="fundos-test",
    )
    if sent_count > 0:
        return JsonResponse({"status": "success", "sent": sent_count})
    return JsonResponse(
        {"status": "no_active_subscriptions", "message": "No active device subscriptions found."},
        status=400,
    )

