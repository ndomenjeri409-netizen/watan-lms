import django.db.models.deletion
from django.db import migrations, models


DEPARTMENT_UNIT_MAP = {
    "BFS": "WTI",
    "ICT": "WTI",
    "LEK": "WTI",
    "T&T": "WTI",
    "GDS": "WTA",
}


def assign_units(apps, schema_editor):
    BusinessUnit = apps.get_model("org", "BusinessUnit")
    Department = apps.get_model("org", "Department")
    Program = apps.get_model("org", "Program")

    departments = list(Department.objects.all().iterator())
    unmapped_codes = {department.code for department in departments} - set(
        DEPARTMENT_UNIT_MAP
    )
    if unmapped_codes:
        raise RuntimeError(
            "A4 has no business-unit mapping for departments: "
            + ", ".join(sorted(unmapped_codes))
        )

    required_unit_codes = {
        DEPARTMENT_UNIT_MAP[department.code] for department in departments
    }
    units = dict(
        BusinessUnit.objects.filter(code__in=required_unit_codes).values_list(
            "code", "pk"
        )
    )
    missing_units = required_unit_codes - set(units)
    if missing_units:
        raise RuntimeError(
            "A4 department mapping references missing business units: "
            + ", ".join(sorted(missing_units))
        )

    for department in departments:
        expected_unit_id = units[DEPARTMENT_UNIT_MAP[department.code]]
        if department.unit_id and department.unit_id != expected_unit_id:
            raise RuntimeError(
                f"Department {department.code} is assigned to a unit that conflicts "
                "with docs/department_unit_map.csv."
            )
        if department.unit_id is None:
            Department.objects.filter(pk=department.pk).update(unit_id=expected_unit_id)

    for program in Program.objects.select_related("department").iterator():
        expected_unit_id = program.department.unit_id
        if program.unit_id and program.unit_id != expected_unit_id:
            raise RuntimeError(
                f"Program {program.pk} has a unit that conflicts with its department."
            )
        if program.unit_id is None:
            Program.objects.filter(pk=program.pk).update(unit_id=expected_unit_id)


class Migration(migrations.Migration):
    dependencies = [
        ("org", "0005_department_unit"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="unit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="programs",
                to="org.businessunit",
            ),
        ),
        migrations.RunPython(assign_units, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="department",
            name="unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="departments",
                to="org.businessunit",
            ),
        ),
        migrations.AlterField(
            model_name="program",
            name="unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="programs",
                to="org.businessunit",
            ),
        ),
    ]
