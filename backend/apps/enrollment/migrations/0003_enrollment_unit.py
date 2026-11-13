import django.db.models.deletion
from django.db import migrations, models


def assign_enrollment_units(apps, schema_editor):
    Enrollment = apps.get_model("enrollment", "Enrollment")

    for enrollment in Enrollment.objects.select_related("course").iterator():
        expected_unit_id = enrollment.course.unit_id
        if enrollment.unit_id and enrollment.unit_id != expected_unit_id:
            raise RuntimeError(
                f"Enrollment {enrollment.pk} has a unit that conflicts with its course."
            )
        if enrollment.unit_id is None:
            Enrollment.objects.filter(pk=enrollment.pk).update(unit_id=expected_unit_id)


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0003_course_unit"),
        ("enrollment", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="enrollment",
            name="unit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="enrollments",
                to="org.businessunit",
            ),
        ),
        migrations.RunPython(assign_enrollment_units, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="enrollment",
            name="unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="enrollments",
                to="org.businessunit",
            ),
        ),
    ]
