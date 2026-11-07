from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q, Sum
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone


plate_validator = RegexValidator(
    regex=r"^[A-Z]{2}-\d{3}-[A-Z]{2}$",
    message="La plaque doit respecter le format AA-123-AA.",
)


class VehicleType(models.TextChoices):
    CAR = "car", "Voiture"
    MOTORCYCLE = "motorcycle", "Moto"


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
    is_covered = models.BooleanField("parking couvert", default=False)
    max_vehicle_height_m = models.DecimalField(
        "hauteur maximale du véhicule (m)",
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("9.99"))],
        help_text="Laisser vide si la limite de hauteur n'est pas renseignée.",
    )
    has_ev_charging = models.BooleanField("bornes de recharge", default=False)
    late_arrival_grace_minutes = models.PositiveIntegerField(
        "délai d'arrivée tardive (minutes)",
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(1440)],
        help_text="Temps accordé après le signalement du retard (de 1 à 1440 minutes).",
    )
    opening_time = models.TimeField(
        "heure d'ouverture",
        null=True,
        blank=True,
        help_text="Laisser vide avec l'heure de fermeture si le parking est ouvert 24h/24.",
    )
    closing_time = models.TimeField("heure de fermeture", null=True, blank=True)
    has_step_free_access = models.BooleanField("accès sans marche", default=False)
    has_accessible_elevator = models.BooleanField("ascenseur accessible", default=False)
    has_accessible_restroom = models.BooleanField("toilettes accessibles", default=False)
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


class ParkingHoursException(models.Model):
    parking = models.ForeignKey(
        Parking,
        on_delete=models.CASCADE,
        related_name="hours_exceptions",
    )
    date = models.DateField()
    is_closed = models.BooleanField("fermé toute la journée", default=False)
    opening_time = models.TimeField("heure d'ouverture", null=True, blank=True)
    closing_time = models.TimeField("heure de fermeture", null=True, blank=True)
    reason = models.CharField(max_length=250, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parking", "date"],
                name="unique_parking_hours_exception_per_day",
            )
        ]
        ordering = ["date", "parking"]

    def clean(self):
        if self.is_closed:
            if self.opening_time or self.closing_time:
                raise ValidationError(
                    "Une journée fermée ne peut pas avoir d’heures d’ouverture."
                )
        elif (
            self.opening_time is None
            or self.closing_time is None
            or self.opening_time >= self.closing_time
        ):
            raise ValidationError(
                "Renseignez des horaires valides pour cette journée."
            )

    def __str__(self):
        return f"{self.parking} — {self.date:%d/%m/%Y}"


class Spot(models.Model):
    parking = models.ForeignKey(Parking, on_delete=models.CASCADE, related_name="spots")
    number = models.PositiveIntegerField()
    is_available = models.BooleanField(default=True)
    is_pmr = models.BooleanField("place PMR", default=False)
    availability_updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parking", "number"], name="unique_spot_number_per_parking")
        ]
        ordering = ["parking", "number"]

    def __str__(self):
        return f"{self.parking} - place {self.number}"


class ParkingSpotClosure(models.Model):
    spot = models.ForeignKey(
        Spot,
        on_delete=models.CASCADE,
        related_name="unavailability_periods",
    )
    reason = models.CharField(max_length=250)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_spot_closures",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_at", "-created_at"]

    def clean(self):
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError(
                {"ends_at": "La fin de l’indisponibilité doit suivre son début."}
            )

    def __str__(self):
        return f"{self.spot} indisponible : {self.reason}"


class DemoPaymentMethod(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="demo_payment_methods",
    )
    name = models.CharField(
        "nom du moyen de paiement",
        max_length=50,
        default="Moyen enregistré",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} de {self.user}"


