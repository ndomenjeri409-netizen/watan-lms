import django.db.models.deletion
from django.db import migrations, models


def assign_course_units(apps, schema_editor):
    Course = apps.get_model("academics", "Course")

    for course in Course.objects.select_related("department").iterator():
        expected_unit_id = course.department.unit_id
        if course.unit_id and course.unit_id != expected_unit_id:
            raise RuntimeError(
                f"Course {course.pk} has a unit that conflicts with its department."
            )
        if course.unit_id is None:
            Course.objects.filter(pk=course.pk).update(unit_id=expected_unit_id)


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0002_material_is_active"),
        ("org", "0006_a4_unit_ownership"),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="unit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="courses",
                to="org.businessunit",
            ),
        ),
        migrations.RunPython(assign_course_units, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="course",
            name="unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="courses",
                to="org.businessunit",
            ),
        ),
    ]
