from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


plate_validator = RegexValidator(
    regex=r"^[A-Z]{2}-\d{3}-[A-Z]{2}$",
    message="La plaque doit respecter le format AA-123-AA.",
)

class Parking(models.Model):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    hourly_rate = models.DecimalField(
        "tarif horaire (€)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    max_duration_minutes = models.PositiveIntegerField(
        "durée maximale (minutes)",
        null=True,
        blank=True,
        help_text="Laisser vide si la durée n'est pas limitée.",
    )
    opening_time = models.TimeField(
        "heure d'ouverture",
        null=True,
        blank=True,
        help_text="Laisser vide avec l'heure de fermeture si le parking est ouvert 24h/24.",
    )
    closing_time = models.TimeField("heure de fermeture", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def clean(self):
        if (self.opening_time is None) != (self.closing_time is None):
            raise ValidationError(
                "Renseigner à la fois l'heure d'ouverture et l'heure de fermeture, ou aucune des deux."
            )

    @property
    def max_duration_display(self):
        if self.max_duration_minutes is None:
            return "Illimitée"
        hours, minutes = divmod(self.max_duration_minutes, 60)
        if hours and minutes:
            return f"{hours} h {minutes:02d}"
        if hours:
            return f"{hours} h"
        return f"{minutes} min"

    @property
    def opening_hours_display(self):
        if self.opening_time is None or self.closing_time is None:
            return "Ouvert 24h/24"
        return f"{self.opening_time:%H:%M} – {self.closing_time:%H:%M}"


class Spot(models.Model):
    parking = models.ForeignKey(Parking, on_delete=models.CASCADE, related_name="spots")
    number = models.PositiveIntegerField()
    is_available = models.BooleanField(default=True)
    is_pmr = models.BooleanField("place PMR", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parking", "number"], name="unique_spot_number_per_parking")
        ]
        ordering = ["parking", "number"]

    def __str__(self):
        return f"{self.parking} - place {self.number}"


class DemoPaymentMethod(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="demo_payment_method",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Moyen de paiement simulé de {self.user}"


class Reservation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CANCELLED = "cancelled", "Annulée"
        COMPLETED = "completed", "Terminée"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reservations",
        null=True,
        blank=True,
    )
    spot = models.ForeignKey(Spot, on_delete=models.CASCADE, related_name="reservations")
    plate = models.CharField(max_length=9, validators=[plate_validator])
    duration_minutes = models.PositiveIntegerField(default=60)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    amount_charged = models.DecimalField(
        "montant initialement payé (€)",
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    amount_refunded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    payment_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plate"],
                condition=models.Q(status="active"),
                name="unique_active_reservation_per_plate",
            ),
            models.UniqueConstraint(
                fields=["spot"],
                condition=models.Q(status="active"),
                name="unique_active_reservation_per_spot",
            ),
        ]

    def __str__(self):
        return f"Réservation de {self.plate} - {self.spot}"

    @property
    def actual_duration(self):
        if self.arrived_at is None or self.ended_at is None:
            return None
        return self.ended_at - self.arrived_at

    @property
    def actual_duration_display(self):
        if self.actual_duration is None:
            return None
        minutes = int(self.actual_duration.total_seconds()) // 60
        return f"{minutes} min"

    @property
    def exceeded_duration(self):
        return (
            self.actual_duration is not None
            and self.actual_duration > timedelta(minutes=self.duration_minutes)
        )

    @property
    def expected_end(self):
        start = self.arrived_at or self.created_at
        return start + timedelta(minutes=self.duration_minutes)

    def calculate_final_amount(self):
        if self.ended_at is None:
            return self.amount_paid
        if self.arrived_at is None:
            return Decimal("0.00")
        rate = self.spot.parking.hourly_rate
        if rate is None:
            return self.amount_paid
        if self.actual_duration is None:
            return self.amount_paid
        amount = rate * Decimal(str(self.actual_duration.total_seconds())) / Decimal(3600)
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def settle_final_amount(self):
        charged_amount = self.amount_charged
        if charged_amount == Decimal("0.00"):
            charged_amount = self.amount_paid or Decimal("0.00")
        final_amount = self.calculate_final_amount()
        if final_amount is None:
            self.amount_refunded = Decimal("0.00")
        else:
            self.amount_refunded = max(
                charged_amount - final_amount,
                Decimal("0.00"),
            )
        self.amount_paid = final_amount

    def save(self, *args, **kwargs):
        previous_spot_id = None
        if self.pk:
            previous_spot_id = Reservation.objects.filter(pk=self.pk).values_list("spot_id", flat=True).first()
        super().save(*args, **kwargs)
        for spot_id in {previous_spot_id, self.spot_id} - {None}:
            occupied = Reservation.objects.filter(spot_id=spot_id, status=Reservation.Status.ACTIVE).exists()
            Spot.objects.filter(pk=spot_id).update(is_available=not occupied)

