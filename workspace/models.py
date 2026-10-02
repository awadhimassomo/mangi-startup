from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse


class Startup(models.Model):
    class Plan(models.TextChoices):
        SOLO  = "solo",  "Solo — $5/mo"
        TEAM  = "team",  "Team — $29/mo"

    PLAN_SEAT_LIMITS = {
        "solo": 1,
        "team": 3,
    }

    PLAN_PRICES = {
        "solo": 5,
        "team": 29,
    }

    name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=120)
    city = models.CharField(max_length=120, blank=True)
    registration_number = models.CharField(max_length=120, blank=True)
    year_founded = models.PositiveIntegerField(null=True, blank=True)
    sector = models.CharField(max_length=120, blank=True)
    business_model = models.CharField(max_length=120, blank=True)
    short_description = models.TextField(blank=True)
    problem_statement = models.TextField(blank=True)
    solution_statement = models.TextField(blank=True)
    target_market = models.TextField(blank=True)
    revenue_model = models.TextField(blank=True)
    current_traction = models.TextField(blank=True)
    website = models.URLField(blank=True)
    contact_email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=50, blank=True)
    founder_name = models.CharField(max_length=255, blank=True)
    funding_goal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    logo = models.ImageField(upload_to="startup_logos/", blank=True)
    plan = models.CharField(max_length=10, choices=Plan.choices, default=Plan.SOLO)
    plan_expires_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def seat_limit(self):
        return self.PLAN_SEAT_LIMITS.get(self.plan, 1)

    @property
    def plan_price(self):
        return self.PLAN_PRICES.get(self.plan, 5)

    @property
    def seats_used(self):
        return self.memberships.filter(is_active=True).count()

    @property
    def seats_available(self):
        return max(0, self.seat_limit - self.seats_used)

    @property
    def funds_raised(self):
        total = self.opportunities.filter(status=FundingOpportunity.Status.WON).aggregate(
            total=models.Sum("amount")
        )["total"]
        return total or Decimal("0.00")


class StartupMember(models.Model):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        STARTUP_ADMIN = "startup_admin", "Startup Admin / Founder"
        TEAM_MEMBER = "team_member", "Team Member"
        FIELD_STAFF = "field_staff", "Field Staff"
        AUDITOR = "auditor", "Auditor / Read-only"
        VIEWER = "viewer", "Viewer / Advisor"

    READ_ONLY_ROLES = ["auditor", "viewer"]
    WRITE_ROLES = ["super_admin", "startup_admin", "team_member", "field_staff"]
    ADMIN_ROLES = ["super_admin", "startup_admin"]
    FIELD_ONLY_ROLES = ["field_staff"]

    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="startup_memberships")
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.TEAM_MEMBER)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("startup", "user")
        ordering = ["startup", "user__username"]

    def __str__(self):
        return f"{self.user} @ {self.startup}"


