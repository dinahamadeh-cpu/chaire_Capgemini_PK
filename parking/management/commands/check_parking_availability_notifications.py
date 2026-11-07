from django.core.management.base import BaseCommand
from django.utils import timezone

from parking.models import (
    Parking,
    ParkingWaitlist,
    Spot,
    notify_parking_availability,
)


class Command(BaseCommand):
    help = "Traite les alertes de disponibilité et créneaux de liste d’attente."

    def handle(self, *args, **options):
        now = timezone.now()
        expired_count, _ = ParkingWaitlist.objects.filter(
            ends_at__lt=now,
        ).delete()
        processed = 0
        parking_ids = set(
            ParkingWaitlist.objects.filter(
                starts_at__lte=now,
                ends_at__gte=now,
            ).values_list("parking_id", flat=True)
        )
        parking_ids.update(
            Parking.objects.filter(
                favorited_by__availability_alert_threshold__isnull=False,
                favorited_by__availability_alert_sent_at__isnull=True,
            ).values_list("pk", flat=True)
        )
        for spot_id in Spot.objects.filter(
            parking_id__in=parking_ids,
        ).values_list("pk", flat=True):
            notify_parking_availability(spot_id)
            processed += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"{processed} place(s) vérifiée(s), "
                f"{expired_count} entrée(s) expirée(s) supprimée(s)."
            )
        )
