from django.core.management.base import BaseCommand

from workspace.models import PostedOpportunity


class Command(BaseCommand):
    help = "Delete board opportunities whose deadline has passed."

    def handle(self, *args, **options):
        count = PostedOpportunity.purge_expired()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} expired opportunities."))
