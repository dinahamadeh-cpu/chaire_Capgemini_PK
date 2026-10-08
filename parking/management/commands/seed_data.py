from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from parking.models import Parking, Reservation, Spot

AGENTS = [
    {"username": "agent1", "password": "agent1234"},
    {"username": "agent2", "password": "agent1234"},
]

PARKINGS = [
    {"name": "Parking Centre-Ville", "address": "1 place de la Mairie", "spots": 10},
    {"name": "Parking Gare", "address": "2 avenue de la Gare", "spots": 10},
]

STATIONED_PLATES = [
    "AA-123-AA",
    "BB-234-BB",
    "CC-345-CC",
    "DD-456-DD",
    "EE-567-EE",
    "FF-678-FF",
    "GG-789-GG",
    "HH-890-HH",
]

LEFT_PLATES = ["YY-111-YY", "ZZ-222-ZZ"]


class Command(BaseCommand):
    help = "Crée des données factices : parkings, places, comptes agents et réservations (plaques stationnées)."

    def handle(self, *args, **options):
        User = get_user_model()
        agents_group, _ = Group.objects.get_or_create(name="Agents")
        agent_users = []

        for agent in AGENTS:
            user, created = User.objects.get_or_create(
                username=agent["username"], defaults={"is_staff": True}
            )
            if created:
                user.set_password(agent["password"])
                user.is_staff = True
                user.save()
                self.stdout.write(f"Agent créé : {agent['username']} / {agent['password']}")
            else:
                self.stdout.write(f"Agent déjà existant : {agent['username']}")
            user.groups.add(agents_group)
            agent_users.append(user)

        Reservation.objects.all().delete()
        Spot.objects.all().delete()
        Parking.objects.all().delete()

        spots = []
        for data in PARKINGS:
            parking = Parking.objects.create(name=data["name"], address=data["address"])
            for number in range(1, data["spots"] + 1):
                spots.append(Spot.objects.create(parking=parking, number=number))
        self.stdout.write(f"{len(PARKINGS)} parkings et {len(spots)} places créés.")

        stationed_spots = spots[: len(STATIONED_PLATES)]
        seed_user = agent_users[0]
        for plate, spot in zip(STATIONED_PLATES, stationed_spots):
            Reservation.objects.create(
                user=seed_user,
                plate=plate,
                spot=spot,
                status=Reservation.Status.ACTIVE,
            )
        self.stdout.write(f"{len(STATIONED_PLATES)} véhicules stationnés (plaques actives).")

        left_spots = spots[len(STATIONED_PLATES) : len(STATIONED_PLATES) + len(LEFT_PLATES)]
        now = timezone.now()
        for index, (plate, spot) in enumerate(zip(LEFT_PLATES, left_spots)):
            reservation = Reservation.objects.create(
                user=seed_user,
                plate=plate,
                spot=spot,
                status=Reservation.Status.CANCELLED,
            )
            started = now - timedelta(hours=3 - index)
            ended = now - timedelta(hours=1)
            Reservation.objects.filter(pk=reservation.pk).update(created_at=started, ended_at=ended)
        self.stdout.write(f"{len(LEFT_PLATES)} véhicules déjà partis (historique).")

        self.stdout.write(self.style.SUCCESS("Données factices créées avec succès."))
