import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.finance.models import Account


class Command(BaseCommand):
    help = "Seed the shared chart of accounts from an accountant-approved JSON file."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, required=True)

    def handle(self, *args, **options):
        path = options["file"]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise CommandError(
                f"Unable to read account definitions at {path}."
            ) from exc
        except json.JSONDecodeError as exc:
            raise CommandError(
                f"Account definitions at {path} are not valid JSON."
            ) from exc

        rows = self._validate_rows(data)
        created = 0
        existing = 0
        resolved = {}
        visiting = set()

        def ensure_account(code):
            nonlocal created, existing
            if code in resolved:
                return resolved[code]
            if code in visiting:
                raise CommandError(f"Account parent cycle detected at {code}.")

            row = rows.get(code)
            if row is None:
                try:
                    return Account.objects.get(code=code)
                except Account.DoesNotExist as exc:
                    raise CommandError(
                        f"Parent account {code} is not defined."
                    ) from exc

            visiting.add(code)
            parent = (
                ensure_account(row["parent"]) if row["parent"] is not None else None
            )
            account = Account.objects.filter(code=code).first()
            if account is None:
                account = Account.objects.create(
                    code=code,
                    name=row["name"],
                    type=row["type"],
                    parent=parent,
                )
                created += 1
            elif (
                account.name != row["name"]
                or account.type != row["type"]
                or account.parent_id != getattr(parent, "pk", None)
            ):
                raise CommandError(
                    f"Existing account {code} differs from the approved chart; "
                    "no account changes were made."
                )
            else:
                existing += 1

            visiting.remove(code)
            resolved[code] = account
            return account

        with transaction.atomic():
            for code in rows:
                ensure_account(code)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} accounts; {existing} already matched."
            )
        )

    @staticmethod
    def _validate_rows(data):
        if not isinstance(data, list) or not data:
            raise CommandError("The chart file must contain a non-empty JSON list.")

        rows = {}
        required_fields = {"code", "name", "type"}
        allowed_fields = required_fields | {"parent"}
        for index, item in enumerate(data):
            if not isinstance(item, dict) or not required_fields.issubset(item):
                raise CommandError(
                    f"Chart row {index + 1} must include code, name, and type."
                )
            if item.keys() - allowed_fields:
                raise CommandError(f"Chart row {index + 1} contains unknown fields.")

            code = item["code"]
            name = item["name"]
            account_type = item["type"]
            parent = item.get("parent")
            if (
                not isinstance(code, str)
                or not code.strip()
                or len(code.strip()) > 16
                or not isinstance(name, str)
                or not name.strip()
                or len(name.strip()) > 120
                or account_type not in Account.Type.values
                or (
                    parent is not None
                    and (not isinstance(parent, str) or not parent.strip())
                )
            ):
                raise CommandError(f"Chart row {index + 1} contains invalid values.")

            code = code.strip()
            if code in rows:
                raise CommandError(f"Duplicate account code in chart: {code}.")
            parent = parent.strip() if parent is not None else None
            if parent == code:
                raise CommandError(f"Account {code} cannot be its own parent.")
            rows[code] = {
                "name": name.strip(),
                "type": account_type,
                "parent": parent,
            }
        return rows
