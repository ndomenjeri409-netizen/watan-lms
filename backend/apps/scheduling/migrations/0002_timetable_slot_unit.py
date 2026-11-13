import django.db.models.deletion
from django.db import migrations, models


def assign_timetable_slot_units(apps, schema_editor):
    TimetableSlot = apps.get_model("scheduling", "TimetableSlot")

    slots = TimetableSlot.objects.select_related("class_group__course")
    for slot in slots.iterator():
        expected_unit_id = slot.class_group.course.unit_id
        if slot.unit_id and slot.unit_id != expected_unit_id:
            raise RuntimeError(
                f"Timetable slot {slot.pk} has a unit that conflicts with its course."
            )
        if slot.unit_id is None:
            TimetableSlot.objects.filter(pk=slot.pk).update(unit_id=expected_unit_id)


class Migration(migrations.Migration):
    dependencies = [
        ("academics", "0003_course_unit"),
        ("scheduling", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="timetableslot",
            name="unit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="timetable_slots",
                to="org.businessunit",
            ),
        ),
        migrations.RunPython(assign_timetable_slot_units, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="timetableslot",
            name="unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="timetable_slots",
                to="org.businessunit",
            ),
        ),
    ]
