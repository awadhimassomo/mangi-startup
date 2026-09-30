from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    ActivityLog,
    CashAdvance,
    DocumentCategory,
    ExchangeRate,
    FundingOpportunity,
    ManagedGrant,
    Notification,
    StartupDocument,
    StartupMember,
    Task,
)


DEFAULT_CATEGORY_BLUEPRINT = [
    {
        "name": "Company Documents",
        "description": "Certificate, licenses, company profile, structure, and registration paperwork.",
        "expected_document_count": 5,
        "weight": 20,
    },
    {
        "name": "Financial Documents",
        "description": "Statements, budgets, projections, and banking support documents.",
        "expected_document_count": 5,
        "weight": 25,
    },
    {
        "name": "Fundraising Documents",
        "description": "Pitch deck, one-pager, proposals, investor memo, and use-of-funds plan.",
        "expected_document_count": 5,
        "weight": 25,
    },
    {
        "name": "Impact Documents",
        "description": "Impact reports, SDG alignment, climate data, and beneficiary evidence.",
        "expected_document_count": 5,
        "weight": 15,
    },
    {
        "name": "Team Documents",
        "description": "Founder CVs, team bios, and advisor profiles.",
        "expected_document_count": 3,
        "weight": 10,
    },
    {
        "name": "Legal Documents",
        "description": "Contracts, MOUs, partnership papers, and shareholder agreements.",
        "expected_document_count": 4,
        "weight": 5,
    },
]


def ensure_default_document_categories():
    for blueprint in DEFAULT_CATEGORY_BLUEPRINT:
        DocumentCategory.objects.get_or_create(name=blueprint["name"], defaults=blueprint)


def get_current_membership(user):
    return (
        StartupMember.objects.select_related("startup")
        .filter(user=user, is_active=True)
        .order_by("joined_at")
        .first()
    )


def get_current_startup(user):
    membership = get_current_membership(user)
    return membership.startup if membership else None


def log_activity(startup, user, action, obj, description, before_state=None, after_state=None):
    ActivityLog.objects.create(
        startup=startup,
        user=user,
        action=action,
        model_name=obj.__class__.__name__,
        object_id=obj.pk,
        description=description,
        before_state=before_state,
        after_state=after_state,
    )


# ── Role helpers ──────────────────────────────────────────────────────────────

def is_read_only(membership):
    return membership and membership.role in StartupMember.READ_ONLY_ROLES


def is_admin(membership):
    return membership and membership.role in StartupMember.ADMIN_ROLES


def is_field_staff(membership):
    return membership and membership.role in StartupMember.FIELD_ONLY_ROLES


def can_write(membership):
    return membership and membership.role in StartupMember.WRITE_ROLES


def check_write_permission(membership):
    from django.http import HttpResponseForbidden
    if is_read_only(membership):
        return HttpResponseForbidden("Your role does not have write access.")
    return None


# ── Currency helpers ──────────────────────────────────────────────────────────

def convert_to_tzs(amount, currency_code, date=None):
    return ExchangeRate.convert_to_tzs(amount, currency_code, date)


def get_tzs_rate(currency_code):
    rate_obj = ExchangeRate.get_rate(currency_code)
    return rate_obj.rate_to_tzs if rate_obj else None


# ── Notification helpers ──────────────────────────────────────────────────────

def create_notification(user, startup, title, body="", level="info", link=""):
    Notification.objects.get_or_create(
        user=user,
        startup=startup,
        title=title,
        is_read=False,
        link=link,
        defaults={"body": body, "level": level},
    )


def build_readiness_summary(startup):
    ensure_default_document_categories()
    categories = []
    overall = Decimal("0.00")
    for category in DocumentCategory.objects.all():
        complete_count = startup.documents.filter(
            category=category, completion_status=StartupDocument.CompletionStatus.COMPLETE
        ).count()
        expected = max(category.expected_document_count, 1)
        ratio = min(complete_count / expected, 1)
        score = Decimal(str(ratio * category.weight))
        overall += score
        categories.append(
            {
                "name": category.name,
                "complete_count": complete_count,
                "expected_count": expected,
                "percent": round(ratio * 100),
                "weight": category.weight,
            }
        )

    missing_documents = startup.documents.filter(
        completion_status__in=[
            StartupDocument.CompletionStatus.MISSING,
            StartupDocument.CompletionStatus.REQUIRED,
        ]
    )[:5]
    recommendations = []
    for category in categories:
        if category["percent"] < 100:
            recommendations.append(f"Add more files to {category['name'].lower()}.")
    if not recommendations:
        recommendations.append("Keep documents current and review expiries.")

    return {
        "overall": round(overall),
        "categories": categories,
        "missing_documents": missing_documents,
        "recommendations": recommendations[:3],
    }


