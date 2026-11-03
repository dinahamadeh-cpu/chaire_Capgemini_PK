from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("parking", "0015_pmr_and_contravention_appeals"),
    ]

    operations = [
        migrations.AddField(
            model_name="contravention",
            name="fine_type",
            field=models.CharField(
                choices=[
                    ("no_reservation", "Stationnement sans réservation"),
                    ("pmr_abuse", "Usage abusif d’une place PMR"),
                    ("overstay", "Dépassement de la durée réservée"),
                    ("wrong_spot", "Stationnement sur une place non autorisée"),
                    ("obstructing", "Stationnement gênant ou bloquant"),
                    ("no_payment", "Paiement ou titre de stationnement absent"),
                    ("other", "Autres"),
                ],
                default="other",
                max_length=20,
            ),
        ),
    ]
