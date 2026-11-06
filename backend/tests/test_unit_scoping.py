from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import RoleAssignment, User
from apps.accounts.roles import Role
from apps.org.models import BusinessUnit
from common.scoping import (
    ScopedViewSetMixin,
    UnitScopedQuerySet,
    can_write_unit,
)


class AssignmentScopedQuerySet(UnitScopedQuerySet):
    unit_field = "assignments__unit_id"


class UserUnitViewSet(ScopedViewSetMixin, GenericViewSet):
    queryset = User.objects.all()
    unit_field = "assignments__unit_id"


class UnitScopingTests(TestCase):
    def setUp(self):
        self.unit_a = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.unit_b = BusinessUnit.objects.create(
            code="WTA", name="Watan Travel Agency", kind=BusinessUnit.Kind.TRAINING
        )
        self.manager_a = User.objects.create_user(
            "manager-a", role=Role.UNIT_MANAGER, unit=self.unit_a
        )
        self.manager_b = User.objects.create_user(
            "manager-b", role=Role.UNIT_MANAGER, unit=self.unit_b
        )
        self.dual_manager = User.objects.create_user("dual-manager")
        RoleAssignment.objects.create(
            user=self.dual_manager, role=Role.UNIT_MANAGER, unit=self.unit_a
        )
        RoleAssignment.objects.create(
            user=self.dual_manager, role=Role.UNIT_MANAGER, unit=self.unit_b
        )
        self.dual_manager.clear_role_cache()
        self.admin = User.objects.create_user("admin", role=Role.ADMIN)
        self.director = User.objects.create_user("director", role=Role.DIRECTOR)
        self.auditor = User.objects.create_user("auditor", role=Role.AUDITOR)

    def test_queryset_limits_unit_roles_and_allows_group_read(self):
        queryset = AssignmentScopedQuerySet(model=User, using="default")

        self.assertEqual(
            set(queryset.for_user(self.manager_a).values_list("pk", flat=True)),
            {self.manager_a.pk, self.dual_manager.pk},
        )
        self.assertEqual(
            set(queryset.for_user(self.dual_manager).values_list("pk", flat=True)),
            {self.manager_a.pk, self.manager_b.pk, self.dual_manager.pk},
        )
        self.assertEqual(
            set(queryset.for_user(self.director).values_list("pk", flat=True)),
            set(User.objects.values_list("pk", flat=True)),
        )
        self.assertFalse(queryset.for_user(AnonymousUser()).exists())

    def test_unit_query_parameter_is_validated_and_applied(self):
        view = self._view_for(self.manager_a, f"?unit={self.unit_a.pk}")

        self.assertEqual(
            set(view.get_queryset().values_list("pk", flat=True)),
            {self.manager_a.pk, self.dual_manager.pk},
        )

    def test_unit_query_parameter_rejects_unassigned_and_invalid_units(self):
        forbidden = self._view_for(self.manager_a, f"?unit={self.unit_b.pk}")
        with self.assertRaises(ValidationError):
            forbidden.get_queryset()

        invalid = self._view_for(self.manager_a, "?unit=not-a-uuid")
        with self.assertRaises(ValidationError):
            invalid.get_queryset()

    def test_group_reader_may_select_any_active_unit(self):
        view = self._view_for(self.director, f"?unit={self.unit_b.pk}")

        self.assertEqual(
            set(view.get_queryset().values_list("pk", flat=True)),
            {self.manager_b.pk, self.dual_manager.pk},
        )

    def test_writes_are_limited_to_assigned_units_and_exclude_read_only_roles(self):
        self.assertTrue(can_write_unit(self.manager_a, self.unit_a))
        self.assertFalse(can_write_unit(self.manager_a, self.unit_b))
        self.assertTrue(can_write_unit(self.admin, self.unit_b))
        self.assertFalse(can_write_unit(self.director, self.unit_a))
        self.assertFalse(can_write_unit(self.auditor, self.unit_a))
        self.assertFalse(can_write_unit(AnonymousUser(), self.unit_a))

    def _view_for(self, user, query_string):
        request = APIRequestFactory().get(f"/?{query_string.lstrip('?')}")
        request.user = user
        view = UserUnitViewSet()
        view.request = SimpleNamespace(user=user, query_params=request.GET)
        return view
