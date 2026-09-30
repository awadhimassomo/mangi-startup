"""
Management command to import the legacy "Funding raising.xlsx" spreadsheet
into FundingOpportunity records.

Usage:
    python manage.py import_sheet --file "C:/path/to/Funding raising.xlsx"
    python manage.py import_sheet --file "..." --startup-id 1
    python manage.py import_sheet --file "..." --dry-run
"""
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()

# ── Status mapping from the legacy sheet values ──────────────────────────────
STATUS_MAP = {
    "closed":       "lost",
    "accepted":     "under_review",
    "processing":   "in_progress",
    "overviewing":  "researching",
    "prospect":     "researching",
    "submitted":    "submitted",
    "won":          "won",
    "lost":         "lost",
    "withdrawn":    "withdrawn",
}


def _parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return None


def _parse_amount(value):
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0")


def _map_status(raw):
    if not raw:
        return "researching"
    return STATUS_MAP.get(raw.strip().lower(), "researching")


def _is_url(value):
    if not value or not isinstance(value, str):
        return False
    v = value.strip().lower()
    return v.startswith("http://") or v.startswith("https://")


class Command(BaseCommand):
    help = "Import funding opportunities from the legacy Excel spreadsheet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Absolute path to the .xlsx file.",
        )
        parser.add_argument(
            "--startup-id",
            type=int,
            default=None,
            help="Primary key of the Startup to import into. Defaults to the first startup in the database.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview rows without saving anything.",
        )
        parser.add_argument(
            "--skip-duplicates",
            action="store_true",
            default=True,
            help="Skip rows whose opportunity name already exists for this startup (default: on).",
        )

    def handle(self, *args, **options):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("openpyxl is required: python -m pip install openpyxl")

        from workspace.models import FundingOpportunity, Startup

        # ── Resolve startup ───────────────────────────────────────────────────
        if options["startup_id"]:
            try:
                startup = Startup.objects.get(pk=options["startup_id"])
            except Startup.DoesNotExist:
                raise CommandError(f"No startup with id={options['startup_id']}.")
        else:
            startup = Startup.objects.first()
            if not startup:
                raise CommandError("No startups in the database. Create one first via the web app.")

        self.stdout.write(f"Target startup: {startup.name} (id={startup.pk})")

        # ── Load workbook ─────────────────────────────────────────────────────
        try:
            wb = openpyxl.load_workbook(options["file"], read_only=True, data_only=True)
        except FileNotFoundError:
            raise CommandError(f"File not found: {options['file']}")

        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))

        # Skip header row
        data_rows = rows[1:]

        dry = options["dry_run"]
        skip_dupes = options["skip_duplicates"]
        existing_names = set(
            startup.opportunities.values_list("name", flat=True)
        ) if skip_dupes else set()

        created = skipped = errors = 0

        for idx, row in enumerate(data_rows, start=2):
            # Columns: [0]name [1]date [2]company [3]status [4]notes [5]link
            #          [6]person [7]amount [8]col9 [9]col10 [10]contacts
            name        = row[0]
            date_val    = row[1]
            company     = row[2]
            action      = row[3]
            comment     = row[4]
            link_val    = row[5]
            person      = row[6]
            ticket_size = row[7]
            contact     = row[10] if len(row) > 10 else None

            # Skip blank or summary rows
            if not name or str(name).strip().upper() in ("TOTAL GOAL", "OPPORTUNITY", ""):
                continue

            name = str(name).strip()

            if skip_dupes and name in existing_names:
                self.stdout.write(self.style.WARNING(f"  Row {idx}: SKIP (duplicate) — {name}"))
                skipped += 1
                continue

            status = _map_status(action)
            date_applied = _parse_date(date_val)
            amount = _parse_amount(ticket_size)

            # Build notes: prepend person responsible if present
            notes_parts = []
            if person:
                notes_parts.append(f"Responsible: {str(person).strip()}")
            if comment:
                notes_parts.append(str(comment).strip())
            notes = "\n".join(notes_parts)

            application_link = link_val if _is_url(link_val) else ""
            funder_name = str(company).strip() if company else "Unknown"
            contact_person = str(contact).strip() if contact else ""

            if dry:
                self.stdout.write(
                    f"  Row {idx}: [{status:>12}] {name[:40]:<40} | {funder_name[:25]:<25} "
                    f"| {date_applied} | {amount:>10}"
                )
                created += 1
                continue

            try:
                opp = FundingOpportunity.objects.create(
                    startup=startup,
                    name=name,
                    funder_name=funder_name,
                    opportunity_type="grant",
                    status=status,
                    date_applied=date_applied,
                    amount=amount,
                    notes=notes,
                    application_link=application_link,
                    contact_person=contact_person,
                )
                existing_names.add(name)
                self.stdout.write(self.style.SUCCESS(f"  Row {idx}: CREATED — {opp.name}"))
                created += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f"  Row {idx}: ERROR — {name}: {exc}"))
                errors += 1

        action_word = "Would create" if dry else "Created"
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{action_word} {created} | Skipped (duplicates) {skipped} | Errors {errors}"
        ))
        if dry:
            self.stdout.write(self.style.WARNING("Dry-run — nothing was saved. Remove --dry-run to import."))
