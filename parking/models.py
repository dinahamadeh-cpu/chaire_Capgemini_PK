from django.conf import settings
from django.db import models


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

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reservations")
    spot = models.ForeignKey(Spot, on_delete=models.CASCADE, related_name="reservations")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Réservation de {self.user} - {self.spot}"
