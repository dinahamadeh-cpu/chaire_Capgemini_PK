import random
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from parking.models import (
    Contravention,
    DemoPaymentMethod,
    Parking,
    ParkingReport,
    ParkingReportComment,
    PaymentTransaction,
    Reservation,
    Spot,
    UserNotification,
)

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
    "JJ-012-JJ",
    "KK-123-KK",
    "LL-234-LL",
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
        DemoPaymentMethod.objects.get_or_create(
            user=demo_user,
            name="Exemple",
        )

        PaymentTransaction.objects.filter(reservation__isnull=False).delete()
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

        stationed_spot_indexes = list(range(7)) + [10, 11, 20, 30]
        stationed_spots = [spots[index] for index in stationed_spot_indexes]
        arrival_time = timezone.now()
        for plate, spot in zip(STATIONED_PLATES, stationed_spots):
            is_demo_reservation = plate in DEMO_RESERVATION_PLATES
            amount_paid = (
                spot.parking.hourly_rate
                if is_demo_reservation and spot.parking.hourly_rate is not None
                else Decimal("0.00")
            )
            reservation = Reservation.objects.create(
                user=demo_user if plate in DEMO_RESERVATION_PLATES else None,
                plate=plate,
                spot=spot,
                status=Reservation.Status.ACTIVE,
                arrived_at=arrival_time,
                duration_minutes=60,
                amount_paid=amount_paid,
                amount_charged=amount_paid,
            )
            if is_demo_reservation and amount_paid > 0:
                PaymentTransaction.objects.create(
                    user=demo_user,
                    reservation=reservation,
                    kind=PaymentTransaction.Kind.RESERVATION,
                    amount=amount_paid,
                    created_at=arrival_time,
                )
        self.stdout.write(f"{len(STATIONED_PLATES)} véhicules stationnés (plaques actives).")
        active_demo_reservation = Reservation.objects.get(
            user=demo_user,
            plate=STATIONED_PLATES[0],
            status=Reservation.Status.ACTIVE,
        )
        UserNotification.objects.update_or_create(
            user=demo_user,
            title="Votre stationnement est en cours",
            defaults={
                "message": (
                    f"Votre véhicule est stationné au parking "
                    f"{active_demo_reservation.spot.parking.name}, place "
                    f"{active_demo_reservation.spot.number}. Consultez le récapitulatif "
                    "pour suivre votre réservation."
                ),
                "url": reverse(
                    "parking:reservation_summary",
                    args=[active_demo_reservation.pk],
                ),
            },
        )

        left_spots = spots[12 : 12 + len(LEFT_PLATES)]
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

        self.create_demo_summary(demo_user, spots[15], now)
        self.create_demo_reports(demo_user, spots)

        history_count = self.create_history(timezone.localdate())
        self.stdout.write(f"{history_count} réservations passées sur {HISTORY_DAYS} jours (affluence).")

        self.create_contraventions(demo_user)
        self.stdout.write(self.style.SUCCESS("Données factices créées avec succès."))

    def create_demo_reports(self, demo_user, spots):
        agent = get_user_model().objects.get(username=AGENTS[0]["username"])
        examples = [
            {
                "category": ParkingReport.Category.DANGER,
                "title": "Danger immédiat : accès à une place bloqué",
                "description": "Une voiture occupe une place réservée et empêche son utilisation.",
                "parking": spots[0].parking,
                "spot": spots[0],
                "status": ParkingReport.Status.IN_PROGRESS,
                "priority": ParkingReport.Priority.URGENT,
                "assigned_agent": agent,
                "comment": (
                    "Signalement traité en priorité : un agent vérifie le véhicule "
                    "et sécurise l’accès à la place."
                ),
            },
            {
                "category": ParkingReport.Category.EQUIPMENT,
                "title": "Borne de paiement hors service",
                "description": "La borne de paiement du parking ne fonctionne pas.",
                "parking": spots[10].parking,
                "spot": None,
                "status": ParkingReport.Status.RESOLVED,
                "priority": ParkingReport.Priority.NORMAL,
                "comment": "La borne a été redémarrée et son fonctionnement vérifié.",
            },
            {
                "category": ParkingReport.Category.INFORMATION,
                "title": "Adresse du parking incorrecte",
                "description": "L’adresse affichée pour le parking est incorrecte.",
                "parking": spots[20].parking,
                "spot": None,
                "status": ParkingReport.Status.RESOLVED,
                "priority": ParkingReport.Priority.NORMAL,
                "comment": "L’adresse du parking a été corrigée dans l’application.",
            },
            {
                "category": ParkingReport.Category.INFORMATION,
                "title": "Panneau d’entrée supposé manquant",
                "description": "Le panneau d’entrée du parking semble manquer.",
                "parking": spots[30].parking,
                "spot": None,
                "status": ParkingReport.Status.REFUSED,
                "priority": ParkingReport.Priority.NORMAL,
                "comment": (
                    "Après vérification, la signalisation est présente à l’entrée "
                    "officielle du parking. Le signalement est donc refusé."
                ),
            },
            {
                "category": ParkingReport.Category.OCCUPIED,
                "title": "Véhicule gênant l’accès à une place",
                "description": (
                    "Un véhicule est stationné devant une place et gêne "
                    "l’accès des autres usagers."
                ),
                "parking": spots[5].parking,
                "spot": spots[5],
                "status": ParkingReport.Status.NEW,
                "priority": ParkingReport.Priority.HIGH,
            },
        ]
        for example in examples:
            category = example["category"]
            description = example["description"]
            report, _ = ParkingReport.objects.update_or_create(
                user=demo_user,
                description=description,
                defaults={
                    "category": category,
                    "title": example["title"],
                    "parking": example["parking"],
                    "spot": example["spot"],
                    "status": example["status"],
                    "priority": example["priority"],
                    "assigned_agent": example.get("assigned_agent"),
                },
            )
            if example.get("comment"):
                seeded_comments = report.comments.filter(author=agent).order_by(
                    "created_at", "pk"
                )
                seeded_comment = seeded_comments.first()
                if seeded_comment is None:
                    ParkingReportComment.objects.create(
                        report=report,
                        message=example["comment"],
                        author=agent,
                    )
                else:
                    seeded_comment.message = example["comment"]
                    seeded_comment.save(update_fields=["message"])
                    seeded_comments.exclude(pk=seeded_comment.pk).delete()
        self.stdout.write("5 signalements de démonstration créés ou actualisés.")

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
        saint_michel = Parking.objects.get(name="Parking Place Saint-Michel")
        villette = Parking.objects.get(
            name="Parking Parc de la Villette Nord - Cité des Sciences"
        )
        demo_payment_time = timezone.now()
        sample_contraventions = [
            {
                "agent": agents["agent1"],
                "user": demo_user,
                "plate": "YY-111-YY",
                "fine_type": Contravention.FineType.NO_PAYMENT,
                "reason": "Paiement ou titre de stationnement absent",
                "parking": centre_ville,
                "spot": centre_ville.spots.get(number=8),
                "latitude": centre_ville.latitude,
                "longitude": centre_ville.longitude,
                "amount": Decimal("50.00"),
                "comment": "Exemple de contravention associée au compte demo.",
                "status": Contravention.Status.ISSUED,
                "opposition_reason": "",
                "opposition_submitted_at": None,
                "paid_at": None,
            },
            {
                "agent": agents["agent2"],
                "user": None,
                "plate": "ZZ-222-ZZ",
                "fine_type": Contravention.FineType.OVERSTAY,
                "reason": "Dépassement de la durée réservée",
                "parking": gare,
                "spot": gare.spots.get(number=5),
                "latitude": gare.latitude,
                "longitude": gare.longitude,
                "amount": Decimal("35.00"),
                "comment": "Exemple d’avis créé par agent2.",
                "status": Contravention.Status.ISSUED,
                "opposition_reason": "",
                "opposition_submitted_at": None,
                "paid_at": None,
            },
            {
                "agent": agents["agent1"],
                "user": demo_user,
                "plate": "MM-345-MM",
                "fine_type": Contravention.FineType.WRONG_SPOT,
                "reason": "Stationnement sur une place non autorisée",
                "parking": saint_michel,
                "spot": saint_michel.spots.get(number=1),
                "latitude": saint_michel.latitude,
                "longitude": saint_michel.longitude,
                "amount": Decimal("50.00"),
                "comment": "Avis de démonstration réglé.",
                "status": Contravention.Status.ISSUED,
                "opposition_reason": "",
                "opposition_submitted_at": None,
                "paid_at": demo_payment_time,
            },
            {
                "agent": agents["agent2"],
                "user": demo_user,
                "plate": "NN-456-NN",
                "fine_type": Contravention.FineType.OBSTRUCTING,
                "reason": "Stationnement gênant ou bloquant",
                "parking": villette,
                "spot": villette.spots.get(number=1),
                "latitude": villette.latitude,
                "longitude": villette.longitude,
                "amount": Decimal("75.00"),
                "comment": "Avis de démonstration réglé.",
                "status": Contravention.Status.ISSUED,
                "opposition_reason": "",
                "opposition_submitted_at": None,
                "paid_at": demo_payment_time,
            },
            {
                "agent": agents["agent1"],
                "user": demo_user,
                "plate": "PP-567-PP",
                "fine_type": Contravention.FineType.NO_RESERVATION,
                "reason": "Stationnement sans réservation",
                "parking": centre_ville,
                "spot": centre_ville.spots.get(number=9),
                "latitude": centre_ville.latitude,
                "longitude": centre_ville.longitude,
                "amount": Decimal("50.00"),
                "comment": "Avis de démonstration faisant l’objet d’une contestation.",
                "status": Contravention.Status.CONTESTING,
                "opposition_reason": (
                    "Je conteste cet avis : j’avais bien réservé cette place. "
                    "La confirmation de réservation est disponible dans mon compte."
                ),
                "opposition_submitted_at": demo_payment_time,
                "paid_at": None,
            },
            {
                "agent": agents["agent2"],
                "user": demo_user,
                "plate": "QQ-678-QQ",
                "fine_type": Contravention.FineType.OVERSTAY,
                "reason": "Dépassement de la durée réservée",
                "parking": gare,
                "spot": gare.spots.get(number=7),
                "latitude": gare.latitude,
                "longitude": gare.longitude,
                "amount": Decimal("35.00"),
                "comment": "Avis de démonstration faisant l’objet d’une contestation.",
                "status": Contravention.Status.CONTESTING,
                "opposition_reason": (
                    "Je conteste la durée indiquée : j’ai quitté la place avant "
                    "la fin de ma réservation. Je demande une vérification de l’heure de départ."
                ),
                "opposition_submitted_at": demo_payment_time,
                "paid_at": None,
            },
            {
                "agent": agents["agent1"],
                "user": demo_user,
                "plate": "RR-789-RR",
                "fine_type": Contravention.FineType.NO_RESERVATION,
                "reason": "Stationnement sans réservation",
                "parking": centre_ville,
                "spot": centre_ville.spots.get(number=4),
                "latitude": centre_ville.latitude,
                "longitude": centre_ville.longitude,
                "amount": Decimal("50.00"),
                "comment": (
                    "Après vérification de la confirmation de réservation, "
                    "la contestation est acceptée et l’avis est annulé."
                ),
                "status": Contravention.Status.APPEAL_WON,
                "opposition_reason": (
                    "J’avais bien réservé cette place pour la période indiquée. "
                    "Je joins la confirmation reçue lors de la réservation."
                ),
                "opposition_submitted_at": demo_payment_time - timedelta(hours=1),
                "paid_at": None,
            },
        ]
        for data in sample_contraventions:
            agent = data["agent"]
            plate = data["plate"]
            contravention, _ = Contravention.objects.update_or_create(
                plate=plate,
                defaults=data,
            )
            if contravention.paid_at:
                if contravention.payment_reference is None:
                    contravention.payment_reference = uuid.uuid4()
                    contravention.save(update_fields=["payment_reference"])
                PaymentTransaction.objects.update_or_create(
                    contravention=contravention,
                    defaults={
                        "user": contravention.user,
                        "kind": PaymentTransaction.Kind.CONTRAVENTION,
                        "amount": contravention.amount,
                        "created_at": contravention.paid_at,
                    },
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