class FundingOpportunity(models.Model):
    class OpportunityType(models.TextChoices):
        GRANT = "grant", "Grant"
        LOAN = "loan", "Loan"
        DEBT = "debt", "Debt Financing"
        EQUITY = "equity", "Equity"
        ACCELERATOR = "accelerator", "Accelerator"
        COMPETITION = "competition", "Competition"
        FELLOWSHIP = "fellowship", "Fellowship"
        CSR = "csr", "CSR"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        RESEARCHING = "researching", "Researching"
        QUALIFYING = "qualifying", "Qualifying"
        IN_PROGRESS = "in_progress", "Application In Progress"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        SELECTED = "selected", "Selected"
        WON = "won", "Won"
        LOST = "lost", "Lost"
        WITHDRAWN = "withdrawn", "Withdrawn"

    ACTIVE_STATUSES = [
        "researching", "qualifying", "in_progress", "submitted", "under_review", "selected",
    ]
    TERMINAL_STATUSES = ["won", "lost", "withdrawn"]
    DEADLINE_ACTION_STATUSES = ["researching", "qualifying", "in_progress"]

    class OutcomeReason(models.TextChoices):
        STRONG_FIT = "strong_fit", "Strong fit with funder's focus"
        GOOD_NETWORK = "good_network", "Strong relationship / network"
        POLISHED_APPLICATION = "polished_application", "Polished, compelling application"
        COMPETITIVE_AMOUNT = "competitive_amount", "Competitive funding amount requested"
        FAST_RESPONSE = "fast_response", "Fast and responsive communication"
        NO_FIT = "no_fit", "No fit with funder's focus area"
        LATE_SUBMISSION = "late_submission", "Late or incomplete submission"
        GAVE_TO_COMPETITOR = "gave_to_competitor", "Funder awarded to a competitor"
        NO_FEEDBACK = "no_feedback", "No feedback received"
        BUDGET_CUT = "budget_cut", "Funder budget cut or programme closed"
        STRONG_COMPETITION = "strong_competition", "Too much competition"
        WEAK_APPLICATION = "weak_application", "Weak or underprepared application"
        WITHDRAWN_BY_US = "withdrawn_by_us", "We withdrew voluntarily"
        OTHER = "other", "Other"

    WIN_REASONS = [
        "strong_fit", "good_network", "polished_application",
        "competitive_amount", "fast_response",
    ]
    LOSS_REASONS = [
        "no_fit", "late_submission", "gave_to_competitor",
        "no_feedback", "budget_cut", "strong_competition",
        "weak_application", "withdrawn_by_us",
    ]

    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="opportunities")
    source_posted_opportunity = models.ForeignKey(
        "PostedOpportunity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pipeline_opportunities",
        help_text="Shared board opportunity this pipeline item was created from.",
    )
    name = models.CharField(max_length=255)
    funder_name = models.CharField(max_length=255)
    opportunity_type = models.CharField(max_length=30, choices=OpportunityType.choices)
    sector = models.CharField(max_length=120, blank=True, help_text="Focus area or sector targeted by the funder.")
    deadline_date = models.DateField(null=True, blank=True)
    decision_timeline = models.CharField(max_length=100, blank=True, help_text="e.g. '4 weeks after submission'")
    application_link = models.URLField(blank=True)
    funder_website = models.URLField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    amount_min = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Minimum award amount.")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Target / maximum award amount.")
    currency = models.CharField(max_length=10, default="USD")
    geographic_eligibility = models.CharField(max_length=255, blank=True)
    source_of_lead = models.CharField(max_length=255, blank=True, help_text="How you found this opportunity.")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.RESEARCHING)
    fit_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        help_text="Your fit rating: 0 = unrated, 1 (poor fit) to 5 (perfect fit).",
    )
    probability = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Win probability from 0 to 100 percent.",
    )
    tags = models.CharField(max_length=300, blank=True, help_text="Comma-separated tags, e.g. agritech, women-led")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_opportunities",
    )
    notes = models.TextField(blank=True)
    required_documents = models.TextField(blank=True)
    date_applied = models.DateField(null=True, blank=True)
    expected_response_date = models.DateField(null=True, blank=True)
    final_result = models.CharField(max_length=255, blank=True)
    feedback = models.TextField(blank=True)
    outcome_reason = models.CharField(
        max_length=40,
        choices=OutcomeReason.choices,
        blank=True,
        help_text="Required when marking Won, Lost, or Withdrawn.",
    )
    outcome_notes = models.TextField(blank=True, help_text="Any extra context about the outcome.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_opportunities",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_opportunities",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["deadline_date", "-updated_at"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("opportunity_detail", args=[self.pk])

    @property
    def weighted_amount(self):
        return (self.amount or Decimal("0.00")) * Decimal(self.probability) / Decimal("100")

    @property
    def is_overdue(self):
        from django.utils import timezone
        if self.deadline_date and self.status in self.DEADLINE_ACTION_STATUSES:
            return self.deadline_date < timezone.localdate()
        return False

    @property
    def is_deadline_soon(self):
        from django.utils import timezone
        if not self.deadline_date or self.status not in self.DEADLINE_ACTION_STATUSES:
            return False
        days_left = (self.deadline_date - timezone.localdate()).days
        return 0 <= days_left <= 14

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class DocumentCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_required_by_default = models.BooleanField(default=True)
    expected_document_count = models.PositiveIntegerField(default=1)
    weight = models.PositiveSmallIntegerField(default=10)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Document categories"

    def __str__(self):
        return self.name


class StartupDocument(models.Model):
    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        TEAM = "team", "Team"
        ADVISOR = "advisor", "Advisor"

    class CompletionStatus(models.TextChoices):
        REQUIRED = "required", "Required"
        MISSING = "missing", "Missing"
        COMPLETE = "complete", "Complete"

    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="documents")
    category = models.ForeignKey(DocumentCategory, on_delete=models.PROTECT, related_name="documents")
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to="startup_documents/")
    version = models.CharField(max_length=30, default="1.0")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_documents",
    )
    expiry_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.TEAM)
    completion_status = models.CharField(
        max_length=20, choices=CompletionStatus.choices, default=CompletionStatus.COMPLETE
    )
    linked_opportunity = models.ForeignKey(
        FundingOpportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
    )
    parent_document = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__name", "title"]

    def __str__(self):
        return self.title


