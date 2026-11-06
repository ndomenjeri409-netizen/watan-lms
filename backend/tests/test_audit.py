from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from apps.accounts.models import User
from apps.accounts.roles import GLOBAL_ROLES, Role
from apps.audit.models import AuditLog
from apps.org.models import BusinessUnit, Campus
from common.audit import record_audit


class AuditLogTests(TestCase):
    def setUp(self):
        self.unit_a = BusinessUnit.objects.create(
            code="AUD-A",
            name="Audit Unit A",
            kind=BusinessUnit.Kind.ACADEMIC,
        )
        self.unit_b = BusinessUnit.objects.create(
            code="AUD-B",
            name="Audit Unit B",
            kind=BusinessUnit.Kind.TRAINING,
        )
        self.actor = User.objects.create_user("audit-user", role=Role.ADMIN)

    def create_log(self, *, scope, unit, actor, actor_kind, actor_label=""):
        return AuditLog.objects.create(
            unit=unit,
            scope=scope,
            actor=actor,
            actor_kind=actor_kind,
            actor_label=actor_label,
            action="test",
            object_type="org.BusinessUnit",
            object_id=str(self.unit_a.pk),
        )

    def test_scope_and_actor_constraints_allow_the_four_valid_combinations(self):
        entries = (
            self.create_log(
                scope=AuditLog.Scope.UNIT,
                unit=self.unit_a,
                actor=self.actor,
                actor_kind=AuditLog.ActorKind.USER,
            ),
            self.create_log(
                scope=AuditLog.Scope.UNIT,
                unit=self.unit_a,
                actor=None,
                actor_kind=AuditLog.ActorKind.SYSTEM,
                actor_label="test-job",
            ),
            self.create_log(
                scope=AuditLog.Scope.GROUP,
                unit=None,
                actor=self.actor,
                actor_kind=AuditLog.ActorKind.USER,
            ),
            self.create_log(
                scope=AuditLog.Scope.GROUP,
                unit=None,
                actor=None,
                actor_kind=AuditLog.ActorKind.SYSTEM,
                actor_label="test-job",
            ),
        )
        self.assertEqual(AuditLog.objects.count(), len(entries))

    def test_scope_and_actor_constraints_reject_invalid_combinations(self):
        invalid_entries = (
            {
                "scope": AuditLog.Scope.UNIT,
                "unit": None,
                "actor": self.actor,
                "actor_kind": AuditLog.ActorKind.USER,
            },
            {
                "scope": AuditLog.Scope.GROUP,
                "unit": self.unit_a,
                "actor": self.actor,
                "actor_kind": AuditLog.ActorKind.USER,
            },
            {
                "scope": AuditLog.Scope.UNIT,
                "unit": self.unit_a,
                "actor": None,
                "actor_kind": AuditLog.ActorKind.USER,
            },
            {
                "scope": AuditLog.Scope.GROUP,
                "unit": None,
                "actor": self.actor,
                "actor_kind": AuditLog.ActorKind.SYSTEM,
                "actor_label": "test-job",
            },
            {
                "scope": AuditLog.Scope.GROUP,
                "unit": None,
                "actor": None,
                "actor_kind": AuditLog.ActorKind.SYSTEM,
            },
        )
        for values in invalid_entries:
            with (
                self.subTest(values=values),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                self.create_log(**values)

    def test_record_audit_requires_actor_and_explicit_scope(self):
        campus = Campus.objects.create(name="Audit Campus", code="AUD-C")

        with self.assertRaisesRegex(ValueError, "actor or non-empty system label"):
            record_audit(action="created", obj=campus, group_level=True)

        with self.assertRaisesRegex(ValueError, "unit or group_level"):
            record_audit(actor=self.actor, action="created", obj=campus)

        group_log = record_audit(
            actor=self.actor,
            action="created",
            obj=campus,
            group_level=True,
        )
        self.assertEqual(group_log.scope, AuditLog.Scope.GROUP)
        self.assertIsNone(group_log.unit_id)

    def test_record_audit_derives_unit_and_labels_system_events(self):
        unit_log = record_audit(
            actor=self.actor,
            action="updated",
            obj=self.unit_a,
        )
        system_log = record_audit(
            system_label="nightly_import",
            action="imported",
            obj=self.unit_b,
        )

        self.assertEqual(unit_log.unit_id, self.unit_a.pk)
        self.assertEqual(unit_log.scope, AuditLog.Scope.UNIT)
        self.assertEqual(unit_log.actor_kind, AuditLog.ActorKind.USER)
        self.assertEqual(system_log.unit_id, self.unit_b.pk)
        self.assertEqual(system_log.actor_kind, AuditLog.ActorKind.SYSTEM)
        self.assertEqual(system_log.actor_label, "nightly_import")

    def test_record_audit_rejects_conflicting_or_blank_actor_labels(self):
        with self.assertRaisesRegex(ValueError, "either an actor or a system label"):
            record_audit(
                actor=self.actor,
                system_label="import",
                action="updated",
                obj=self.unit_a,
            )
        with self.assertRaisesRegex(ValueError, "actor or non-empty system label"):
            record_audit(
                system_label="  ",
                action="imported",
                obj=self.unit_a,
            )

    def test_for_user_limits_unit_managers_and_grants_global_roles(self):
        own_unit_log = self.create_log(
            scope=AuditLog.Scope.UNIT,
            unit=self.unit_a,
            actor=self.actor,
            actor_kind=AuditLog.ActorKind.USER,
        )
        other_unit_log = self.create_log(
            scope=AuditLog.Scope.UNIT,
            unit=self.unit_b,
            actor=self.actor,
            actor_kind=AuditLog.ActorKind.USER,
        )
        group_log = self.create_log(
            scope=AuditLog.Scope.GROUP,
            unit=None,
            actor=self.actor,
            actor_kind=AuditLog.ActorKind.USER,
        )
        manager = User.objects.create_user(
            "audit-manager",
            role=Role.UNIT_MANAGER,
            unit=self.unit_a,
        )

        self.assertEqual(
            list(AuditLog.objects.for_user(manager).values_list("pk", flat=True)),
            [own_unit_log.pk],
        )
        self.assertEqual(
            set(AuditLog.objects.for_user(None).values_list("pk", flat=True)),
            set(),
        )
        for role in GLOBAL_ROLES:
            with self.subTest(role=role):
                user = User.objects.create_user(f"audit-{role}", role=role)
                self.assertSetEqual(
                    set(AuditLog.objects.for_user(user).values_list("pk", flat=True)),
                    {own_unit_log.pk, other_unit_log.pk, group_log.pk},
                )

        group_bursar = User.objects.create_user("audit-group-bursar", role=Role.BURSAR)
        self.assertFalse(AuditLog.objects.for_user(group_bursar).exists())

    def test_audit_logs_remain_append_only_through_queryset_operations(self):
        entry = self.create_log(
            scope=AuditLog.Scope.UNIT,
            unit=self.unit_a,
            actor=self.actor,
            actor_kind=AuditLog.ActorKind.USER,
        )

        with self.assertRaisesRegex(ValueError, "append-only"):
            AuditLog.objects.filter(pk=entry.pk).update(action="changed")
        with self.assertRaisesRegex(ValueError, "append-only"):
            AuditLog.objects.filter(pk=entry.pk).delete()
        with self.assertRaisesRegex(ValueError, "append-only"):
            AuditLog.objects.bulk_update([entry], ["action"])


class AuditLogBackfillMigrationTests(TransactionTestCase):
    migrate_from = ("audit", "0002_auditlog_unit")
    migrate_to = ("audit", "0003_audit_scope_actor_and_meta")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        BusinessUnit = old_apps.get_model("org", "BusinessUnit")
        AuditLog = old_apps.get_model("audit", "AuditLog")
        self.unit = BusinessUnit.objects.create(
            code="MIG-AUD",
            name="Migration Audit Unit",
            kind="ACADEMIC",
        )
        AuditLog.objects.create(
            action="legacy_attributed",
            object_type="org.BusinessUnit",
            object_id=str(self.unit.pk),
        )
        AuditLog.objects.create(
            action="legacy_unresolved",
            object_type="missing.Model",
            object_id="missing",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_backfill_attributes_resolvable_rows_and_explains_group_rows(self):
        AuditLog = self.apps.get_model("audit", "AuditLog")
        attributed = AuditLog.objects.get(action="legacy_attributed")
        unresolved = AuditLog.objects.get(action="legacy_unresolved")

        self.assertEqual(attributed.scope, "UNIT")
        self.assertEqual(attributed.unit_id, self.unit.pk)
        self.assertEqual(attributed.actor_kind, "SYSTEM")
        self.assertEqual(attributed.actor_label, "historical_unknown")
        self.assertEqual(unresolved.scope, "GROUP")
        self.assertIsNone(unresolved.unit_id)
        self.assertIn("backfill_note", unresolved.meta)
