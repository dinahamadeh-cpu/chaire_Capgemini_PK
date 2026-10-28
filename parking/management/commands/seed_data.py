import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from parking.models import Contravention, Parking, Reservation, Spot

AGENTS = [
    {"username": "agent1", "password": "agent1234"},
    {"username": "agent2", "password": "agent1234"},
]

DEMO_USER = {"username": "demo", "password": "demo1234"}

PARKINGS = [
    {
        "name": "Parking Centre-Ville",
        "address": "1 place de la Mairie",
        "spots": 10,
        "latitude": 48.8566,
        "longitude": 2.3522,
        "hourly_rate": Decimal("2.50"),
        "max_duration_minutes": 120,
        "opening_time": time(7, 0),
        "closing_time": time(21, 0),
    },
    {
        "name": "Parking Gare",
        "address": "2 avenue de la Gare",
        "spots": 10,
        "latitude": 48.8443,
        "longitude": 2.3730,
        "hourly_rate": Decimal("1.80"),
        "max_duration_minutes": None,
        "opening_time": None,
        "closing_time": None,
    },
    {
        "name": "Parking Place Saint-Michel",
        "address": "25 Rue Francisque Gay, 75006 Paris",
        "spots": 10,
        "latitude": 48.8528402,
        "longitude": 2.3433514,
        "hourly_rate": Decimal("5.50"),
        "max_duration_minutes": None,
        "opening_time": None,
        "closing_time": None,
    },
    {
        "name": "Parking Parc de la Villette Nord - Cité des Sciences",
        "address": "61 Bd Macdonald, 75019 Paris",
        "spots": 10,
        "latitude": 48.8980453,
        "longitude": 2.3875319,
        "hourly_rate": Decimal("4.80"),
        "max_duration_minutes": None,
        "opening_time": None,
        "closing_time": None,
    },
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
DEMO_RESERVATION_PLATES = {STATIONED_PLATES[0], LEFT_PLATES[0]}

HISTORY_DAYS = 30
# Poids d'arrivée par heure (0 h à 23 h) : pics le matin, le midi et en fin de journée.
HOURLY_WEIGHTS = [1, 1, 1, 1, 1, 2, 4, 9, 12, 8, 5, 5, 7, 7, 5, 5, 6, 9, 10, 7, 4, 3, 2, 1]
# Nombre moyen d'arrivées par parking selon le jour de la semaine (lundi à dimanche).
DAILY_ARRIVALS = [12, 13, 13, 14, 17, 20, 8]


class Command(BaseCommand):
    help = "Crée des données factices : parkings, places, comptes agents et réservations (plaques stationnées)."

    def handle(self, *args, **options):
        User = get_user_model()
        agents_group, _ = Group.objects.get_or_create(name="Agents")

        for agent in AGENTS:
            user, created = User.objects.get_or_create(
                username=agent["username"], defaults={"is_staff": True}
            )
            if created:
                user.set_password(agent["password"])
                user.is_staff = True
                user.save()
                self.stdout.write(f"Agent créé : {agent['username']}")
            else:
                self.stdout.write(f"Agent déjà existant : {agent['username']}")
            user.groups.add(agents_group)

        demo_user, created = User.objects.get_or_create(
            username=DEMO_USER["username"],
            defaults={"is_staff": False},
        )
        if created:
            demo_user.set_password(DEMO_USER["password"])
            demo_user.save()
            self.stdout.write(f"Utilisateur de démonstration créé : {DEMO_USER['username']}")
        else:
            self.stdout.write(f"Utilisateur déjà existant : {DEMO_USER['username']}")

        Reservation.objects.all().delete()
        Spot.objects.all().delete()
        Parking.objects.all().delete()

        spots = []
        for data in PARKINGS:
            parking = Parking.objects.create(
                name=data["name"],
                address=data["address"],
                latitude=data["latitude"],
                longitude=data["longitude"],
                hourly_rate=data["hourly_rate"],
                max_duration_minutes=data["max_duration_minutes"],
                opening_time=data["opening_time"],
                closing_time=data["closing_time"],
            )
            for number in range(1, data["spots"] + 1):
                spots.append(
                    Spot.objects.create(
                        parking=parking,
                        number=number,
                        is_pmr=number in (9, 10),
                    )
                )
        self.stdout.write(f"{len(PARKINGS)} parkings et {len(spots)} places créés.")

        stationed_spots = spots[: len(STATIONED_PLATES)]
        for plate, spot in zip(STATIONED_PLATES, stationed_spots):
            Reservation.objects.create(
                user=demo_user if plate in DEMO_RESERVATION_PLATES else None,
                plate=plate,
                spot=spot,
                status=Reservation.Status.ACTIVE,
            )
        self.stdout.write(f"{len(STATIONED_PLATES)} véhicules stationnés (plaques actives).")

        left_spots = spots[len(STATIONED_PLATES) : len(STATIONED_PLATES) + len(LEFT_PLATES)]
        now = timezone.now()
        for index, (plate, spot) in enumerate(zip(LEFT_PLATES, left_spots)):
            reservation = Reservation.objects.create(
                user=demo_user if plate in DEMO_RESERVATION_PLATES else None,
                plate=plate,
                spot=spot,
                status=Reservation.Status.COMPLETED,
            )
            started = now - timedelta(hours=3 - index)
            ended = now - timedelta(hours=1)
            Reservation.objects.filter(pk=reservation.pk).update(created_at=started, ended_at=ended)
        self.stdout.write(f"{len(LEFT_PLATES)} véhicules déjà partis (historique).")

        self.create_demo_summary(demo_user, spots[10], now)

        history_count = self.create_history(timezone.localdate())
        self.stdout.write(f"{history_count} réservations passées sur {HISTORY_DAYS} jours (affluence).")

        self.create_contraventions(demo_user)
        self.stdout.write(self.style.SUCCESS("Données factices créées avec succès."))

    def create_demo_summary(self, demo_user, spot, now):
        arrived_at = now - timedelta(days=2)
        ended_at = arrived_at + timedelta(hours=2, minutes=16)
        reservation = Reservation(
            user=demo_user,
            spot=spot,
            plate="II-901-II",
            duration_minutes=210,
            amount_paid=Decimal("6.30"),
            amount_charged=Decimal("6.30"),
            status=Reservation.Status.COMPLETED,
            arrived_at=arrived_at,
            ended_at=ended_at,
        )
        reservation.settle_final_amount()
        reservation.save()
        Reservation.objects.filter(pk=reservation.pk).update(created_at=arrived_at)
        self.stdout.write(
            "Récapitulatif de démonstration créé : 3 h 30 réservées, "
            "2 h 16 de stationnement réel."
        )

    def create_contraventions(self, demo_user):
        agents = {
            agent["username"]: get_user_model().objects.get(username=agent["username"])
            for agent in AGENTS
        }
        centre_ville = Parking.objects.get(name="Parking Centre-Ville")
        gare = Parking.objects.get(name="Parking Gare")
        sample_contraventions = [
            {
                "agent": agents["agent1"],
                "user": demo_user,
                "plate": "YY-111-YY",
                "fine_type": Contravention.FineType.NO_PAYMENT,
                "reason": "Paiement ou titre de stationnement absent",
                "parking": centre_ville,
                "amount": Decimal("50.00"),
                "comment": "Exemple de contravention associée au compte demo.",
                "status": Contravention.Status.ISSUED,
                "opposition_reason": "",
                "opposition_submitted_at": None,
            },
            {
                "agent": agents["agent2"],
                "user": None,
                "plate": "ZZ-222-ZZ",
                "fine_type": Contravention.FineType.OVERSTAY,
                "reason": "Dépassement de la durée réservée",
                "parking": gare,
                "amount": Decimal("35.00"),
                "comment": "Exemple d’avis créé par agent2.",
                "status": Contravention.Status.ISSUED,
                "opposition_reason": "",
                "opposition_submitted_at": None,
            },
        ]
        for data in sample_contraventions:
            agent = data["agent"]
            plate = data["plate"]
            Contravention.objects.update_or_create(
                agent=agent,
                plate=plate,
                reason=data["reason"],
                defaults=data,
            )
        self.stdout.write(f"{len(sample_contraventions)} contraventions de démonstration créées ou actualisées.")

    def create_history(self, today):
        """Crée des stationnements terminés sur les jours précédents, sans chevauchement sur une même place."""
        rng = random.Random(42)
        reservations = []
        starts = []
        for parking in Parking.objects.prefetch_related("spots"):
            spots = list(parking.spots.all())
            max_hours = (parking.max_duration_minutes or 240) // 60
            open_hours = [
                hour
                for hour in range(24)
                if parking.opening_time is None
                or parking.opening_time.hour <= hour < parking.closing_time.hour - max_hours
            ]
            for offset in range(HISTORY_DAYS, 0, -1):
                day = today - timedelta(days=offset)
                arrivals_count = max(0, DAILY_ARRIVALS[day.weekday()] + rng.randint(-3, 3))
                hours = rng.choices(open_hours, weights=[HOURLY_WEIGHTS[h] for h in open_hours], k=arrivals_count)
                free_at = {spot.pk: None for spot in spots}
                for hour in sorted(hours):
                    start = timezone.make_aware(datetime.combine(day, time(hour, rng.randrange(0, 60, 5))))
                    spot = next(
                        (s for s in spots if free_at[s.pk] is None or free_at[s.pk] <= start),
                        None,
                    )
                    if spot is None:
                        continue
                    end = start + timedelta(minutes=rng.randrange(30, max_hours * 60 + 1, 15))
                    free_at[spot.pk] = end
                    reservations.append(
                        Reservation(
                            spot=spot,
                            plate=random_plate(rng),
                            duration_minutes=int((end - start).total_seconds() // 60),
                            status=Reservation.Status.COMPLETED,
                            arrived_at=start,
                            ended_at=end,
                        )
                    )
                    starts.append(start)

        Reservation.objects.bulk_create(reservations)
        # created_at est rempli automatiquement à la création : on le remet à l'heure d'arrivée simulée.
        for reservation, start in zip(reservations, starts):
            reservation.created_at = start
        Reservation.objects.bulk_update(reservations, ["created_at"])
        return len(reservations)


def random_plate(rng):
    letters = "ABCDEFGHJKLMNPQRSTVWXYZ"
    return (
        f"{rng.choice(letters)}{rng.choice(letters)}-{rng.randint(100, 999)}-"
        f"{rng.choice(letters)}{rng.choice(letters)}"
    )
