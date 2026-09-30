from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from workspace.models import FundingOpportunity, ReminderLog


REMINDER_DAYS = [30, 14, 7, 3, 1]


class Command(BaseCommand):
    help = "Send email reminders for funding deadlines at 30, 14, 7, 3, and 1 days out."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print reminders that would be sent without actually sending emails.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        today = timezone.localdate()
        sent_count = 0
        skipped_count = 0

        active_opps = FundingOpportunity.objects.filter(
            status__in=FundingOpportunity.ACTIVE_STATUSES,
            deadline_date__isnull=False,
        ).select_related("startup", "assigned_to")

        for opp in active_opps:
            days_remaining = (opp.deadline_date - today).days

            if days_remaining not in REMINDER_DAYS:
                continue

            already_sent = ReminderLog.objects.filter(
                opportunity=opp, days_before=days_remaining
            ).exists()

            if already_sent:
                skipped_count += 1
                continue

            recipients = []
            if opp.assigned_to and opp.assigned_to.email:
                recipients.append(opp.assigned_to.email)
            if opp.startup.contact_email and opp.startup.contact_email not in recipients:
                recipients.append(opp.startup.contact_email)

            subject = (
                f"[Mangi FundOS] Reminder: \"{opp.name}\" deadline in {days_remaining} day"
                + ("s" if days_remaining != 1 else "")
            )
            body = (
                f"Hi,\n\n"
                f"This is a reminder that the following funding opportunity is due in "
                f"{days_remaining} day{'s' if days_remaining != 1 else ''}:\n\n"
                f"  Opportunity : {opp.name}\n"
                f"  Funder      : {opp.funder_name}\n"
                f"  Deadline    : {opp.deadline_date}\n"
                f"  Stage       : {opp.get_status_display()}\n"
                f"  Amount      : {opp.currency} {opp.amount}\n\n"
                f"Log in to Mangi FundOS to take action.\n\n"
                f"— Mangi FundOS"
            )

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"[DRY RUN] Would send to {recipients}: {subject}"
                    )
                )
            else:
                if recipients:
                    try:
                        send_mail(
                            subject=subject,
                            message=body,
                            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@mangifundos.com"),
                            recipient_list=recipients,
                            fail_silently=False,
                        )
                        ReminderLog.objects.create(
                            opportunity=opp, days_before=days_remaining
                        )
                        sent_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Sent {days_remaining}d reminder for '{opp.name}' → {recipients}"
                            )
                        )
                    except Exception as exc:
                        self.stderr.write(
                            self.style.ERROR(
                                f"Failed to send reminder for '{opp.name}': {exc}"
                            )
                        )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"No recipients for '{opp.name}' — skipping."
                        )
                    )

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run complete."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. {sent_count} reminder(s) sent, {skipped_count} already sent."
                )
            )