class BudgetPlan(models.Model):
    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="budget_plans")
    title = models.CharField(max_length=255)
    funding_source = models.ForeignKey(
        FundingOpportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="budget_plans",
    )
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="USD")
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_budget_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

    @property
    def planned_total(self):
        total = self.items.aggregate(total=models.Sum("planned_amount"))["total"]
        return total or Decimal("0.00")

    @property
    def actual_total(self):
        total = self.items.aggregate(total=models.Sum("actual_amount"))["total"]
        return total or Decimal("0.00")

    @property
    def remaining_amount(self):
        return (self.total_amount or Decimal("0.00")) - self.actual_total

    @property
    def remaining_state(self):
        remaining = self.remaining_amount
        if remaining < 0:
            return "over"
        if remaining == 0:
            return "empty"
        return "available"

    @property
    def funding_gap(self):
        return max((self.planned_total or Decimal("0.00")) - (self.total_amount or Decimal("0.00")), Decimal("0.00"))

    @property
    def funding_gap_state(self):
        return "gap" if self.funding_gap > 0 else "covered"


class BudgetItem(models.Model):
    class Category(models.TextChoices):
        OPERATIONS = "operations", "Operations"
        SALARIES = "salaries", "Salaries/Stipends"
        EQUIPMENT = "equipment", "Equipment"
        PRODUCT = "product_development", "Product Development"
        MARKETING = "marketing", "Marketing"
        TRANSPORT = "transport", "Transport/Logistics"
        OFFICE = "office_setup", "Office/Setup Costs"
        PILOT = "pilot_project", "Pilot Project"
        PROFESSIONAL = "professional_services", "Professional Services"
        COMPLIANCE = "compliance_legal", "Compliance/Legal"
        TECHNOLOGY = "technology_software", "Technology/Software"
        RESERVE = "emergency_reserve", "Emergency Reserve"

    class Priority(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    budget_plan = models.ForeignKey(BudgetPlan, on_delete=models.CASCADE, related_name="items")
    category = models.CharField(max_length=40, choices=Category.choices)
    planned_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    actual_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["category"]

    def __str__(self):
        return f"{self.get_category_display()} - {self.budget_plan.title}"

    @property
    def spend_state(self):
        if self.actual_amount > self.planned_amount:
            return "over"
        if self.actual_amount == self.planned_amount:
            return "on_track"
        return "under"


class Task(models.Model):
    class Priority(models.TextChoices):
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        OVERDUE = "overdue", "Overdue"

    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    related_opportunity = models.ForeignKey(
        FundingOpportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    related_document = models.ForeignKey(
        StartupDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tasks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_date", "-updated_at"]

    def __str__(self):
        return self.title


class ActivityLog(models.Model):
    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="activity_logs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    object_id = models.PositiveBigIntegerField()
    description = models.TextField()
    before_state = models.JSONField(null=True, blank=True)
    after_state = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.model_name}"


class OpportunityStageHistory(models.Model):
    opportunity = models.ForeignKey(
        FundingOpportunity, on_delete=models.CASCADE, related_name="stage_history"
    )
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.opportunity} → {self.to_status}"


class ReminderLog(models.Model):
    opportunity = models.ForeignKey(
        FundingOpportunity, on_delete=models.CASCADE, related_name="reminder_logs"
    )
    days_before = models.PositiveSmallIntegerField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("opportunity", "days_before")
        ordering = ["-sent_at"]

    def __str__(self):
        return f"Reminder for {self.opportunity} ({self.days_before}d before)"


class Contact(models.Model):
    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="contacts")
    linked_opportunity = models.ForeignKey(
        FundingOpportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contacts",
    )
    name = models.CharField(max_length=200)
    role = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    last_interaction_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}" + (f" ({self.role})" if self.role else "")


