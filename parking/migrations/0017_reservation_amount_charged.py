from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, models


def backfill_charged_amounts(apps, schema_editor):
    Reservation = apps.get_model("parking", "Reservation")
    for reservation in Reservation.objects.select_related("spot__parking").iterator():
        rate = reservation.spot.parking.hourly_rate
        if rate is None:
            charged_amount = reservation.amount_paid or Decimal("0.00")
        else:
            charged_amount = (
                rate * reservation.duration_minutes / Decimal("60")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        updates = {"amount_charged": charged_amount}
        if reservation.status != "active" and reservation.amount_paid is not None:
            updates["amount_refunded"] = max(
                charged_amount - reservation.amount_paid,
                Decimal("0.00"),
            )
        Reservation.objects.filter(pk=reservation.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("parking", "0016_contravention_fine_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="reservation",
            name="amount_charged",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=10,
                verbose_name="montant initialement payé (€)",
            ),
        ),
        migrations.RunPython(
            backfill_charged_amounts,
            migrations.RunPython.noop,
        ),
    ]
