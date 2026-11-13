from importlib import import_module
from types import SimpleNamespace

from django.test import SimpleTestCase


class FakeQuerySet:
    def __init__(self, manager, records):
        self.manager = manager
        self.records = records

    def using(self, _database):
        return self

    def select_related(self, *_fields):
        return self

    def iterator(self):
        return iter(self.records)

    def filter(self, **criteria):
        return FakeQuerySet(
            self.manager,
            [
                record
                for record in self.records
                if all(getattr(record, key) == value for key, value in criteria.items())
            ],
        )

    def first(self):
        return self.records[0] if self.records else None

    def create(self, **values):
        record = SimpleNamespace(**values)
        record.save = lambda **_kwargs: None
        self.manager.records.append(record)
        return record

    def __iter__(self):
        return iter(self.records)


class FakeManager(FakeQuerySet):
    def __init__(self, records):
        self.records = records
        super().__init__(self, self.records)


class ClassLeadBackfillMigrationTests(SimpleTestCase):
    def test_legacy_class_teachers_become_active_leads_idempotently(self):
        group_without_assignment = SimpleNamespace(
            pk="group-1",
            teacher_id="teacher-1",
            course=SimpleNamespace(unit_id="unit-1"),
        )
        group_with_conflicting_assignments = SimpleNamespace(
            pk="group-2",
            teacher_id="teacher-2",
            course=SimpleNamespace(unit_id="unit-1"),
        )
        class_groups = FakeManager(
            [group_without_assignment, group_with_conflicting_assignments]
        )
        assignments = FakeManager(
            [
                SimpleNamespace(
                    class_group_id="group-2",
                    teacher_id="teacher-3",
                    unit_id="unit-1",
                    role="LEAD",
                    is_active=True,
                    save=lambda **_kwargs: None,
                ),
                SimpleNamespace(
                    class_group_id="group-2",
                    teacher_id="teacher-2",
                    unit_id="unit-1",
                    role="ASSISTANT",
                    is_active=False,
                    save=lambda **_kwargs: None,
                ),
            ]
        )
        historical_apps = SimpleNamespace(
            get_model=lambda app, model: SimpleNamespace(
                objects=class_groups if model == "ClassGroup" else assignments
            )
        )
        schema_editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))
        migration = import_module(
            "apps.scheduling.migrations.0005_remove_classgroup_teacher"
        )

        migration.backfill_legacy_class_leads(historical_apps, schema_editor)
        migration.backfill_legacy_class_leads(historical_apps, schema_editor)

        self.assertEqual(len(assignments.records), 3)
        lead_without_assignment = next(
            row for row in assignments.records if row.class_group_id == "group-1"
        )
        self.assertEqual(lead_without_assignment.teacher_id, "teacher-1")
        self.assertEqual(lead_without_assignment.role, "LEAD")
        self.assertTrue(lead_without_assignment.is_active)

        rows = [row for row in assignments.records if row.class_group_id == "group-2"]
        self.assertEqual(
            {(row.teacher_id, row.role, row.is_active) for row in rows},
            {
                ("teacher-2", "LEAD", True),
                ("teacher-3", "ASSISTANT", True),
            },
        )
