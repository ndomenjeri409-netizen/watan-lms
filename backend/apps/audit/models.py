from django.db import models
from django.db.models import Q

from apps.accounts.roles import GLOBAL_ROLES, Role
from common.models import BaseModel


class AuditLogQuerySet(models.QuerySet):
    def for_user(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if user.has_role(*GLOBAL_ROLES):
            return self
        if user.has_role(Role.UNIT_MANAGER):
            return self.filter(
                scope=AuditLog.Scope.UNIT,
                unit_id__in=user.unit_ids(),
            )
        return self.none()

    def update(self, **kwargs):
        raise ValueError("Audit logs are append-only.")

    def delete(self):
        raise ValueError("Audit logs are append-only.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValueError("Audit logs are append-only.")


class AuditLog(BaseModel):
    class Scope(models.TextChoices):
        UNIT = "UNIT"
        GROUP = "GROUP"

    class ActorKind(models.TextChoices):
        USER = "USER"
        SYSTEM = "SYSTEM"

    actor = models.ForeignKey(
        "accounts.User",
        null=True,
        on_delete=models.PROTECT,
        related_name="audit_entries",
    )
    unit = models.ForeignKey(
        "org.BusinessUnit",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_entries",
    )
    scope = models.CharField(max_length=8, choices=Scope.choices)
    actor_kind = models.CharField(max_length=8, choices=ActorKind.choices)
    actor_label = models.CharField(max_length=120, blank=True)
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=80)
    object_id = models.CharField(max_length=64)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    meta = models.JSONField(default=dict, blank=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [  # noqa: RUF012
            models.Index(fields=("unit", "created_at"), name="audit_unit_created_idx"),
            models.Index(
                fields=("actor", "created_at"), name="audit_actor_created_idx"
            ),
        ]
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=(
                    Q(scope="UNIT", unit__isnull=False)
                    | Q(scope="GROUP", unit__isnull=True)
                ),
                name="audit_scope_matches_unit",
            ),
            models.CheckConstraint(
                condition=(
                    Q(actor_kind="USER", actor__isnull=False)
                    | Q(
                        actor_kind="SYSTEM",
                        actor__isnull=True,
                        actor_label__gt="",
                    )
                ),
                name="audit_actor_kind_matches_actor",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Audit logs are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit logs are append-only.")
