from django.core.management.base import BaseCommand
from workspace.scraper_agent import run_opportunity_scraper


class Command(BaseCommand):
    help = "Runs the automated Opportunity Scraper Agent to discover and ingest open funding calls."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            nargs="*",
            type=str,
            help="Optional custom opportunity URLs to scrape directly.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=6,
            help="Maximum items to ingest per feed (default: 6).",
        )

    def handle(self, *args, **options):
        custom_urls = options.get("url") or []
        limit = options.get("limit") or 6

        self.stdout.write(self.style.NOTICE("Starting Opportunity Scraper Agent..."))
        stats = run_opportunity_scraper(custom_urls=custom_urls, max_items_per_feed=limit)

        self.stdout.write(
            self.style.SUCCESS(
                f"Scraper completed: {stats['scraped']} items analyzed, "
                f"{stats['created']} new opportunities created, "
                f"{stats['skipped_duplicates']} duplicates skipped."
            )
        )

        if stats["created_opportunities"]:
            self.stdout.write(self.style.SUCCESS("New opportunities:"))
            for title in stats["created_opportunities"]:
                self.stdout.write(f"  + {title}")

        if stats["errors"]:
            for err in stats["errors"]:
                self.stdout.write(self.style.WARNING(f"  ! {err}"))
