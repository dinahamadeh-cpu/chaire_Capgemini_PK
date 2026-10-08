from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models


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

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parking", "number"], name="unique_spot_number_per_parking")
        ]
        ordering = ["parking", "number"]

    def __str__(self):
        return f"{self.parking} - place {self.number}"


class Reservation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CANCELLED = "cancelled", "Annulée"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reservations",
        null=True,
        blank=True,
    )
    spot = models.ForeignKey(Spot, on_delete=models.CASCADE, related_name="reservations")
    plate = models.CharField(max_length=9, validators=[plate_validator])
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        is_occupied = Reservation.objects.filter(spot=self.spot, status=Reservation.Status.ACTIVE).exists()
        Spot.objects.filter(pk=self.spot_id).update(is_available=not is_occupied)
