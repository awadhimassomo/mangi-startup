from django.core.management.base import BaseCommand

from workspace.ai_pipeline import run_matching_agent


class Command(BaseCommand):
    help = "Run the opportunity matching agent across all startups and open opportunities."

    def handle(self, *args, **options):
        self.stdout.write("Starting matching agent…")
        run = run_matching_agent(trigger="scheduled")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {run.pipelines_created} pipeline entries created "
                f"({run.startups_processed} startups × {run.opportunities_processed} opportunities)"
            )
        )
