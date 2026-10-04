from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

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

        reservation = Reservation.objects.create(user=user, spot=spot)

        self.assertEqual(reservation.user, user)
        self.assertEqual(reservation.spot, spot)
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)

    def test_spot_number_is_unique_within_parking(self):
        parking = Parking.objects.create(name="Parking Central", address="1 rue du Centre")
        Spot.objects.create(parking=parking, number=1)

        with self.assertRaises(IntegrityError):
            Spot.objects.create(parking=parking, number=1)

class ParkingViewsTests(TestCase):
    def setUp(self):
        self.parking = Parking.objects.create(
            name="Parking Central",
            address="1 rue du Centre",
        )

        Spot.objects.create(
            parking=self.parking,
            number=1,
            is_available=True,
        )

        Spot.objects.create(
            parking=self.parking,
            number=2,
            is_available=False,
        )

    def test_parking_list_page(self):
        response = self.client.get(reverse("parking:parking_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Central")
        self.assertContains(response, "1 rue du Centre")

    def test_parking_detail_page(self):
        response = self.client.get(
            reverse(
                "parking:parking_detail",
                args=[self.parking.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Central")
        self.assertContains(response, "Place numéro 1")
        self.assertNotContains(response, "Place numéro 2")