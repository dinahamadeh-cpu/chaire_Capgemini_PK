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

    def test_home_page_links_to_parking_list(self):
        response = self.client.get(reverse("parking:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("parking:parking_list"))

    def test_login_page_is_available(self):
        response = self.client.get(reverse("parking:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Se connecter")

    def test_signup_page_is_available(self):
        response = self.client.get(reverse("parking:signup"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Créer un compte")

    def test_user_can_sign_up(self):
        response = self.client.post(
            reverse("parking:signup"),
            {
                "username": "alice",
                "password1": "A-valid-password-123!",
                "password2": "A-valid-password-123!",
            },
        )

        self.assertRedirects(response, reverse("parking:parking_list"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertTrue(get_user_model().objects.filter(username="alice").exists())

    def test_user_can_log_in(self):
        get_user_model().objects.create_user(
            username="alice",
            password="password",
        )

        response = self.client.post(
            reverse("parking:login"),
            {"username": "alice", "password": "password"},
        )

        self.assertRedirects(response, reverse("parking:parking_list"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_parking_list_page(self):
        response = self.client.get(reverse("parking:parking_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Central")
        self.assertContains(response, "1 rue du Centre")
        self.assertContains(response, "1")
        self.assertContains(response, "2")

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

    def test_missing_parking_returns_not_found(self):
        response = self.client.get(
            reverse("parking:parking_detail", args=[999])
        )

        self.assertEqual(response.status_code, 404)

    def test_parking_list_contains_map_and_parking_data(self):
        response = self.client.get(reverse("parking:parking_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="map"')
        self.assertContains(response, "Parking Central")
        self.assertContains(response, 'id="parkings-data"')