class Reservation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CANCELLED = "cancelled", "Annulée"
        COMPLETED = "completed", "Terminée"
        EXPIRED = "expired", "Expirée"
        REFUSED = "refused", "Refusée par un agent"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reservations",
        null=True,
        blank=True,
    )
    spot = models.ForeignKey(Spot, on_delete=models.CASCADE, related_name="reservations")
    saved_vehicle = models.ForeignKey(
        "SavedVehicle",
        on_delete=models.SET_NULL,
        related_name="reservations",
        null=True,
        blank=True,
    )
    plate = models.CharField(max_length=9, validators=[plate_validator])
    vehicle_type = models.CharField(
        "type de véhicule",
        max_length=12,
        choices=VehicleType.choices,
        default=VehicleType.CAR,
    )
    starts_at = models.DateTimeField(null=True, blank=True)
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
    qr_verified_bucket = models.PositiveBigIntegerField(null=True, blank=True)
    late_arrival_reported_at = models.DateTimeField(null=True, blank=True)
    late_arrival_deadline = models.DateTimeField(null=True, blank=True)
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
        start = self.arrived_at or self.starts_at or self.created_at
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
            sync_spot_availability(spot_id)


class ReservationHistoryEntry(models.Model):
    class Action(models.TextChoices):
        EXTENDED = "extended", "Durée prolongée"
        CANCELLED = "cancelled", "Réservation annulée"
        DEPARTED = "departed", "Départ déclaré"
        AGENT_CLOSED = "agent_closed", "Stationnement clôturé par un agent"
        AGENT_REFUSED = "agent_refused", "Réservation refusée par un agent"

    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.SET_NULL,
        related_name="history_entries",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reservation_history_actions",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    summary = models.CharField(max_length=500)
    plate = models.CharField(max_length=9, blank=True)
    parking_name = models.CharField(max_length=200, blank=True)
    spot_number = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_action_display()} — {self.created_at:%d/%m/%Y %H:%M}"


class ParkingReview(models.Model):
    reservation = models.OneToOneField(
        Reservation,
        on_delete=models.CASCADE,
        related_name="review",
    )
    parking = models.ForeignKey(
        Parking,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="parking_reviews",
        null=True,
        blank=True,
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.parking} — {self.rating}/5"


def notify_parking_availability(spot_id):
    spot = Spot.objects.select_related("parking").get(pk=spot_id)
    now = timezone.now()
    available_count = Spot.objects.filter(
        parking_id=spot.parking_id,
        is_available=True,
    ).exclude(
        unavailability_periods__closed_at__isnull=True,
        unavailability_periods__starts_at__lte=now,
        unavailability_periods__ends_at__gt=now,
    ).distinct().count()
    if available_count == 0:
        return
    waitlist_entries = list(
        ParkingWaitlist.objects.filter(parking_id=spot.parking_id)
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))
        .select_related("user")
    )
    favorite_alerts = list(
        Favorite.objects.filter(
            parking_id=spot.parking_id,
            availability_alert_threshold__isnull=False,
            availability_alert_sent_at__isnull=True,
            availability_alert_threshold__lte=available_count,
        ).select_related("user")
    )
    UserNotification.objects.bulk_create(
        [
            UserNotification(
                user=entry.user,
                title="Une place s’est libérée",
                message=(
                    f"Une place est disponible au {spot.parking.name} "
                    f"pendant votre créneau d’attente. Consultez le parking pour la réserver."
                ),
                url=f"/parkings/{spot.parking_id}/",
            )
            for entry in waitlist_entries
        ]
        + [
            UserNotification(
                user=favorite.user,
                title="Disponibilité de votre parking favori",
                message=(
                    f"{available_count} places sont disponibles au "
                    f"{spot.parking.name}, selon le seuil que vous avez choisi."
                ),
                url=f"/parkings/{spot.parking_id}/",
            )
            for favorite in favorite_alerts
        ]
    )
    if waitlist_entries:
        ParkingWaitlist.objects.filter(
            pk__in=[entry.pk for entry in waitlist_entries]
        ).delete()
    if favorite_alerts:
        Favorite.objects.filter(
            pk__in=[favorite.pk for favorite in favorite_alerts]
        ).update(availability_alert_sent_at=now)


def sync_spot_availability(spot_id):
    occupied = Reservation.objects.filter(
        spot_id=spot_id,
        status=Reservation.Status.ACTIVE,
    ).exists()
    availability_changed = Spot.objects.filter(pk=spot_id).exclude(
        is_available=not occupied
    ).update(
        is_available=not occupied,
        availability_updated_at=timezone.now(),
    )
    if availability_changed and not occupied:
        notify_parking_availability(spot_id)

