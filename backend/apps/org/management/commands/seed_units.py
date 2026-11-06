from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.org.models import BusinessUnit


class Command(BaseCommand):
    help = "Create or update business units listed in docs/units.md."

    def handle(self, *args, **options):
        units_file = Path(settings.BASE_DIR).parent / "docs" / "units.md"
        try:
            rows = self._read_units(units_file)
        except OSError as exc:
            raise CommandError(
                f"Unable to read unit definitions at {units_file}."
            ) from exc

        with transaction.atomic():
            for unit in rows:
                _, created = BusinessUnit.objects.update_or_create(
                    code=unit["code"], defaults=unit
                )
                action = "Created" if created else "Updated"
                self.stdout.write(f"{action} {unit['code']} — {unit['name']}")

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(rows)} business units."))

    @staticmethod
    def _read_units(path):
        rows = []
        seen_codes = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != 6 or cells[0] == "Code" or set(cells[0]) <= {"-", ":"}:
                continue
            code, name, kind, currency, modules, _notes = cells
            if code in seen_codes:
                raise CommandError(f"Duplicate business unit code in {path}: {code}")
            seen_codes.add(code)
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "kind": kind,
                    "currency": currency,
                    "modules": {
                        module.strip(): True
                        for module in modules.split(",")
                        if module.strip()
                    },
                    "is_active": True,
                }
            )
        if not rows:
            raise CommandError(f"No business unit definitions were found in {path}.")
        return rows