class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    parking = models.ForeignKey(Parking, on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "parking"], name="unique_favorite_per_user_parking")
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} aime {self.parking}"


@receiver(post_delete, sender=Reservation)
def update_spot_availability_after_reservation_delete(sender, instance, **kwargs):
    occupied = Reservation.objects.filter(
        spot_id=instance.spot_id,
        status=Reservation.Status.ACTIVE,
    ).exists()
    Spot.objects.filter(pk=instance.spot_id).update(is_available=not occupied)


class Contravention(models.Model):
    class FineType(models.TextChoices):
        NO_RESERVATION = "no_reservation", "Stationnement sans réservation"
        PMR_ABUSE = "pmr_abuse", "Usage abusif d’une place PMR"
        OVERSTAY = "overstay", "Dépassement de la durée réservée"
        WRONG_SPOT = "wrong_spot", "Stationnement sur une place non autorisée"
        OBSTRUCTING = "obstructing", "Stationnement gênant ou bloquant"
        NO_PAYMENT = "no_payment", "Paiement ou titre de stationnement absent"
        OTHER = "other", "Autres"

    class Status(models.TextChoices):
        ISSUED = "issued", "Émise"
        CONTESTING = "contesting", "En cours de contestation"
        CLOSED = "closed", "Clôturée"

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_contraventions",
        null=True,
        blank=True,
    )
    agent_name = models.CharField(max_length=150, blank=True)
    plate = models.CharField(max_length=9, validators=[plate_validator])
    number = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    fine_type = models.CharField(
        max_length=20,
        choices=FineType.choices,
        default=FineType.OTHER,
    )
    reason = models.CharField(max_length=255)
    amount = models.DecimalField(
        "montant (€)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("50.00"),
        validators=[MinValueValidator(Decimal("30.00")), MaxValueValidator(Decimal("200.00"))],
    )
    comment = models.TextField(blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="received_contraventions",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ISSUED,
    )
    opposition_reason = models.TextField(blank=True)
    opposition_submitted_at = models.DateTimeField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    parking = models.ForeignKey(
        Parking,
        on_delete=models.SET_NULL,
        related_name="contraventions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.agent_id and not self.agent_name:
            self.agent_name = self.agent.get_username()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Contravention {self.plate} - {self.created_at:%d/%m/%Y}"


class UserProfile(models.Model):
    class VehicleModel(models.TextChoices):
        RENAULT_CLIO = "renault_clio", "Renault Clio"
        PEUGEOT_208 = "peugeot_208", "Peugeot 208"
        CITROEN_C3 = "citroen_c3", "Citroën C3"
        DACIA_SANDERO = "dacia_sandero", "Dacia Sandero"
        TOYOTA_YARIS = "toyota_yaris", "Toyota Yaris"
        VOLKSWAGEN_GOLF = "volkswagen_golf", "Volkswagen Golf"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parking_profile",
    )
    phone_number = models.CharField(max_length=20, blank=True)
    vehicle_model = models.CharField(
        "modèle du véhicule",
        max_length=30,
        choices=VehicleModel.choices,
        blank=True,
    )
    pmr_justification_registered = models.BooleanField(
        "Justificatif PMR enregistré",
        default=False,
        help_text="Indique si l’usager déclare disposer d’un justificatif PMR à présenter au contrôle.",
    )
    notifications_enabled = models.BooleanField(
        "Notifications activées",
        default=True,
        help_text="Active ou désactive les rappels de stationnement dans l’application.",
    )

    def __str__(self):
        return f"Profil de {self.user}"
