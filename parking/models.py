from django.conf import settings
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


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
