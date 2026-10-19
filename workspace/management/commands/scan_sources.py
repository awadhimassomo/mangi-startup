from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from workspace.models import OpportunitySource
from workspace.source_watch import scan_source


class Command(BaseCommand):
    help = "Scan every watched website for new opportunities and alert staff."

    def handle(self, *args, **options):
        found = []
        for source in OpportunitySource.objects.filter(is_active=True):
            new = scan_source(source)
            found += new
            note = f" (error: {source.last_error})" if source.last_error else ""
            self.stdout.write(f"{source}: {len(new)} new{note}")
        if found:
            emails = list(
                get_user_model().objects.filter(is_staff=True, is_active=True)
                .exclude(email="").values_list("email", flat=True)
            )
            if emails:
                lines = "\n".join(f"- {d.title} ({d.source})" for d in found)
                send_mail(
                    f"{len(found)} new funding opportunities found",
                    f"The watcher found new opportunities waiting for your review:\n\n{lines}",
                    getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    emails,
                    fail_silently=True,
                )
        self.stdout.write(self.style.SUCCESS(f"Done. {len(found)} new opportunities."))
