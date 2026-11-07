from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Reservation, UserNotification


def expire_late_reservations(now=None):
    now = now or timezone.now()
    candidates = Reservation.objects.filter(
        status=Reservation.Status.ACTIVE,
        arrived_at__isnull=True,
    ).select_related("spot__parking")
    expired_ids = []
    for candidate in candidates.iterator():
        deadline = candidate.late_arrival_deadline
        if deadline is None and candidate.starts_at is not None:
            deadline = candidate.starts_at + timedelta(
                minutes=candidate.spot.parking.late_arrival_grace_minutes
            )
        if deadline is not None and deadline <= now:
            expired_ids.append(candidate.pk)

    expired_count = 0

    for reservation_id in expired_ids:
        with transaction.atomic():
            reservation = (
                Reservation.objects.select_for_update()
                .select_related("spot__parking")
                .filter(
                    pk=reservation_id,
                    status=Reservation.Status.ACTIVE,
                    arrived_at__isnull=True,
                )
                .first()
            )
            if reservation is None:
                continue
            deadline = reservation.late_arrival_deadline
            if deadline is None and reservation.starts_at is not None:
                deadline = reservation.starts_at + timedelta(
                    minutes=reservation.spot.parking.late_arrival_grace_minutes
                )
            if deadline is None or deadline > now:
                continue

            reservation.status = Reservation.Status.EXPIRED
            reservation.ended_at = now
            reservation.amount_refunded = 0
            reservation.amount_paid = (
                reservation.amount_charged or reservation.amount_paid or 0
            )
            reservation.save(
                update_fields=[
                    "status",
                    "ended_at",
                    "amount_paid",
                    "amount_refunded",
                ]
            )
            if reservation.user_id:
                UserNotification.objects.create(
                    user=reservation.user,
                    title="Réservation libérée après le délai d’arrivée",
                    message=(
                    f"Le délai d’arrivée pour le {reservation.spot.parking.name} "
                    "est dépassé. La place a été libérée et le montant simulé "
                    "de la réservation est conservé."
                    ),
                    url="/mes-reservations/",
                )
            expired_count += 1

    return expired_count
