import django.db.models.deletion
from django.core.exceptions import ObjectDoesNotExist
from django.db import migrations, models


def backfill_audit_logs(apps, schema_editor):
    from common.audit import get_object_unit

    AuditLog = apps.get_model("audit", "AuditLog")
    database = schema_editor.connection.alias
    attributed = 0
    group_level = 0

    for audit_log in AuditLog.objects.using(database).iterator():
        unit_id = audit_log.unit_id
        note = None
        try:
            app_label, model_name = audit_log.object_type.split(".", 1)
            target_model = apps.get_model(app_label.lower(), model_name.lower())
        except (ValueError, LookupError):
            target_model = None
            note = "Target model could not be resolved."

        if target_model is not None:
            try:
                target = target_model._default_manager.using(database).get(
                    pk=audit_log.object_id
                )
            except (target_model.DoesNotExist, ValueError, TypeError):
                if unit_id is None:
                    note = "Target object could not be resolved."
            else:
                try:
                    target_unit = get_object_unit(target)
                except ObjectDoesNotExist:
                    target_unit = None
                if target_unit is not None:
                    unit_id = target_unit.pk
                elif unit_id is None:
                    note = "Target object has no uniquely resolvable business unit."

        if audit_log.actor_id is None:
            audit_log.actor_kind = "SYSTEM"
            audit_log.actor_label = "historical_unknown"
            audit_log.meta = {
                **(audit_log.meta or {}),
                "backfill_actor_note": "The original audit entry had no actor.",
            }
        else:
            audit_log.actor_kind = "USER"
            audit_log.actor_label = ""

        audit_log.unit_id = unit_id
        if unit_id is None:
            audit_log.scope = "GROUP"
            audit_log.meta = {
                **(audit_log.meta or {}),
                "backfill_note": note or "No business unit could be attributed.",
            }
            group_level += 1
        else:
            audit_log.scope = "UNIT"
            attributed += 1
        audit_log.save(
            using=database,
            update_fields=("unit", "scope", "actor_kind", "actor_label", "meta"),
        )

    print(
        "AuditLog backfill: "
        f"{attributed} attributed to units; {group_level} left group-level."
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("audit", "0002_auditlog_unit"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditlog",
            name="scope",
            field=models.CharField(
                blank=True,
                choices=[("UNIT", "Unit"), ("GROUP", "Group")],
                max_length=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="actor_kind",
            field=models.CharField(
                blank=True,
                choices=[("USER", "User"), ("SYSTEM", "System")],
                max_length=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="auditlog",
            name="actor_label",
            field=models.CharField(blank=True, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="auditlog",
            name="meta",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="actor",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="audit_entries",
                to="accounts.user",
            ),
        ),
        migrations.RunPython(backfill_audit_logs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="auditlog",
            name="scope",
            field=models.CharField(
                choices=[("UNIT", "Unit"), ("GROUP", "Group")],
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="actor_kind",
            field=models.CharField(
                choices=[("USER", "User"), ("SYSTEM", "System")],
                max_length=8,
            ),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["unit", "created_at"],
                name="audit_unit_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["actor", "created_at"],
                name="audit_actor_created_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="auditlog",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("scope", "UNIT"), ("unit__isnull", False))
                    | models.Q(("scope", "GROUP"), ("unit__isnull", True))
                ),
                name="audit_scope_matches_unit",
            ),
        ),
        migrations.AddConstraint(
            model_name="auditlog",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("actor__isnull", False), ("actor_kind", "USER"))
                    | models.Q(
                        ("actor__isnull", True),
                        ("actor_kind", "SYSTEM"),
                        ("actor_label__gt", ""),
                    )
                ),
                name="audit_actor_kind_matches_actor",
            ),
        ),
    ]
