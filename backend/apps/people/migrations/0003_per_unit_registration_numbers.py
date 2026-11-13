import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("org", "0007_unit_consistency_guards"),
        ("people", "0002_guardian_is_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="registrationsequence",
            name="unit",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="registration_sequences",
                to="org.businessunit",
            ),
        ),
        migrations.AlterField(
            model_name="registrationsequence",
            name="department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="registration_sequences",
                to="org.department",
            ),
        ),
        migrations.RenameField(
            model_name="registrationsequence",
            old_name="next_value",
            new_name="next_number",
        ),
    ]
