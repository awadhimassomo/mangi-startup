from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import (
    BudgetItem, BudgetPlan, CashAdvance, Contact, Disbursement, Expense,
    ExchangeRate, FundingOpportunity, GrantBudgetCategory, InteractionLog,
    ManagedGrant, Milestone, MilestoneEvidence, PostedOpportunity, Startup,
    StartupDocument, StartupMember, Task,
)


User = get_user_model()

FIT_SCORE_CHOICES = [
    (0, "— Unrated"),
    (1, "★ Poor fit"),
    (2, "★★ Weak fit"),
    (3, "★★★ Moderate fit"),
    (4, "★★★★ Good fit"),
    (5, "★★★★★ Perfect fit"),
]


class DateInput(forms.DateInput):
    input_type = "date"


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class StartupForm(forms.ModelForm):
    class Meta:
        model = Startup
        fields = [
            "name",
            "legal_name",
            "country",
            "city",
            "registration_number",
            "year_founded",
            "sector",
            "business_model",
            "short_description",
            "problem_statement",
            "solution_statement",
            "target_market",
            "revenue_model",
            "current_traction",
            "website",
            "contact_email",
            "phone_number",
            "founder_name",
            "funding_goal",
            "logo",
        ]
        widgets = {
            "short_description": forms.Textarea(attrs={"rows": 3}),
            "problem_statement": forms.Textarea(attrs={"rows": 3}),
            "solution_statement": forms.Textarea(attrs={"rows": 3}),
            "target_market": forms.Textarea(attrs={"rows": 3}),
            "revenue_model": forms.Textarea(attrs={"rows": 3}),
            "current_traction": forms.Textarea(attrs={"rows": 3}),
        }


class OpportunityForm(forms.ModelForm):
    fit_score = forms.ChoiceField(choices=FIT_SCORE_CHOICES, required=False)

    class Meta:
        model = FundingOpportunity
        exclude = ("startup", "source_posted_opportunity", "source_of_lead", "created_by", "updated_by")
        widgets = {
            "deadline_date": DateInput(),
            "date_applied": DateInput(),
            "expected_response_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "required_documents": forms.Textarea(attrs={"rows": 2}),
            "feedback": forms.Textarea(attrs={"rows": 3}),
            "tags": forms.TextInput(attrs={"placeholder": "agritech, women-led, east-africa"}),
            "decision_timeline": forms.TextInput(attrs={"placeholder": "e.g. 4 weeks after submission"}),
            "geographic_eligibility": forms.TextInput(attrs={"placeholder": "e.g. East Africa, Tanzania"}),
        }

    def __init__(self, *args, startup=None, **kwargs):
        super().__init__(*args, **kwargs)
        if startup:
            self.fields["assigned_to"].queryset = User.objects.filter(
                startup_memberships__startup=startup, startup_memberships__is_active=True
            ).distinct()


WIN_REASON_CHOICES = [("", "— Select a reason")] + [
    (v, l) for v, l in FundingOpportunity.OutcomeReason.choices
    if v in FundingOpportunity.WIN_REASONS + ["other"]
]
LOSS_REASON_CHOICES = [("", "— Select a reason")] + [
    (v, l) for v, l in FundingOpportunity.OutcomeReason.choices
    if v in FundingOpportunity.LOSS_REASONS + ["other"]
]
ALL_OUTCOME_CHOICES = [("", "— Select outcome reason (required for Won/Lost)")] + list(
    FundingOpportunity.OutcomeReason.choices
)


class StageUpdateForm(forms.Form):
    status = forms.ChoiceField(choices=FundingOpportunity.Status.choices)
    outcome_reason = forms.ChoiceField(
        choices=ALL_OUTCOME_CHOICES,
        required=False,
        label="Outcome reason",
    )
    outcome_notes = forms.CharField(
        required=False,
        label="Outcome notes",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Any extra context…"}),
    )
    note = forms.CharField(
        required=False,
        label="Stage note",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Optional note about this stage change…"}),
    )

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        reason = cleaned.get("outcome_reason")
        if status in ("won", "lost") and not reason:
            self.add_error("outcome_reason", "Please select an outcome reason when marking Won or Lost.")
        return cleaned


class DocumentForm(forms.ModelForm):
    class Meta:
        model = StartupDocument
        exclude = ("startup", "uploaded_by")
        widgets = {
            "expiry_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, startup=None, **kwargs):
        super().__init__(*args, **kwargs)
        if startup:
            self.fields["linked_opportunity"].queryset = startup.opportunities.all()


class BudgetPlanForm(forms.ModelForm):
    class Meta:
        model = BudgetPlan
        exclude = ("startup", "created_by")
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, startup=None, **kwargs):
        super().__init__(*args, **kwargs)
        if startup:
            self.fields["funding_source"].queryset = startup.opportunities.all()


class BudgetItemForm(forms.ModelForm):
    class Meta:
        model = BudgetItem
        exclude = ("budget_plan",)
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        exclude = ("startup", "created_by")
        widgets = {
            "due_date": DateInput(),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, startup=None, **kwargs):
        super().__init__(*args, **kwargs)
        if startup:
            members = User.objects.filter(
                startup_memberships__startup=startup, startup_memberships__is_active=True
            ).distinct()
            self.fields["assigned_to"].queryset = members
            self.fields["related_opportunity"].queryset = startup.opportunities.all()
            self.fields["related_document"].queryset = startup.documents.all()


