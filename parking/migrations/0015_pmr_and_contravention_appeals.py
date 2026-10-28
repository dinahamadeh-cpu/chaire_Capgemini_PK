import decimal
import uuid

import django.core.validators
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def populate_contravention_numbers(apps, schema_editor):
    contraventions = apps.get_model("parking", "Contravention")
    for contravention in contraventions.objects.filter(number__isnull=True).iterator():
        contraventions.objects.filter(pk=contravention.pk).update(number=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [
        ("parking", "0014_spot_is_pmr_userprofile_vehicle_model"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="pmr_justification_registered",
            field=models.BooleanField(
                default=False,
                help_text="Indique si l’usager déclare disposer d’un justificatif PMR à présenter au contrôle.",
                verbose_name="Justificatif PMR enregistré",
            ),
        ),
        migrations.AddField(
            model_name="contravention",
            name="number",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.RunPython(
            populate_contravention_numbers,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="contravention",
            name="number",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name="contravention",
            name="amount",
            field=models.DecimalField(
                decimal_places=2,
                default=decimal.Decimal("50.00"),
                max_digits=5,
                validators=[
                    django.core.validators.MinValueValidator(decimal.Decimal("30.00")),
                    django.core.validators.MaxValueValidator(decimal.Decimal("200.00")),
                ],
                verbose_name="montant (€)",
            ),
        ),
        migrations.AddField(
            model_name="contravention",
            name="comment",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="contravention",
            name="opposition_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="contravention",
            name="opposition_submitted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="contravention",
            name="status",
            field=models.CharField(
                choices=[
                    ("issued", "Émise"),
                    ("contesting", "En cours de contestation"),
                    ("closed", "Clôturée"),
                ],
                default="issued",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="contravention",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="received_contraventions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="contravention",
            name="agent",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_contraventions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
