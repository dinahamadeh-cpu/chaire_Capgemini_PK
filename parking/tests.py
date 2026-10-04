from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from .models import Parking, Reservation, Spot


class ParkingModelsTests(TestCase):
    def test_creates_parking(self):
        parking = Parking.objects.create(name="Parking Central", address="1 rue du Centre")

        self.assertEqual(Parking.objects.count(), 1)
        self.assertEqual(parking.name, "Parking Central")

    def test_creates_spot_for_parking(self):
        parking = Parking.objects.create(name="Parking Central", address="1 rue du Centre")

        spot = Spot.objects.create(parking=parking, number=1)

        self.assertEqual(spot.parking, parking)
        self.assertTrue(spot.is_available)

    def test_creates_reservation_for_user_and_spot(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        spot = Spot.objects.create(
            parking=Parking.objects.create(name="Parking Central", address="1 rue du Centre"),
            number=1,
        )

        reservation = Reservation.objects.create(user=user, spot=spot, plate="AA-123-AA")

        self.assertEqual(reservation.user, user)
        self.assertEqual(reservation.spot, spot)
        self.assertEqual(reservation.plate, "AA-123-AA")
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)

    def test_spot_number_is_unique_within_parking(self):
        parking = Parking.objects.create(name="Parking Central", address="1 rue du Centre")
        Spot.objects.create(parking=parking, number=1)

        with self.assertRaises(IntegrityError):
            Spot.objects.create(parking=parking, number=1)

    def test_reservation_without_user_is_allowed(self):
        spot = Spot.objects.create(
            parking=Parking.objects.create(name="Parking Central", address="1 rue du Centre"),
            number=1,
        )

        reservation = Reservation.objects.create(spot=spot, plate="BB-234-BB")

        self.assertIsNone(reservation.user)

    def test_spot_becomes_unavailable_then_available_again(self):
        spot = Spot.objects.create(
            parking=Parking.objects.create(name="Parking Central", address="1 rue du Centre"),
            number=1,
        )

        reservation = Reservation.objects.create(spot=spot, plate="CC-345-CC")
        spot.refresh_from_db()
        self.assertFalse(spot.is_available)

        reservation.status = Reservation.Status.CANCELLED
        reservation.save()
        spot.refresh_from_db()
        self.assertTrue(spot.is_available)

    def test_plate_can_only_have_one_active_reservation(self):
        parking = Parking.objects.create(name="Parking Central", address="1 rue du Centre")
        spot_1 = Spot.objects.create(parking=parking, number=1)
        spot_2 = Spot.objects.create(parking=parking, number=2)
        Reservation.objects.create(spot=spot_1, plate="DD-456-DD")

        with self.assertRaises(IntegrityError):
            Reservation.objects.create(spot=spot_2, plate="DD-456-DD")

    def test_plate_format_is_validated(self):
        spot = Spot.objects.create(
            parking=Parking.objects.create(name="Parking Central", address="1 rue du Centre"),
            number=1,
        )
        reservation = Reservation(spot=spot, plate="not-a-plate")

        with self.assertRaises(ValidationError):
            reservation.full_clean()
