from datetime import timedelta

from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from workspace.models import ManagedGrant, StartupMember
from workspace.utils import create_notification

FROM_EMAIL = getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@fundos.app")


def _notify(user, startup, title, body, level, link, send_email=True):
    create_notification(user=user, startup=startup, title=title, body=body, level=level, link=link)
    if send_email and user.email:
        try:
            send_mail(
                subject=f"[FundOS] {title}",
                message=f"{body}\n\nView: {link}",
                from_email=FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            pass


class Command(BaseCommand):
    help = "Generate in-app notifications (and emails) for overdue advances, low funds, upcoming deadlines, and milestone due dates."

    def add_arguments(self, parser):
        parser.add_argument("--no-email", action="store_true", help="Skip email dispatch; create in-app notifications only.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        deadline_horizon = today + timedelta(days=7)
        send_email = not options["no_email"]
        created = 0

        for grant in ManagedGrant.objects.filter(status=ManagedGrant.Status.ACTIVE).select_related("startup"):
            startup = grant.startup
            admins = StartupMember.objects.filter(
                startup=startup,
                role__in=StartupMember.ADMIN_ROLES,
                is_active=True,
            ).select_related("user")

            # 1. Aging cash advances (outstanding > 14 days)
            for advance in grant.cash_advances.all():
                if advance.is_aging:
                    for m in admins:
                        _notify(
                            user=m.user, startup=startup,
                            title=f"Aging advance: {advance.person}",
                            body=f"Cash advance of {grant.currency} {advance.balance_outstanding} issued {advance.date_issued} is unreconciled.",
                            level="danger",
                            link=grant.get_absolute_url() + "#advances",
                            send_email=send_email,
                        )
                        created += 1

            # 2. Low remaining funds (≥90% utilised)
            if grant.utilization_pct >= 90:
                for m in admins:
                    _notify(
                        user=m.user, startup=startup,
                        title=f"Low funds: {grant.name}",
                        body=f"Grant is {grant.utilization_pct}% utilised — only {grant.currency} {grant.remaining_funds} remaining.",
                        level="warning",
                        link=grant.get_absolute_url(),
                        send_email=send_email,
                    )
                    created += 1

            # 3. Forecast end date exceeds grant end date
            if grant.is_over_budget_forecast:
                for m in admins:
                    _notify(
                        user=m.user, startup=startup,
                        title=f"Overspend forecast: {grant.name}",
                        body=f"At current burn rate, funds will be exhausted around {grant.forecast_end_date}, before the grant end {grant.end_date}.",
                        level="danger",
                        link=grant.get_absolute_url(),
                        send_email=send_email,
                    )
                    created += 1

            # 4. Milestones with end_month approaching within 7 days
            for milestone in grant.milestones.exclude(status__in=["approved", "verified"]):
                if milestone.end_month and milestone.end_month <= deadline_horizon:
                    for m in admins:
                        _notify(
                            user=m.user, startup=startup,
                            title=f"Milestone due: {milestone.name}",
                            body=f"'{milestone.name}' on '{grant.name}' is due by {milestone.end_month} — status: {milestone.get_status_display()}.",
                            level="warning",
                            link=grant.get_absolute_url() + "#milestones",
                            send_email=send_email,
                        )
                        created += 1

        # 5. Pipeline deadlines within 7 days
        from workspace.models import FundingOpportunity
        upcoming = FundingOpportunity.objects.filter(
            deadline_date__gte=today,
            deadline_date__lte=deadline_horizon,
            status__in=FundingOpportunity.ACTIVE_STATUSES,
        ).select_related("startup")

        for opp in upcoming:
            opp_startup = opp.startup
            days_left = (opp.deadline_date - today).days
            for m in StartupMember.objects.filter(
                startup=opp_startup, role__in=StartupMember.ADMIN_ROLES, is_active=True
            ).select_related("user"):
                _notify(
                    user=m.user, startup=opp_startup,
                    title=f"Deadline in {days_left}d: {opp.name}",
                    body=f"'{opp.name}' deadline is {opp.deadline_date}.",
                    level="warning",
                    link=opp.get_absolute_url(),
                    send_email=send_email,
                )
                created += 1

        suffix = " (in-app only)" if not send_email else ""
        self.stdout.write(self.style.SUCCESS(f"Created/updated {created} notifications{suffix}."))