class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    parking = models.ForeignKey(Parking, on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)
    availability_alert_threshold = models.PositiveIntegerField(
        "alerte à partir de ce nombre de places libres",
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
    )
    availability_alert_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "parking"], name="unique_favorite_per_user_parking")
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} aime {self.parking}"


class ParkingWaitlist(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parking_waitlist_entries",
    )
    parking = models.ForeignKey(
        Parking,
        on_delete=models.CASCADE,
        related_name="waitlist_entries",
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "parking"],
                name="unique_parking_waitlist_entry",
            )
        ]
        ordering = ["joined_at"]

    def __str__(self):
        return f"{self.user} attend une place à {self.parking}"

    def clean(self):
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValidationError(
                {"ends_at": "La fin du créneau doit suivre son début."}
            )


class UserNotification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parking_notifications",
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.user}"


class ParkingReport(models.Model):
    class Category(models.TextChoices):
        OCCUPIED = "occupied", "Place occupée"
        EQUIPMENT = "equipment", "Équipement en panne"
        INFORMATION = "information", "Information incorrecte"
        DANGER = "danger", "Danger immédiat"
        FORGOTTEN_ITEM = "forgotten_item", "Objet oublié"
        VEHICLE_DAMAGE = "vehicle_damage", "Véhicule endommagé"

    class Status(models.TextChoices):
        NEW = "new", "Nouveau"
        IN_PROGRESS = "in_progress", "En cours"
        RESOLVED = "resolved", "Résolu"
        REFUSED = "refused", "Refusé"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="parking_reports",
        null=True,
        blank=True,
    )
    parking = models.ForeignKey(
        Parking,
        on_delete=models.SET_NULL,
        related_name="reports",
        null=True,
        blank=True,
    )
    spot = models.ForeignKey(
        Spot,
        on_delete=models.SET_NULL,
        related_name="reports",
        null=True,
        blank=True,
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.SET_NULL,
        related_name="reports",
        null=True,
        blank=True,
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    title = models.CharField(max_length=150, blank=True, default="")
    description = models.TextField(max_length=1000)
    photo = models.FileField(
        "photo facultative",
        upload_to="parking_reports/%Y/%m/",
        blank=True,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.NEW,
    )
    class Priority(models.IntegerChoices):
        LOW = 1, "Basse"
        NORMAL = 2, "Normale"
        HIGH = 3, "Haute"
        URGENT = 4, "Urgente"

    priority = models.PositiveSmallIntegerField(
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_parking_reports",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.spot_id and self.parking_id and self.spot.parking_id != self.parking_id:
            raise ValidationError(
                {"spot": "La place sélectionnée n’appartient pas à ce parking."}
            )
        if self.reservation_id:
            reservation_parking_id = self.reservation.spot.parking_id
            if self.parking_id and self.parking_id != reservation_parking_id:
                raise ValidationError(
                    {"reservation": "La réservation sélectionnée ne concerne pas ce parking."}
                )
            if self.spot_id and self.spot_id != self.reservation.spot_id:
                raise ValidationError(
                    {"reservation": "La place ne correspond pas à la réservation sélectionnée."}
                )

    def __str__(self):
        return (
            f"{self.title or self.get_category_display()} — "
            f"{self.parking or 'Parking supprimé'}"
        )


class ParkingReportComment(models.Model):
    report = models.ForeignKey(
        ParkingReport,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    message = models.TextField(max_length=1000)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="parking_report_comments",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Commentaire du signalement {self.report_id}"


class AgentActionLog(models.Model):
    class ActionType(models.TextChoices):
        REPORT_STATUS = "report_status", "Modification du statut d’un signalement"
        REPORT_COMMENT = "report_comment", "Commentaire sur un signalement"
        SPOT_BLOCKED = "spot_blocked", "Indisponibilité créée"
        SPOT_UNBLOCKED = "spot_unblocked", "Indisponibilité levée"
        CONTRAVENTION_CREATED = "contravention_created", "Contravention créée"
        RESERVATION_CLOSED = "reservation_closed", "Stationnement clôturé"
        RESERVATION_REFUSED = "reservation_refused", "Réservation refusée"
        REPORT_ASSIGNED = "report_assigned", "Signalement attribué"
        REPORT_PRIORITY = "report_priority", "Priorité du signalement modifiée"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="agent_action_logs",
        null=True,
        blank=True,
    )
    action_type = models.CharField(max_length=32, choices=ActionType.choices)
    summary = models.CharField(max_length=500)
    report = models.ForeignKey(
        ParkingReport,
        on_delete=models.SET_NULL,
        related_name="agent_actions",
        null=True,
        blank=True,
    )
    spot_closure = models.ForeignKey(
        ParkingSpotClosure,
        on_delete=models.SET_NULL,
        related_name="agent_actions",
        null=True,
        blank=True,
    )
    contravention = models.ForeignKey(
        "Contravention",
        on_delete=models.SET_NULL,
        related_name="agent_actions",
        null=True,
        blank=True,
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.SET_NULL,
        related_name="agent_actions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.get_action_type_display()} — {self.created_at:%d/%m/%Y %H:%M}"


@receiver(post_delete, sender=Reservation)
def update_spot_availability_after_reservation_delete(sender, instance, **kwargs):
    sync_spot_availability(instance.spot_id)


@receiver(post_delete, sender=ParkingReport)
def delete_parking_report_photo(sender, instance, **kwargs):
    if instance.photo:
        instance.photo.delete(save=False)


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
        APPEAL_WON = "appeal_won", "Contestation acceptée"
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
    photo = models.FileField(
        "photo (facultative)",
        upload_to="contraventions/",
        blank=True,
    )
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
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.UUIDField(null=True, blank=True, unique=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    parking = models.ForeignKey(
        Parking,
        on_delete=models.SET_NULL,
        related_name="contraventions",
        null=True,
        blank=True,
    )
    spot = models.ForeignKey(
        Spot,
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
        YAMAHA_MT07 = "yamaha_mt07", "Yamaha MT-07"
        HONDA_CB500F = "honda_cb500f", "Honda CB500F"
        BMW_R1250GS = "bmw_r1250gs", "BMW R 1250 GS"
        YAMAHA_TMAX = "yamaha_tmax", "Yamaha TMAX"
        HONDA_PCX = "honda_pcx", "Honda PCX"
        KAWASAKI_Z650 = "kawasaki_z650", "Kawasaki Z650"

    VEHICLE_MODEL_TYPES = {
        "renault_clio": VehicleType.CAR,
        "peugeot_208": VehicleType.CAR,
        "citroen_c3": VehicleType.CAR,
        "dacia_sandero": VehicleType.CAR,
        "toyota_yaris": VehicleType.CAR,
        "volkswagen_golf": VehicleType.CAR,
        "yamaha_mt07": VehicleType.MOTORCYCLE,
        "honda_cb500f": VehicleType.MOTORCYCLE,
        "bmw_r1250gs": VehicleType.MOTORCYCLE,
        "yamaha_tmax": VehicleType.MOTORCYCLE,
        "honda_pcx": VehicleType.MOTORCYCLE,
        "kawasaki_z650": VehicleType.MOTORCYCLE,
    }
    VEHICLE_MODEL_HEIGHTS = {
        "renault_clio": Decimal("1.45"),
        "peugeot_208": Decimal("1.43"),
        "citroen_c3": Decimal("1.47"),
        "dacia_sandero": Decimal("1.50"),
        "toyota_yaris": Decimal("1.50"),
        "volkswagen_golf": Decimal("1.49"),
        "yamaha_mt07": Decimal("1.11"),
        "honda_cb500f": Decimal("1.15"),
        "bmw_r1250gs": Decimal("1.46"),
        "yamaha_tmax": Decimal("1.42"),
        "honda_pcx": Decimal("1.10"),
        "kawasaki_z650": Decimal("1.08"),
    }

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parking_profile",
    )
    vehicle_type = models.CharField(
        "type de véhicule",
        max_length=12,
        choices=VehicleType.choices,
        default=VehicleType.CAR,
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
    prefers_covered_parking = models.BooleanField(
        "parkings couverts uniquement",
        default=False,
    )
    vehicle_height_m = models.DecimalField(
        "hauteur du véhicule (m)",
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("9.99"))],
    )
    requires_ev_charging = models.BooleanField(
        "borne de recharge nécessaire",
        default=False,
    )
    color_vision_mode = models.BooleanField(
        "mode adapté au daltonisme",
        default=False,
        help_text="Renforce les contrastes et distingue les statuts autrement que par la couleur.",
    )
    monthly_budget_limit = models.DecimalField(
        "budget mensuel (€)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    def __str__(self):
        return f"Profil de {self.user}"


class SavedVehicle(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_vehicles",
    )
    plate = models.CharField(max_length=9, validators=[plate_validator])
    vehicle_type = models.CharField(
        max_length=12,
        choices=VehicleType.choices,
        default=VehicleType.CAR,
    )
    model = models.CharField(
        max_length=30,
        choices=UserProfile.VehicleModel.choices,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "plate"],
                name="unique_saved_vehicle_plate_per_user",
            )
        ]
        ordering = ["plate"]

    def clean(self):
        if self.model and UserProfile.VEHICLE_MODEL_TYPES.get(self.model) != self.vehicle_type:
            raise ValidationError({"model": "Ce modèle ne correspond pas au type de véhicule."})

    def __str__(self):
        return f"{self.plate} — {self.get_vehicle_type_display()}"


class RecurringReservationPlan(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Lundi"
        TUESDAY = 1, "Mardi"
        WEDNESDAY = 2, "Mercredi"
        THURSDAY = 3, "Jeudi"
        FRIDAY = 4, "Vendredi"
        SATURDAY = 5, "Samedi"
        SUNDAY = 6, "Dimanche"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="recurring_reservation_plans",
    )
    parking = models.ForeignKey(
        Parking,
        on_delete=models.CASCADE,
        related_name="recurring_reservation_plans",
    )
    vehicle = models.ForeignKey(
        SavedVehicle,
        on_delete=models.SET_NULL,
        related_name="recurring_reservation_plans",
        null=True,
        blank=True,
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField()
    next_reminder_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["weekday", "start_time"]

    def __str__(self):
        return f"{self.get_weekday_display()} — {self.parking}"


class PaymentTransaction(models.Model):
    class Kind(models.TextChoices):
        RESERVATION = "reservation", "Paiement de réservation"
        REFUND = "refund", "Remboursement"
        CONTRAVENTION = "contravention", "Paiement de contravention"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="parking_transactions",
        null=True,
        blank=True,
    )
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.SET_NULL,
        related_name="transactions",
        null=True,
        blank=True,
    )
    contravention = models.ForeignKey(
        Contravention,
        on_delete=models.SET_NULL,
        related_name="transactions",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.amount:.2f} €"


@receiver(post_save, sender=PaymentTransaction)
def notify_monthly_budget_reached(sender, instance, created, **kwargs):
    if not created or instance.user_id is None:
        return
    send_monthly_budget_notification(instance.user_id, instance.created_at)


def send_monthly_budget_notification(user_id, at=None):
    profile = UserProfile.objects.filter(user_id=user_id).first()
    if (
        profile is None
        or profile.monthly_budget_limit is None
        or not profile.notifications_enabled
    ):
        return
    now = timezone.localtime(at or timezone.now())
    month_transactions = PaymentTransaction.objects.filter(
        user_id=user_id,
        created_at__year=now.year,
        created_at__month=now.month,
    )
    charges = month_transactions.filter(
        kind__in=[
            PaymentTransaction.Kind.RESERVATION,
            PaymentTransaction.Kind.CONTRAVENTION,
        ]
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    refunds = month_transactions.filter(
        kind=PaymentTransaction.Kind.REFUND
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    net_spend = charges - refunds
    month_key = now.strftime("%Y-%m")
    if net_spend < profile.monthly_budget_limit or UserNotification.objects.filter(
        user_id=user_id,
        title="Seuil de budget mensuel atteint",
        message__contains=month_key,
    ).exists():
        return
    UserNotification.objects.create(
        user_id=user_id,
        title="Seuil de budget mensuel atteint",
        message=(
            f"Vos dépenses simulées nettes atteignent {net_spend:.2f} € "
            f"pour {month_key}, soit votre seuil de {profile.monthly_budget_limit:.2f} €."
        ),
        url="/mes-depenses/",
    )
