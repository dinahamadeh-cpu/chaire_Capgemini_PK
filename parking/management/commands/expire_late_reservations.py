from django.core.management.base import BaseCommand

from parking.services import expire_late_reservations


class Command(BaseCommand):
    help = "Libère les réservations dont le délai d’arrivée tardive est dépassé."

    def handle(self, *args, **options):
        expired_count = expire_late_reservations()
        self.stdout.write(
            self.style.SUCCESS(
                f"{expired_count} réservation(s) libérée(s) après retard."
            )
        )
