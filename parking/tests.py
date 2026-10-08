from datetime import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
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

    def test_reservation_without_user_is_allowed_for_agent_records(self):
        spot = Spot.objects.create(
            parking=Parking.objects.create(name="Parking Central", address="1 rue du Centre"),
            number=1,
        )

        reservation = Reservation.objects.create(spot=spot, plate="BB-234-BB")

        self.assertIsNone(reservation.user)

    def test_spot_becomes_unavailable_then_available_again(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        spot = Spot.objects.create(
            parking=Parking.objects.create(name="Parking Central", address="1 rue du Centre"),
            number=1,
        )

        reservation = Reservation.objects.create(user=user, spot=spot, plate="CC-345-CC")
        spot.refresh_from_db()
        self.assertFalse(spot.is_available)

        reservation.status = Reservation.Status.CANCELLED
        reservation.save()
        spot.refresh_from_db()
        self.assertTrue(spot.is_available)

    def test_plate_can_only_have_one_active_reservation(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        parking = Parking.objects.create(name="Parking Central", address="1 rue du Centre")
        spot_1 = Spot.objects.create(parking=parking, number=1)
        spot_2 = Spot.objects.create(parking=parking, number=2)
        Reservation.objects.create(user=user, spot=spot_1, plate="DD-456-DD")

        with self.assertRaises(IntegrityError):
            Reservation.objects.create(user=user, spot=spot_2, plate="DD-456-DD")

    def test_spot_can_only_have_one_active_reservation(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        parking = Parking.objects.create(name="Parking Central", address="1 rue du Centre")
        spot = Spot.objects.create(parking=parking, number=1)
        Reservation.objects.create(user=user, spot=spot, plate="EE-567-EE")

        with self.assertRaises(IntegrityError):
            Reservation.objects.create(user=user, spot=spot, plate="FF-678-FF")

    def test_plate_format_is_validated(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        spot = Spot.objects.create(
            parking=Parking.objects.create(name="Parking Central", address="1 rue du Centre"),
            number=1,
        )
        reservation = Reservation(user=user, spot=spot, plate="not-a-plate")

        with self.assertRaises(ValidationError):
            reservation.full_clean()

    def test_parking_pricing_is_optional(self):
        parking = Parking.objects.create(name="Parking Central", address="1 rue du Centre")

        parking.full_clean()
        self.assertIsNone(parking.hourly_rate)
        self.assertEqual(parking.max_duration_display, "Illimitée")
        self.assertEqual(parking.opening_hours_display, "Ouvert 24h/24")

    def test_max_duration_display(self):
        parking = Parking(name="Parking Central", address="1 rue du Centre")

        parking.max_duration_minutes = 45
        self.assertEqual(parking.max_duration_display, "45 min")
        parking.max_duration_minutes = 120
        self.assertEqual(parking.max_duration_display, "2 h")
        parking.max_duration_minutes = 90
        self.assertEqual(parking.max_duration_display, "1 h 30")

    def test_opening_hours_display(self):
        parking = Parking(
            name="Parking Central",
            address="1 rue du Centre",
            opening_time=time(7, 0),
            closing_time=time(21, 30),
        )

        self.assertEqual(parking.opening_hours_display, "07:00 – 21:30")

    def test_opening_and_closing_times_go_together(self):
        parking = Parking(name="Parking Central", address="1 rue du Centre", opening_time=time(7, 0))

        with self.assertRaises(ValidationError):
            parking.full_clean()


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

    def test_authenticated_user_can_reserve_a_spot(self):
        user = get_user_model().objects.create_user(
            username="alice",
            password="password",
        )
        self.client.login(username="alice", password="password")

        response = self.client.post(
            reverse(
                "parking:reserve_spot",
                args=[self.parking.id, self.parking.spots.get(number=1).id],
            ),
            {"plate": "GG-789-GG"},
        )

        self.assertRedirects(response, reverse("parking:parking_detail", args=[self.parking.id]))
        reservation = Reservation.objects.get(plate="GG-789-GG")
        self.assertEqual(reservation.user, user)

    def test_anonymous_user_is_redirected_before_reserving(self):
        spot = self.parking.spots.get(number=1)

        response = self.client.post(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
            {"plate": "HH-890-HH"},
        )

        self.assertRedirects(
            response,
            f"{reverse('parking:login')}?next={reverse('parking:reserve_spot', args=[self.parking.id, spot.id])}",
        )
        self.assertFalse(Reservation.objects.filter(plate="HH-890-HH").exists())

    def test_user_can_view_only_own_reservations(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        other_user = get_user_model().objects.create_user(username="bob", password="password")
        own_spot = self.parking.spots.get(number=1)
        other_spot = Spot.objects.create(parking=self.parking, number=3)
        Reservation.objects.create(user=user, spot=own_spot, plate="AA-123-AA")
        Reservation.objects.create(user=other_user, spot=other_spot, plate="BB-234-BB")
        self.client.login(username="alice", password="password")

        response = self.client.get(reverse("parking:reservation_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AA-123-AA")
        self.assertNotContains(response, "BB-234-BB")

    def test_anonymous_user_is_redirected_from_reservations(self):
        response = self.client.get(reverse("parking:reservation_list"))

        self.assertRedirects(
            response,
            f"{reverse('parking:login')}?next={reverse('parking:reservation_list')}",
        )

    def test_user_can_cancel_own_active_reservation(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        spot = self.parking.spots.get(number=1)
        reservation = Reservation.objects.create(user=user, spot=spot, plate="CC-345-CC")
        self.client.login(username="alice", password="password")

        response = self.client.post(
            reverse("parking:cancel_reservation", args=[reservation.id])
        )

        self.assertRedirects(response, reverse("parking:reservation_list"))
        reservation.refresh_from_db()
        spot.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CANCELLED)
        self.assertIsNotNone(reservation.ended_at)
        self.assertTrue(spot.is_available)

    def test_user_cannot_cancel_another_users_reservation(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        other_user = get_user_model().objects.create_user(username="bob", password="password")
        spot = self.parking.spots.get(number=1)
        reservation = Reservation.objects.create(
            user=other_user,
            spot=spot,
            plate="DD-456-DD",
        )
        self.client.login(username="alice", password="password")

        response = self.client.post(
            reverse("parking:cancel_reservation", args=[reservation.id])
        )

        self.assertEqual(response.status_code, 404)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)

    def test_agent_requires_agents_group(self):
        user = get_user_model().objects.create_user(username="agent", password="password")
        user.is_staff = True
        user.save()
        self.client.login(username="agent", password="password")

        response = self.client.get(reverse("parking:agent_dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('parking:agent_login')}?next={reverse('parking:agent_dashboard')}",
        )

        user.groups.add(Group.objects.create(name="Agents"))
        response = self.client.get(reverse("parking:agent_dashboard"))
        self.assertEqual(response.status_code, 200)

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

    def test_parking_detail_shows_pricing(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.max_duration_minutes = 120
        self.parking.opening_time = time(7, 0)
        self.parking.closing_time = time(21, 0)
        self.parking.save()

        response = self.client.get(reverse("parking:parking_detail", args=[self.parking.id]))

        self.assertContains(response, "2,50 € / heure")
        self.assertContains(response, "Durée maximale : 2 h")
        self.assertContains(response, "07:00 – 21:00")

    def test_parking_list_shows_pricing(self):
        self.parking.hourly_rate = Decimal("1.80")
        self.parking.save()

        response = self.client.get(reverse("parking:parking_list"))

        self.assertContains(response, "1,80 € / heure")
        self.assertContains(response, "Ouvert 24h/24")

    def test_parking_without_rate_shows_not_provided(self):
        response = self.client.get(reverse("parking:parking_detail", args=[self.parking.id]))

        self.assertContains(response, "non renseigné")

    def test_free_parking_shows_free(self):
        self.parking.hourly_rate = Decimal("0")
        self.parking.save()

        response = self.client.get(reverse("parking:parking_detail", args=[self.parking.id]))

        self.assertContains(response, "Gratuit")