class StartupMemberForm(forms.ModelForm):
    class Meta:
        model = StartupMember
        fields = ("user", "role", "is_active")

    def __init__(self, *args, startup=None, **kwargs):
        super().__init__(*args, **kwargs)
        if startup:
            self.fields["user"].queryset = User.objects.exclude(startup_memberships__startup=startup)


class DocumentVersionForm(forms.ModelForm):
    class Meta:
        model = StartupDocument
        fields = ("file", "version", "notes", "visibility")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        exclude = ("startup",)
        widgets = {
            "last_interaction_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, startup=None, **kwargs):
        super().__init__(*args, **kwargs)
        if startup:
            self.fields["linked_opportunity"].queryset = FundingOpportunity.objects.filter(
                startup=startup
            ).order_by("name")
            self.fields["linked_opportunity"].required = False


class InteractionLogForm(forms.ModelForm):
    class Meta:
        model = InteractionLog
        fields = ("interaction_type", "date", "summary")
        widgets = {
            "date": DateInput(),
            "summary": forms.Textarea(attrs={"rows": 3}),
        }


# ── Phase 2 forms ─────────────────────────────────────────────────────────────

class ManagedGrantForm(forms.ModelForm):
    class Meta:
        model = ManagedGrant
        exclude = ("startup", "created_by")
        widgets = {
            "start_date": DateInput(),
            "end_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, startup=None, **kwargs):
        super().__init__(*args, **kwargs)
        if startup:
            self.fields["opportunity"].queryset = FundingOpportunity.objects.filter(
                startup=startup, status="won"
            ).order_by("name")
        self.fields["opportunity"].required = False


class DisbursementForm(forms.ModelForm):
    class Meta:
        model = Disbursement
        exclude = ("grant",)
        widgets = {
            "expected_date": DateInput(),
            "actual_receipt_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = Milestone
        exclude = ("grant",)
        widgets = {
            "start_month": DateInput(),
            "end_month": DateInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
            "deliverables": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class MilestoneStatusForm(forms.ModelForm):
    class Meta:
        model = Milestone
        fields = ("status", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class MilestoneEvidenceForm(forms.ModelForm):
    class Meta:
        model = MilestoneEvidence
        fields = ("file", "description")


class GrantBudgetCategoryForm(forms.ModelForm):
    class Meta:
        model = GrantBudgetCategory
        exclude = ("grant",)

    def __init__(self, *args, grant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if grant:
            self.fields["milestone"].queryset = grant.milestones.all()
        self.fields["milestone"].required = False


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        exclude = ("grant", "created_at")
        widgets = {
            "date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, grant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if grant:
            self.fields["category"].queryset = grant.budget_categories.all()
            self.fields["milestone"].queryset = grant.milestones.all()
        self.fields["category"].required = False
        self.fields["milestone"].required = False
        self.fields["approved_by"].required = False
        self.fields["receipt_file"].required = False


class CashAdvanceForm(forms.ModelForm):
    class Meta:
        model = CashAdvance
        exclude = ("grant",)
        widgets = {
            "date_issued": DateInput(),
            "purpose": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class CashAdvanceReconcileForm(forms.ModelForm):
    class Meta:
        model = CashAdvance
        fields = ("receipts_submitted", "cash_returned", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class ExchangeRateForm(forms.ModelForm):
    class Meta:
        model = ExchangeRate
        exclude = ("updated_by", "updated_at")
        widgets = {"rate_date": DateInput()}


class QuickExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ("grant", "date", "description", "amount", "currency", "receipt_file", "payment_method", "paid_by")
        widgets = {
            "date": DateInput(),
        }

    def __init__(self, *args, startup=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if startup:
            self.fields["grant"].queryset = ManagedGrant.objects.filter(
                startup=startup, status="active"
            )
            self.fields["paid_by"].queryset = User.objects.filter(
                startup_memberships__startup=startup,
                startup_memberships__is_active=True,
            ).distinct()
        self.fields["receipt_file"].required = False
        if user:
            self.fields["paid_by"].initial = user


class PostedOpportunityForm(forms.ModelForm):
    class Meta:
        model = PostedOpportunity
        exclude = ("posted_by", "created_at", "updated_at")
        widgets = {
            "short_description": forms.Textarea(attrs={"rows": 4, "placeholder": "Brief overview of the opportunity…"}),
            "eligibility": forms.Textarea(attrs={"rows": 3, "placeholder": "Who can apply? Sector, stage, geography…"}),
            "deadline": forms.DateInput(attrs={"type": "date"}),
            "tags": forms.TextInput(attrs={"placeholder": "agritech, women-led, east-africa"}),
            "geographic_focus": forms.TextInput(attrs={"placeholder": "e.g. East Africa, Tanzania"}),
            "sector_focus": forms.TextInput(attrs={"placeholder": "e.g. Agritech, Fintech"}),
            "poster_image": forms.FileInput(attrs={"accept": "image/*"}),
        }