class InteractionLog(models.Model):
    class Type(models.TextChoices):
        MEETING = "meeting", "Meeting"
        CALL = "call", "Call"
        EMAIL = "email", "Email"
        OTHER = "other", "Other"

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="interactions")
    interaction_type = models.CharField(max_length=20, choices=Type.choices, default=Type.EMAIL)
    date = models.DateField()
    summary = models.TextField()
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_interaction_type_display()} with {self.contact} on {self.date}"


# ── Phase 2: Grant & Fund Management ──────────────────────────────────────────

class ManagedGrant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"
        SUSPENDED = "suspended", "Suspended"

    startup = models.ForeignKey(Startup, on_delete=models.CASCADE, related_name="managed_grants")
    opportunity = models.ForeignKey(
        FundingOpportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_grants",
    )
    name = models.CharField(max_length=255)
    reference = models.CharField(max_length=120, blank=True, help_text="Funder's grant reference / contract number.")
    funder_name = models.CharField(max_length=255)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    start_date = models.DateField()
    end_date = models.DateField()
    contract_document = models.FileField(upload_to="grant_contracts/", blank=True)
    project_tag = models.CharField(max_length=255, blank=True, help_text="Which project/programme this grant funds.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="created_grants"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.name} ({self.funder_name})"

    def get_absolute_url(self):
        return reverse("grant_detail", args=[self.pk])

    @property
    def total_received(self):
        from django.db.models import Sum
        return (
            self.disbursements.filter(status=Disbursement.Status.RECEIVED)
            .aggregate(t=Sum("amount"))["t"]
            or Decimal("0")
        )

    @property
    def total_spent(self):
        from django.db.models import Sum
        return self.expenses.aggregate(t=Sum("amount"))["t"] or Decimal("0")

    @property
    def outstanding_advances(self):
        total = Decimal("0")
        for a in self.cash_advances.all():
            if a.balance_outstanding > 0:
                total += a.balance_outstanding
        return total

    @property
    def remaining_funds(self):
        return self.total_amount - self.total_spent

    @property
    def utilization_pct(self):
        if self.total_amount:
            return round(float(self.total_spent) / float(self.total_amount) * 100, 1)
        return 0.0

    @property
    def burn_rate_daily(self):
        from django.utils import timezone
        today = timezone.localdate()
        end = min(today, self.end_date)
        days_elapsed = (end - self.start_date).days
        if days_elapsed > 0 and self.total_spent:
            return self.total_spent / Decimal(days_elapsed)
        return Decimal("0")

    @property
    def forecast_end_date(self):
        remaining = self.remaining_funds
        rate = self.burn_rate_daily
        if rate > 0:
            from django.utils import timezone
            days_left = int(remaining / rate)
            return timezone.localdate() + timedelta(days=days_left)
        return None

    @property
    def is_over_budget_forecast(self):
        forecast = self.forecast_end_date
        return bool(forecast and forecast > self.end_date)

    @property
    def milestone_progress(self):
        total = self.milestones.count()
        if not total:
            return 0
        approved = self.milestones.filter(status=Milestone.Status.APPROVED).count()
        return round(approved / total * 100)


class Disbursement(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RECEIVED = "received", "Received"
        DELAYED = "delayed", "Delayed"

    grant = models.ForeignKey(ManagedGrant, on_delete=models.CASCADE, related_name="disbursements")
    name = models.CharField(max_length=200, help_text="e.g. 'Tranche 1', 'Initial Payment'")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    expected_date = models.DateField()
    actual_receipt_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    bank_account = models.CharField(max_length=255, blank=True)
    exchange_rate = models.DecimalField(
        max_digits=12, decimal_places=6, null=True, blank=True,
        help_text="Exchange rate to base currency, if different."
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["expected_date"]

    def __str__(self):
        return f"{self.name} — {self.grant}"


class Milestone(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not Started"
        IN_PROGRESS = "in_progress", "In Progress"
        SUBMITTED = "submitted", "Submitted"
        VERIFIED = "verified", "Verified"
        APPROVED = "approved", "Approved"

    grant = models.ForeignKey(ManagedGrant, on_delete=models.CASCADE, related_name="milestones")
    order = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    deliverables = models.TextField(blank=True)
    verification_method = models.CharField(max_length=255, blank=True)
    start_month = models.DateField(help_text="First day of the starting month.")
    end_month = models.DateField(help_text="Last day of the ending month.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["order", "start_month"]

    def __str__(self):
        return f"{self.name} ({self.grant})"

    @property
    def progress_pct(self):
        mapping = {
            "not_started": 0, "in_progress": 25,
            "submitted": 60, "verified": 85, "approved": 100,
        }
        return mapping.get(self.status, 0)


class MilestoneEvidence(models.Model):
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, related_name="evidence")
    file = models.FileField(upload_to="milestone_evidence/")
    description = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Evidence for {self.milestone}: {self.description or self.file.name}"


class GrantBudgetCategory(models.Model):
    grant = models.ForeignKey(ManagedGrant, on_delete=models.CASCADE, related_name="budget_categories")
    name = models.CharField(max_length=200)
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name="budget_categories"
    )
    allocated_amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Grant budget categories"

    def __str__(self):
        return f"{self.name} ({self.grant})"

    @property
    def spent(self):
        from django.db.models import Sum
        return self.expenses.aggregate(t=Sum("amount"))["t"] or Decimal("0")

    @property
    def remaining(self):
        return self.allocated_amount - self.spent

    @property
    def utilization_pct(self):
        if self.allocated_amount:
            return round(float(self.spent) / float(self.allocated_amount) * 100, 1)
        return 0.0


class Expense(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        CARD = "card", "Card"
        OTHER = "other", "Other"

    grant = models.ForeignKey(ManagedGrant, on_delete=models.CASCADE, related_name="expenses")
    date = models.DateField()
    description = models.CharField(max_length=255)
    category = models.ForeignKey(
        GrantBudgetCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses"
    )
    milestone = models.ForeignKey(
        Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses"
    )
    vendor = models.CharField(max_length=255, blank=True)
    receipt_number = models.CharField(max_length=120, blank=True)
    receipt_file = models.FileField(upload_to="expense_receipts/", blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="expenses_paid"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses_approved"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.description} — {self.amount} ({self.grant})"


class CashAdvance(models.Model):
    grant = models.ForeignKey(ManagedGrant, on_delete=models.CASCADE, related_name="cash_advances")
    date_issued = models.DateField()
    person = models.CharField(max_length=255)
    purpose = models.TextField()
    amount_given = models.DecimalField(max_digits=14, decimal_places=2)
    receipts_submitted = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    cash_returned = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_issued"]

    def __str__(self):
        return f"Advance to {self.person} on {self.date_issued} ({self.grant})"

    @property
    def balance_outstanding(self):
        return self.amount_given - self.receipts_submitted - self.cash_returned

    @property
    def is_reconciled(self):
        return self.balance_outstanding <= 0

    @property
    def is_aging(self):
        if self.is_reconciled:
            return False
        from django.utils import timezone
        return (timezone.localdate() - self.date_issued).days > 14


# ── Phase 3: Cross-cutting ─────────────────────────────────────────────────────

class ExchangeRate(models.Model):
    class Source(models.TextChoices):
        BOT = "bot", "Bank of Tanzania (BoT)"
        MANUAL = "manual", "Manual Entry"
        CBK = "cbk", "Central Bank of Kenya"
        OTHER = "other", "Other"

    currency_code = models.CharField(
        max_length=10,
        help_text="ISO 4217 code, e.g. USD, EUR, KES.",
    )
    rate_to_tzs = models.DecimalField(
        max_digits=14, decimal_places=4,
        help_text="How many TZS does 1 unit of this currency equal.",
    )
    rate_date = models.DateField()
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.BOT)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-rate_date", "currency_code"]
        unique_together = ("currency_code", "rate_date")

    def __str__(self):
        return f"1 {self.currency_code} = {self.rate_to_tzs} TZS ({self.rate_date})"

    @classmethod
    def get_rate(cls, currency_code, date=None):
        qs = cls.objects.filter(currency_code=currency_code.upper())
        if date:
            qs = qs.filter(rate_date__lte=date)
        return qs.order_by("-rate_date").first()

    @classmethod
    def convert_to_tzs(cls, amount, currency_code, date=None):
        if not amount:
            return Decimal("0")
        if currency_code.upper() == "TZS":
            return amount
        rate_obj = cls.get_rate(currency_code, date)
        if rate_obj:
            return amount * rate_obj.rate_to_tzs
        return None


class Notification(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        DANGER = "danger", "Danger"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    startup = models.ForeignKey(
        Startup, on_delete=models.CASCADE, related_name="notifications", null=True, blank=True
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    is_read = models.BooleanField(default=False)
    link = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.level}] {self.title} → {self.user}"


class PostedOpportunity(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        COMING_SOON = "coming_soon", "Coming Soon"

    class OpportunityType(models.TextChoices):
        GRANT = "grant", "Grant"
        LOAN = "loan", "Loan"
        EQUITY = "equity", "Equity Investment"
        ACCELERATOR = "accelerator", "Accelerator / Incubator"
        COMPETITION = "competition", "Competition / Prize"
        FELLOWSHIP = "fellowship", "Fellowship"
        DEBT = "debt", "Debt Financing"
        OTHER = "other", "Other"

    title = models.CharField(max_length=255)
    funder_name = models.CharField(max_length=255)
    opportunity_type = models.CharField(max_length=30, choices=OpportunityType.choices, default=OpportunityType.GRANT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    short_description = models.TextField(blank=True)
    eligibility = models.TextField(blank=True)
    amount_min = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    amount_max = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default="USD")
    deadline = models.DateField(null=True, blank=True)
    application_link = models.URLField(blank=True)
    geographic_focus = models.CharField(max_length=255, blank=True)
    sector_focus = models.CharField(max_length=255, blank=True)
    tags = models.CharField(max_length=255, blank=True)
    poster_image = models.ImageField(upload_to="opportunity_posters/", null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="posted_opportunities"
    )
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_featured", "-created_at"]

    def __str__(self):
        return f"{self.title} — {self.funder_name}"

    def get_absolute_url(self):
        return reverse("posted_opportunity_detail", args=[self.pk])

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def is_deadline_soon(self):
        if not self.deadline:
            return False
        from django.utils import timezone
        return (self.deadline - timezone.localdate()).days <= 14


class AgentRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    class Trigger(models.TextChoices):
        MANUAL = "manual", "Manual"
        SIGNAL = "signal", "Auto – New Opportunity"
        SCHEDULED = "scheduled", "Scheduled"

    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="agent_runs"
    )
    trigger = models.CharField(max_length=20, choices=Trigger.choices, default=Trigger.MANUAL)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    startups_processed = models.PositiveIntegerField(default=0)
    opportunities_processed = models.PositiveIntegerField(default=0)
    pipelines_created = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"AgentRun [{self.trigger}] {self.started_at:%Y-%m-%d %H:%M} — {self.status}"

    @property
    def duration_seconds(self):
        if self.finished_at:
            return (self.finished_at - self.started_at).seconds
        return None


class PushSubscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.TextField(unique=True)
    p256dh = models.TextField()
    auth = models.TextField()
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"PushSubscription for {self.user.username} ({self.created_at:%Y-%m-%d})"

