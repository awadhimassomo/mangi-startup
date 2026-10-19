from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from workspace.models import Startup
from workspace.utils import create_notification


class Command(BaseCommand):
    help = "Remind startups with incomplete profiles to finish them (every N days, default 3)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3, help="Days between reminders.")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        sent = 0
        for startup in Startup.objects.prefetch_related("memberships__user"):
            if startup.profile_completion >= 100:
                continue
            last = startup.profile_reminder_sent_at or startup.created_at
            if last > cutoff:
                continue
            missing = ", ".join(startup.missing_profile_fields[:4])
            title = f"Your profile is {startup.profile_completion}% complete"
            body = f"Add your {missing} to get better opportunity matches."
            for membership in startup.memberships.filter(is_active=True):
                user = membership.user
                create_notification(
                    user=user, startup=startup, title=title, body=body, level="info", link=reverse("startup_profile")
                )
                if user.email:
                    send_mail(
                        subject=f"[FundOS] {title}",
                        message=f"{body}\n\nComplete your profile: {reverse('startup_profile')}",
                        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                        recipient_list=[user.email],
                        fail_silently=True,
                    )
            startup.profile_reminder_sent_at = timezone.now()
            startup.save(update_fields=["profile_reminder_sent_at"])
            sent += 1
        self.stdout.write(self.style.SUCCESS(f"Sent reminders to {sent} startups."))
