from datetime import timedelta

from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from parking.models import RecurringReservationPlan, UserNotification, UserProfile


class Command(BaseCommand):
    help = "Envoie les rappels dus pour les habitudes de réservation hebdomadaires."

    def handle(self, *args, **options):
        now = timezone.now()
        plans = RecurringReservationPlan.objects.filter(
            is_active=True,
            next_reminder_at__lte=now,
        ).select_related("user", "parking", "vehicle")
        sent_count = 0
        for plan in plans:
            profile = UserProfile.objects.filter(user=plan.user).first()
            if profile and profile.notifications_enabled:
                vehicle_label = (
                    f" pour le véhicule {plan.vehicle.plate}"
                    if plan.vehicle_id
                    else ""
                )
                UserNotification.objects.create(
                    user=plan.user,
                    title="Rappel de réservation habituelle",
                    message=(
                        f"Votre créneau habituel à {plan.start_time:%H:%M} au "
                        f"{plan.parking.name} approche{vehicle_label}. "
                        "Vérifiez les disponibilités puis confirmez vous-même la réservation ; "
                        "aucun paiement n’a été lancé."
                    ),
                    url=reverse("parking:parking_detail", args=[plan.parking_id]),
                )
                sent_count += 1
            next_reminder = plan.next_reminder_at
            while next_reminder <= now:
                next_reminder += timedelta(days=7)
            plan.next_reminder_at = next_reminder
            plan.save(update_fields=["next_reminder_at"])
        self.stdout.write(
            self.style.SUCCESS(f"{sent_count} rappel(s) récurrent(s) envoyé(s).")
        )