def build_dashboard_metrics(startup):
    from .models import PostedOpportunity  # avoid circular at module level
    today = timezone.localdate()
    next_30 = today + timedelta(days=30)
    quarter_start = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)

    opportunities = startup.opportunities.all()
    active_statuses = FundingOpportunity.ACTIVE_STATUSES
    active_opportunities = opportunities.filter(status__in=active_statuses)
    weighted_pipeline = sum((opportunity.weighted_amount for opportunity in active_opportunities), Decimal("0.00"))
    readiness = build_readiness_summary(startup)

    by_status = list(opportunities.values("status").annotate(total=Count("id")).order_by("status"))
    budget_by_category = list(
        startup.budget_plans.values("items__category").annotate(total=Sum("items__planned_amount")).order_by("items__category")
    )
    monthly_applications = list(
        opportunities.filter(date_applied__isnull=False)
        .extra(select={"month": "strftime('%%Y-%%m', date_applied)"})
        .values("month")
        .annotate(total=Count("id"))
        .order_by("month")
    )

    active_grants = startup.managed_grants.filter(status=ManagedGrant.Status.ACTIVE)
    total_active_grant_funding = active_grants.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")

    grant_health = []
    for g in active_grants:
        pct = g.utilization_pct
        if g.is_over_budget_forecast:
            health = "danger"
        elif pct >= 85:
            health = "warning"
        else:
            health = "ok"
        grant_health.append({
            "grant": g, "utilization_pct": pct, "health": health,
        })

    open_advances = [a for g in active_grants for a in g.cash_advances.all() if not a.is_reconciled]
    outstanding_advances_count = len(open_advances)
    outstanding_advances_total = sum(a.balance_outstanding for a in open_advances)
    aging_advances_count = sum(1 for a in open_advances if a.is_aging)

    wins_qtd = opportunities.filter(status="won", updated_at__date__gte=quarter_start).count()
    losses_qtd = opportunities.filter(status="lost", updated_at__date__gte=quarter_start).count()
    won_qs = opportunities.filter(status="won")
    won_total = won_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    won_count = won_qs.count()

    return {
        "funding_goal": startup.funding_goal,
        "funds_raised": startup.funds_raised,
        "active_pipeline": active_opportunities.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "weighted_pipeline": weighted_pipeline,
        "active_opportunities_count": active_opportunities.count(),
        "upcoming_deadlines_count": opportunities.filter(
            deadline_date__gte=today, deadline_date__lte=next_30
        ).count(),
        "readiness_score": readiness["overall"],
        "upcoming_deadlines": opportunities.filter(deadline_date__gte=today).order_by("deadline_date")[:5],
        "recent_opportunities": opportunities.order_by("-updated_at")[:5],
        "missing_documents": startup.documents.filter(
            completion_status__in=[
                StartupDocument.CompletionStatus.MISSING,
                StartupDocument.CompletionStatus.REQUIRED,
            ]
        )[:5],
        "assigned_tasks": startup.tasks.filter(
            Q(status=Task.Status.PENDING) | Q(status=Task.Status.IN_PROGRESS) | Q(status=Task.Status.OVERDUE)
        ).order_by("due_date")[:5],
        "total_active_grant_funding": total_active_grant_funding,
        "grant_health": grant_health,
        "outstanding_advances_count": outstanding_advances_count,
        "outstanding_advances_total": outstanding_advances_total,
        "aging_advances_count": aging_advances_count,
        "wins_qtd": wins_qtd,
        "losses_qtd": losses_qtd,
        "won_total": won_total,
        "won_count": won_count,
        "status_chart": {
            "labels": [item["status"].replace("_", " ").title() for item in by_status],
            "values": [item["total"] for item in by_status],
        },
        "budget_chart": {
            "labels": [item["items__category"].replace("_", " ").title() for item in budget_by_category if item["items__category"]],
            "values": [float(item["total"] or 0) for item in budget_by_category if item["items__category"]],
        },
        "monthly_chart": {
            "labels": [item["month"] for item in monthly_applications],
            "values": [item["total"] for item in monthly_applications],
        },
        "readiness_chart": {
            "labels": [item["name"] for item in readiness["categories"]],
            "values": [item["percent"] for item in readiness["categories"]],
        },
        "readiness": readiness,
        "posted_opportunities": PostedOpportunity.objects.filter(status="open")[:4],
    }
