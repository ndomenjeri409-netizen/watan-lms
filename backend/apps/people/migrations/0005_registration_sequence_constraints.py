import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("people", "0004_backfill_registration_sequences"),
    ]

    operations = [
        migrations.AlterField(
            model_name="registrationsequence",
            name="unit",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="registration_sequences",
                to="org.businessunit",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="registrationsequence",
            name="unique_registration_sequence_department_year",
        ),
        migrations.AddConstraint(
            model_name="registrationsequence",
            constraint=models.UniqueConstraint(
                condition=Q(department__isnull=False),
                fields=("unit", "department", "year"),
                name="uniq_regseq_dept",
            ),
        ),
        migrations.AddConstraint(
            model_name="registrationsequence",
            constraint=models.UniqueConstraint(
                condition=Q(department__isnull=True),
                fields=("unit", "year"),
                name="uniq_regseq_unit",
            ),
        ),
    ]
