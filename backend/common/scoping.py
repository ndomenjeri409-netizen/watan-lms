from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from rest_framework.exceptions import ValidationError

from apps.accounts.roles import Role


class ScopedQuerySet(models.QuerySet):
    """Every domain queryset implements for_user(); viewsets must call it."""

    def for_user(self, user):
        raise NotImplementedError


class UnitScopedQuerySet(ScopedQuerySet):
    unit_field = "unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_global_read():
            return self
        unit_ids = user.unit_ids()
        if not unit_ids:
            return self.none()
        return self.filter(**{f"{self.unit_field}__in": unit_ids})


class ScopedViewSetMixin:
    """Use on every ModelViewSet to guarantee row-level scoping."""

    def get_queryset(self):
        queryset = super().get_queryset().for_user(self.request.user)
        selected_unit = self.request.query_params.get("unit")
        if selected_unit is None:
            return queryset

        unit_field = getattr(self, "unit_field", None) or getattr(
            queryset, "unit_field", None
        )
        if not unit_field:
            raise ValidationError(
                {"unit": "This endpoint does not support unit filtering."}
            )

        from apps.org.models import BusinessUnit

        try:
            unit_id = BusinessUnit._meta.pk.to_python(selected_unit)
        except (DjangoValidationError, TypeError, ValueError) as exc:
            raise ValidationError({"unit": "Select a valid unit."}) from exc

        user = self.request.user
        if user.has_global_read():
            permitted_unit_ids = BusinessUnit.objects.filter(
                is_active=True
            ).values_list("id", flat=True)
        else:
            permitted_unit_ids = user.unit_ids()

        if not BusinessUnit.objects.filter(
            id=unit_id,
            is_active=True,
            id__in=permitted_unit_ids,
        ).exists():
            raise ValidationError({"unit": "You may not access this unit."})

        return queryset.filter(**{unit_field: unit_id})


def can_write_unit(user, unit):
    if not getattr(user, "is_authenticated", False) or unit is None:
        return False
    if user.has_role(Role.DIRECTOR, Role.AUDITOR):
        return False
    if user.has_role(Role.SUPER_ADMIN, Role.ADMIN):
        return True
    return unit.pk in user.unit_ids()
