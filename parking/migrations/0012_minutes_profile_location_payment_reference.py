import uuid

from django.conf import settings
from django.db import migrations, models


def convert_durations_to_minutes(apps, schema_editor):
    Reservation = apps.get_model("parking", "Reservation")
    for reservation in Reservation.objects.only("pk", "duration_minutes").iterator():
        Reservation.objects.filter(pk=reservation.pk).update(
            duration_minutes=reservation.duration_minutes * 60
        )


def convert_durations_to_hours(apps, schema_editor):
    Reservation = apps.get_model("parking", "Reservation")
    for reservation in Reservation.objects.only("pk", "duration_minutes").iterator():
        Reservation.objects.filter(pk=reservation.pk).update(
            duration_minutes=reservation.duration_minutes // 60
        )


def populate_payment_references(apps, schema_editor):
    Reservation = apps.get_model("parking", "Reservation")
    for reservation in Reservation.objects.filter(payment_reference__isnull=True).only("pk").iterator():
        Reservation.objects.filter(pk=reservation.pk).update(
            payment_reference=uuid.uuid4()
        )


class Migration(migrations.Migration):
    dependencies = [
        ("parking", "0011_merge_0010_contravention_0010_favorite"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameField(
            model_name="reservation",
            old_name="duration_hours",
            new_name="duration_minutes",
        ),
        migrations.AlterField(
            model_name="reservation",
            name="duration_minutes",
            field=models.PositiveIntegerField(default=60),
        ),
        migrations.RunPython(convert_durations_to_minutes, convert_durations_to_hours),
        migrations.AddField(
            model_name="contravention",
            name="latitude",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="contravention",
            name="longitude",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="reservation",
            name="payment_reference",
            field=models.UUIDField(editable=False, null=True, unique=True),
        ),
        migrations.RunPython(populate_payment_references, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="reservation",
            name="payment_reference",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
            ),
        ),
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("phone_number", models.CharField(blank=True, max_length=20)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=models.CASCADE,
                        related_name="parking_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
