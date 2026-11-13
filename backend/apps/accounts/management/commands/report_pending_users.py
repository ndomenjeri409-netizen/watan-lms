from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from apps.audit.models import AuditLog

from ...models import RoleAssignment, User
from ...roles import Role


class Command(BaseCommand):
    help = "Report users without an active role assignment; does not modify data."

    def handle(self, *args, **options):
        active_assignments = RoleAssignment.objects.filter(
            user_id=OuterRef("pk"),
            is_active=True,
        )
        pending_users = User.objects.annotate(
            has_active_assignment=Exists(active_assignments)
        ).filter(has_active_assignment=False)

        self.stdout.write("Email | Name | Created | Previous role (if recoverable)")
        for user in pending_users.order_by("created_at", "email"):
            previous_role = self._previous_role(user)
            self.stdout.write(
                " | ".join(
                    (
                        user.email or "—",
                        user.display_name or "—",
                        user.created_at.isoformat(),
                        previous_role or "Not recoverable",
                    )
                )
            )
        self.stdout.write(
            "To approve a user, open Users in the app, choose Assign role, "
            "and select the verified role and business unit. No unit was inferred."
        )

    @staticmethod
    def _previous_role(user):
        entries = AuditLog.objects.filter(
            object_type="accounts.User",
            object_id=str(user.pk),
        ).order_by("-created_at")
        for entry in entries:
            for record in (entry.after, entry.before):
                role = record.get("role")
                if role in Role.values:
                    return role
        return None
