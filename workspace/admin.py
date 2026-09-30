from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import (
    ActivityLog,
    BudgetItem,
    BudgetPlan,
    CashAdvance,
    Contact,
    Disbursement,
    DocumentCategory,
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
    PostedOpportunity,
    ReminderLog,
    Startup,
    StartupDocument,
    StartupMember,
    Task,
)


User = get_user_model()


def validate_unique_user_email(email, user=None):
    email = (email or "").strip().lower()
    if not email:
        return email

    existing_users = User.objects.filter(email__iexact=email)
    if user and user.pk:
        existing_users = existing_users.exclude(pk=user.pk)
    if existing_users.exists():
        raise forms.ValidationError("An account with this email already exists.")
    return email


class UniqueEmailUserChangeForm(UserChangeForm):
    def clean_email(self):
        return validate_unique_user_email(self.cleaned_data.get("email"), self.instance)


class UniqueEmailUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        return validate_unique_user_email(self.cleaned_data.get("email"))


class UniqueEmailUserAdmin(UserAdmin):
    form = UniqueEmailUserChangeForm
    add_form = UniqueEmailUserCreationForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "password1", "password2"),
            },
        ),
    )


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass
admin.site.register(User, UniqueEmailUserAdmin)


class StartupMemberInline(admin.TabularInline):
    model = StartupMember
    extra = 0


class StageHistoryInline(admin.TabularInline):
    model = OpportunityStageHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "changed_at", "note")
    can_delete = False


@admin.register(Startup)
class StartupAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "sector", "funding_goal", "updated_at")
    search_fields = ("name", "legal_name", "country", "sector")
    inlines = [StartupMemberInline]


@admin.register(FundingOpportunity)
class FundingOpportunityAdmin(admin.ModelAdmin):
    list_display = ("name", "startup", "funder_name", "opportunity_type", "status", "fit_score", "amount", "deadline_date", "is_overdue")
    list_filter = ("status", "opportunity_type", "currency", "fit_score")
    search_fields = ("name", "funder_name", "contact_person", "sector", "tags")
    readonly_fields = ("created_at", "updated_at")
    inlines = [StageHistoryInline]

    @admin.display(boolean=True, description="Overdue?")
    def is_overdue(self, obj):
        return obj.is_overdue


@admin.register(OpportunityStageHistory)
class OpportunityStageHistoryAdmin(admin.ModelAdmin):
    list_display = ("opportunity", "from_status", "to_status", "changed_by", "changed_at")
    list_filter = ("to_status",)
    readonly_fields = ("changed_at",)


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = ("opportunity", "days_before", "sent_at")
    list_filter = ("days_before",)
    readonly_fields = ("sent_at",)


@admin.register(StartupDocument)
class StartupDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "startup", "category", "visibility", "completion_status", "version", "updated_at")
    list_filter = ("category", "visibility", "completion_status")
    search_fields = ("title", "startup__name")


class BudgetItemInline(admin.TabularInline):
    model = BudgetItem
    extra = 0


@admin.register(BudgetPlan)
class BudgetPlanAdmin(admin.ModelAdmin):
    list_display = ("title", "startup", "total_amount", "currency", "updated_at")
    list_filter = ("currency",)
    inlines = [BudgetItemInline]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "startup", "status", "priority", "due_date", "assigned_to")
    list_filter = ("status", "priority")
    search_fields = ("title", "startup__name")


class InteractionLogInline(admin.TabularInline):
    model = InteractionLog
    extra = 0
    readonly_fields = ("logged_by", "created_at")


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "email", "phone", "startup", "linked_opportunity", "last_interaction_date")
    list_filter = ("startup",)
    search_fields = ("name", "email", "role")
    inlines = [InteractionLogInline]


@admin.register(InteractionLog)
class InteractionLogAdmin(admin.ModelAdmin):
    list_display = ("contact", "interaction_type", "date", "logged_by")
    list_filter = ("interaction_type",)
    readonly_fields = ("created_at",)


class DisbursementInline(admin.TabularInline):
    model = Disbursement
    extra = 0

class MilestoneInline(admin.TabularInline):
    model = Milestone
    extra = 0

class GrantBudgetCategoryInline(admin.TabularInline):
    model = GrantBudgetCategory
    extra = 0

@admin.register(ManagedGrant)
class ManagedGrantAdmin(admin.ModelAdmin):
    list_display = ("name", "funder_name", "startup", "status", "total_amount", "currency", "start_date", "end_date")
    list_filter = ("status", "currency")
    search_fields = ("name", "funder_name", "reference", "project_tag")
    inlines = [DisbursementInline, MilestoneInline, GrantBudgetCategoryInline]

@admin.register(Disbursement)
class DisbursementAdmin(admin.ModelAdmin):
    list_display = ("name", "grant", "amount", "expected_date", "actual_receipt_date", "status")
    list_filter = ("status",)

@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ("name", "grant", "status", "start_month", "end_month")
    list_filter = ("status",)

admin.site.register(MilestoneEvidence)
admin.site.register(GrantBudgetCategory)

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("description", "grant", "date", "amount", "currency", "payment_method", "paid_by")
    list_filter = ("payment_method", "currency")
    search_fields = ("description", "vendor", "receipt_number")

@admin.register(CashAdvance)
class CashAdvanceAdmin(admin.ModelAdmin):
    list_display = ("person", "grant", "date_issued", "amount_given", "receipts_submitted", "cash_returned", "is_aging")
    list_filter = ("grant__startup",)

    @admin.display(boolean=True, description="Aging?")
    def is_aging(self, obj):
        return obj.is_aging

@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("currency_code", "rate_to_tzs", "rate_date", "source", "updated_by", "updated_at")
    list_filter = ("currency_code", "source")
    ordering = ("-rate_date",)

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "startup", "level", "is_read", "created_at")
    list_filter = ("level", "is_read")
    search_fields = ("title", "body")
    actions = ["mark_all_read"]

    @admin.action(description="Mark selected as read")
    def mark_all_read(self, request, queryset):
        queryset.update(is_read=True)

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("action", "model_name", "object_id", "user", "startup", "created_at")
    list_filter = ("action", "model_name")
    readonly_fields = ("before_state", "after_state", "created_at")
    search_fields = ("description", "model_name")

admin.site.register(DocumentCategory)
admin.site.register(StartupMember)


@admin.register(PostedOpportunity)
class PostedOpportunityAdmin(admin.ModelAdmin):
    list_display = ("title", "funder_name", "opportunity_type", "status", "is_featured", "deadline", "posted_by", "created_at")
    list_filter = ("status", "opportunity_type", "is_featured")
    search_fields = ("title", "funder_name", "tags")
    readonly_fields = ("posted_by", "created_at", "updated_at")
    list_editable = ("status", "is_featured")

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.posted_by = request.user
        super().save_model(request, obj, form, change)
