from datetime import datetime, timedelta, time
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import DemoPaymentMethod, Parking, Reservation, Spot, Favorite, Contravention


class SeedDataTests(TestCase):
    def test_seed_data_keeps_stationings_out_of_agent_reservations(self):
        output = StringIO()
        call_command("seed_data", stdout=output)
        self.assertNotIn("agent1234", output.getvalue())
        self.assertNotIn("demo1234", output.getvalue())

        User = get_user_model()
        agents = User.objects.filter(groups__name="Agents")
        demo_user = User.objects.get(username="demo")

        self.assertEqual(Parking.objects.count(), 4)
        self.assertEqual(Spot.objects.count(), 40)
        self.assertEqual(Reservation.objects.filter(user__in=agents).count(), 0)
        self.assertEqual(Reservation.objects.filter(user=demo_user).count(), 2)
        self.assertEqual(Reservation.objects.filter(user__isnull=True, arrived_at__isnull=True).count(), 8)
        history = Reservation.objects.filter(arrived_at__isnull=False)
        self.assertGreater(history.count(), 0)
        self.assertFalse(history.filter(status=Reservation.Status.ACTIVE).exists())
        self.assertFalse(history.filter(created_at__date__gte=timezone.localdate()).exists())
        self.assertEqual(
            Parking.objects.filter(latitude__isnull=False, longitude__isnull=False).count(),
            4,
        )
        self.assertSetEqual(
            set(Parking.objects.values_list("name", flat=True)),
            {
                "Parking Centre-Ville",
                "Parking Gare",
                "Parking Place Saint-Michel",
                "Parking Parc de la Villette Nord - Cité des Sciences",
            },
        )
        place_saint_michel = Parking.objects.get(name="Parking Place Saint-Michel")
        self.assertEqual(place_saint_michel.address, "25 Rue Francisque Gay, 75006 Paris")
        self.assertEqual(place_saint_michel.hourly_rate, Decimal("5.50"))
        self.assertIsNone(place_saint_michel.max_duration_minutes)
        self.assertEqual(place_saint_michel.opening_hours_display, "Ouvert 24h/24")
        cite_des_sciences = Parking.objects.get(
            name="Parking Parc de la Villette Nord - Cité des Sciences"
        )
        self.assertEqual(cite_des_sciences.address, "61 Bd Macdonald, 75019 Paris")
        self.assertEqual(cite_des_sciences.hourly_rate, Decimal("4.80"))
        self.assertEqual(cite_des_sciences.opening_hours_display, "Ouvert 24h/24")
        self.assertTrue(demo_user.check_password("demo1234"))


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

    def test_moving_reservation_updates_both_spots_availability(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        parking = Parking.objects.create(name="Parking Central", address="1 rue du Centre")
        first_spot = Spot.objects.create(parking=parking, number=1)
        second_spot = Spot.objects.create(parking=parking, number=2)
        reservation = Reservation.objects.create(user=user, spot=first_spot, plate="CC-345-CC")

        first_spot.refresh_from_db()
        self.assertFalse(first_spot.is_available)

        reservation.spot = second_spot
        reservation.save()

        first_spot.refresh_from_db()
        second_spot.refresh_from_db()
        self.assertTrue(first_spot.is_available)
        self.assertFalse(second_spot.is_available)

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

    def authenticate_as_user(self):
        user = get_user_model().objects.create_user(
            username="parking-viewer",
            password="test-password-123",
        )
        self.client.force_login(user)

    def test_home_page_links_to_parking_list(self):
        response = self.client.get(reverse("parking:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("parking:parking_list"))
        self.assertContains(response, reverse("parking:agent_login"))

    def test_home_page_separates_usager_and_agent_actions(self):
        response = self.client.get(reverse("parking:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Espace usager")
        self.assertContains(response, "Espace professionnel")
        self.assertContains(response, reverse("parking:signup"))
        self.assertContains(response, reverse("parking:login"))
        self.assertContains(response, reverse("parking:agent_login"))
        self.assertNotContains(response, reverse("admin:index"))
        self.assertNotContains(response, reverse("parking:reservation_list"))

    def test_staff_user_sees_administration_link(self):
        user = get_user_model().objects.create_user(
            username="site-admin",
            password="test-password-123",
            is_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("parking:home"))

        self.assertContains(response, reverse("admin:index"))

    def test_authenticated_navigation_shows_user_links_and_name(self):
        user = get_user_model().objects.create_user(
            username="alice",
            password="test-password-123",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("parking:reservation_list"))

        self.assertContains(response, "alice")
        self.assertContains(response, reverse("parking:home"))
        self.assertContains(response, reverse("parking:parking_list"))
        self.assertContains(response, reverse("parking:favorite_list"))
        self.assertContains(response, reverse("parking:payment_methods"))
        self.assertContains(response, reverse("parking:logout"))
        self.assertNotContains(response, reverse("parking:agent_dashboard"))
        self.assertNotContains(response, reverse("admin:index"))

    def test_agent_navigation_shows_agent_space(self):
        user = get_user_model().objects.create_user(
            username="parking-agent",
            password="test-password-123",
        )
        user.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(user)

        response = self.client.get(reverse("parking:agent_dashboard"))

        self.assertContains(response, reverse("parking:agent_dashboard"))
        self.assertContains(response, reverse("parking:agent_plate_check"))
        self.assertContains(response, "Espace agent")
        self.assertContains(response, reverse("parking:parking_list"))
        self.assertContains(response, reverse("parking:reservation_list"))
        self.assertContains(response, reverse("parking:payment_methods"))
        self.assertNotContains(response, reverse("admin:index"))

    def test_agent_keeps_access_to_agent_space_after_saving_payment_method(self):
        agent = get_user_model().objects.create_user(
            username="agent-with-payment",
            password="test-password-123",
        )
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

        self.client.post(
            reverse("parking:payment_methods"),
            {
                "card_number": "1234567890123456",
                "expiration_date": "12/30",
                "security_code": "123",
            },
        )

        payment_page = self.client.get(reverse("parking:payment_methods"))
        agent_page = self.client.get(reverse("parking:agent_dashboard"))

        self.assertContains(payment_page, reverse("parking:agent_dashboard"))
        self.assertEqual(agent_page.status_code, 200)

    def test_professional_login_hides_admin_from_non_staff(self):
        response = self.client.get(reverse("parking:professional_login"))

        self.assertNotContains(response, reverse("admin:index"))

    def test_reservation_and_payment_forms_render_field_labels(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()

        checkout = self.client.get(
            reverse(
                "parking:reserve_spot",
                args=[self.parking.id, self.parking.spots.get(number=1).id],
            )
        )
        payment = self.client.get(reverse("parking:payment_methods"))

        self.assertContains(checkout, 'for="id_duration_hours"')
        self.assertContains(checkout, "Nombre d&#x27;heures")
        self.assertContains(checkout, 'for="id_plate"')
        self.assertContains(checkout, "Plaque d&#x27;immatriculation")
        self.assertContains(payment, 'for="id_card_number"')
        self.assertContains(payment, "Numéro de carte")
        self.assertContains(payment, 'for="id_expiration_date"')
        self.assertContains(payment, 'for="id_security_code"')

    def test_anonymous_user_is_redirected_to_login_from_payment_methods(self):
        response = self.client.get(reverse("parking:payment_methods"))

        self.assertRedirects(
            response,
            f"{reverse('parking:login')}?next={reverse('parking:payment_methods')}",
        )

    def test_empty_demo_payment_state_explains_simulation_and_data_handling(self):
        self.authenticate_as_user()

        response = self.client.get(reverse("parking:payment_methods"))

        self.assertContains(response, "Paiement simulé")
        self.assertContains(response, "Aucun débit réel ne sera effectué.")
        self.assertContains(response, "Aucune donnée bancaire conservée")
        self.assertContains(response, "Ajouter un moyen simulé")
        self.assertContains(response, 'aria-labelledby="payment-form-title"')

    def test_saved_demo_payment_method_shows_status_without_card_data(self):
        self.authenticate_as_user()
        DemoPaymentMethod.objects.create(user=get_user_model().objects.get(username="parking-viewer"))

        response = self.client.get(reverse("parking:payment_methods"))

        self.assertContains(response, "Un moyen de paiement simulé est enregistré.")
        self.assertContains(response, "rien ne sera réellement débité")
        self.assertContains(response, "Remplacer le moyen simulé")
        self.assertNotContains(response, "1234567890123456")
        self.assertNotContains(response, 'name="card_number" value=')

    def test_authenticated_home_page_links_to_reservations(self):
        user = get_user_model().objects.create_user(
            username="alice",
            password="test-password-123",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("parking:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mes réservations")
        self.assertContains(response, reverse("parking:reservation_list"))
        self.assertNotContains(response, "Créer un compte")

    def test_anonymous_user_is_redirected_to_login_from_parking_list(self):
        response = self.client.get(reverse("parking:parking_list"))

        self.assertRedirects(
            response,
            f"{reverse('parking:login')}?next={reverse('parking:parking_list')}",
        )

    def test_anonymous_user_is_redirected_to_login_from_parking_detail(self):
        response = self.client.get(
            reverse("parking:parking_detail", args=[self.parking.id])
        )

        self.assertRedirects(
            response,
            f"{reverse('parking:login')}?next={reverse('parking:parking_detail', args=[self.parking.id])}",
        )

    def test_authenticated_user_can_view_parking_list_and_detail(self):
        user = get_user_model().objects.create_user(
            username="parking-user",
            password="test-password-123",
        )
        self.client.force_login(user)

        list_response = self.client.get(reverse("parking:parking_list"))
        detail_response = self.client.get(
            reverse("parking:parking_detail", args=[self.parking.id])
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)

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
            follow=True,
        )

        self.assertRedirects(response, reverse("parking:parking_list"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertTrue(get_user_model().objects.filter(username="alice").exists())
        self.assertContains(response, "message-success")
        self.assertContains(response, "Votre compte a été créé. Bienvenue !")

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

    def test_login_rejects_external_next_redirect(self):
        get_user_model().objects.create_user(username="alice", password="password")

        response = self.client.post(
            f"{reverse('parking:login')}?next=https://example.com/",
            {"username": "alice", "password": "password"},
        )

        self.assertRedirects(response, reverse("parking:parking_list"))

    def test_inactive_user_cannot_log_in(self):
        user = get_user_model().objects.create_user(username="alice", password="password", is_active=False)

        response = self.client.post(
            reverse("parking:login"),
            {"username": "alice", "password": "password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertTrue(user.check_password("password"))

    def test_authenticated_user_can_reserve_a_spot(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
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
            {
                "plate": "GG-789-GG",
                "duration_hours": "3",
                "card_number": "1234567890123456",
                "expiration_date": "12/30",
                "security_code": "123",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("parking:parking_detail", args=[self.parking.id]))
        self.assertContains(response, "message-success")
        self.assertContains(response, "Paiement simulé de 7.50 € confirmé.")
        reservation = Reservation.objects.get(plate="GG-789-GG")
        self.assertEqual(reservation.user, user)
        self.assertEqual(reservation.duration_hours, 3)
        self.assertEqual(reservation.amount_paid, Decimal("7.50"))

    def test_reservation_conflict_shows_a_user_facing_error(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        spot = self.parking.spots.get(number=2)

        response = self.client.post(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
            {
                "plate": "AA-123-AA",
                "duration_hours": "1",
                "card_number": "1234567890123456",
                "expiration_date": "12/30",
                "security_code": "123",
            },
            follow=True,
        )

        self.assertContains(response, "message-error")
        self.assertContains(response, "Cette place n&#x27;est plus disponible.")

    def test_checkout_calculates_total_from_integer_cents(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()

        response = self.client.get(
            reverse(
                "parking:reserve_spot",
                args=[self.parking.id, self.parking.spots.get(number=1).id],
            )
        )

        self.assertContains(response, 'data-hourly-rate-cents="250"')
        self.assertContains(response, "Intl.NumberFormat")
        self.assertNotContains(response, "NaN")

    def test_user_can_save_a_demo_payment_method_without_card_data(self):
        self.authenticate_as_user()

        response = self.client.post(
            reverse("parking:payment_methods"),
            {
                "card_number": "1234567890123456",
                "expiration_date": "12/30",
                "security_code": "123",
            },
        )

        self.assertRedirects(response, reverse("parking:payment_methods"))
        saved_method = DemoPaymentMethod.objects.get()
        self.assertEqual(saved_method.user.username, "parking-viewer")
        self.assertNotIn("1234567890123456", str(saved_method))
        self.assertNotIn("123", str(saved_method))

    def test_reservation_can_use_saved_demo_payment_method(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        user = get_user_model().objects.create_user(username="alice", password="password")
        self.client.force_login(user)
        DemoPaymentMethod.objects.create(user=user)

        checkout_response = self.client.get(
            reverse(
                "parking:reserve_spot",
                args=[self.parking.id, self.parking.spots.get(number=1).id],
            )
        )
        self.assertContains(
            checkout_response,
            "Utiliser le moyen de paiement déjà enregistré",
        )
        self.assertContains(checkout_response, 'class="payment-method-choice"')
        self.assertContains(checkout_response, "Nouveau moyen de paiement")
        self.assertNotContains(checkout_response, "Ajouter ou gérer un moyen de paiement")

        response = self.client.post(
            reverse(
                "parking:reserve_spot",
                args=[self.parking.id, self.parking.spots.get(number=1).id],
            ),
            {
                "payment_method": "saved",
                "duration_hours": "2",
                "plate": "KK-123-KK",
            },
        )

        self.assertRedirects(response, reverse("parking:parking_detail", args=[self.parking.id]))
        reservation = Reservation.objects.get(plate="KK-123-KK")
        self.assertEqual(reservation.amount_paid, Decimal("5.00"))

    def test_checkout_rejects_saved_payment_method_without_registered_method(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()

        response = self.client.post(
            reverse(
                "parking:reserve_spot",
                args=[self.parking.id, self.parking.spots.get(number=1).id],
            ),
            {
                "payment_method": "saved",
                "duration_hours": "1",
                "plate": "LL-234-LL",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucun moyen de paiement simulé")
        self.assertFalse(Reservation.objects.filter(plate="LL-234-LL").exists())

    def test_reservation_checkout_page_shows_payment_form(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        spot = self.parking.spots.get(number=1)

        response = self.client.get(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Réserver une place")
        self.assertContains(response, 'name="duration_hours"')
        self.assertContains(response, 'name="card_number"')
        self.assertContains(response, 'name="security_code"')
        self.assertNotContains(response, "Ces informations sont uniquement vérifiées")

    def test_checkout_preview_shows_reservation_details_without_card_data(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        spot = self.parking.spots.get(number=1)

        response = self.client.get(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id])
        )

        self.assertContains(response, "Récapitulatif avant validation")
        self.assertContains(response, 'class="section-card checkout-summary"')
        self.assertContains(response, "Parking Central — place n°1")
        self.assertContains(response, 'id="reservation-plate"')
        self.assertContains(response, 'id="reservation-duration"')
        self.assertContains(response, 'id="reservation-payment"')
        self.assertContains(response, 'id="reservation-total"')
        self.assertContains(response, "Nouveau moyen de paiement simulé")
        self.assertContains(response, "les données de carte saisies ne sont pas enregistrées")

    def test_reservation_requires_all_payment_details(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        spot = self.parking.spots.get(number=1)

        response = self.client.post(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
            {"plate": "GG-789-GG", "duration_hours": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="message message-error" role="alert"')
        self.assertContains(response, "Vérifiez les informations saisies")
        self.assertContains(response, "Numéro de carte")
        self.assertFalse(Reservation.objects.filter(plate="GG-789-GG").exists())

    def test_reservation_rejects_letters_in_card_number(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        spot = self.parking.spots.get(number=1)

        response = self.client.post(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
            {
                "plate": "GG-789-GG",
                "duration_hours": "1",
                "card_number": "1234AB6789012345",
                "expiration_date": "12/30",
                "security_code": "123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Numéro de carte")
        self.assertFalse(Reservation.objects.filter(plate="GG-789-GG").exists())

    def test_reservation_enforces_parking_max_duration(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.max_duration_minutes = 120
        self.parking.save()
        spot = self.parking.spots.get(number=1)

        response = self.client.post(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
            {
                "plate": "GG-789-GG",
                "duration_hours": "3",
                "card_number": "1234567890123456",
                "expiration_date": "12/30",
                "security_code": "123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La durée dépasse la limite de ce parking.")
        self.assertFalse(Reservation.objects.filter(plate="GG-789-GG").exists())

    def test_invalid_payment_details_are_not_echoed_back(self):
        self.authenticate_as_user()

        response = self.client.post(
            reverse("parking:payment_methods"),
            {
                "card_number": "1234567890123456",
                "expiration_date": "13/30",
                "security_code": "987",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="message message-error" role="alert"')
        self.assertContains(response, "Vérifiez les informations saisies")
        self.assertNotContains(response, "1234567890123456")
        self.assertNotContains(response, "987")
        self.assertFalse(DemoPaymentMethod.objects.exists())

    def test_anonymous_user_is_redirected_before_reserving(self):
        spot = self.parking.spots.get(number=1)

        response = self.client.get(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id])
        )
        self.assertRedirects(
            response,
            f"{reverse('parking:login')}?next={reverse('parking:reserve_spot', args=[self.parking.id, spot.id])}",
        )

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

    def test_user_can_confirm_arrival_and_start_parking_countdown(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        reservation = Reservation.objects.create(
            user=user,
            spot=self.parking.spots.get(number=1),
            plate="MM-345-MM",
            duration_hours=2,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("parking:reservation_list"))
        self.assertContains(response, "Confirmer mon arrivée")
        self.assertContains(response, "Le décompte commencera")

        response = self.client.post(
            reverse("parking:confirm_arrival", args=[reservation.id])
        )

        self.assertRedirects(response, reverse("parking:reservation_list"))
        reservation.refresh_from_db()
        self.assertIsNotNone(reservation.arrived_at)
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)

        response = self.client.get(reverse("parking:reservation_list"))
        self.assertContains(response, "Temps de stationnement restant")
        self.assertContains(response, "data-duration-hours=\"2\"")
        self.assertNotContains(response, "Confirmer mon arrivée")

    def test_confirming_arrival_again_does_not_reset_timer(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        reservation = Reservation.objects.create(
            user=user,
            spot=self.parking.spots.get(number=1),
            plate="NN-456-NN",
            arrived_at=timezone.now() - timedelta(minutes=10),
        )
        initial_arrival = reservation.arrived_at
        self.client.force_login(user)

        response = self.client.post(
            reverse("parking:confirm_arrival", args=[reservation.id])
        )

        self.assertRedirects(response, reverse("parking:reservation_list"))
        reservation.refresh_from_db()
        self.assertEqual(reservation.arrived_at, initial_arrival)

    def test_user_cannot_confirm_another_users_arrival(self):
        owner = get_user_model().objects.create_user(username="owner", password="password")
        other_user = get_user_model().objects.create_user(username="other", password="password")
        reservation = Reservation.objects.create(
            user=owner,
            spot=self.parking.spots.get(number=1),
            plate="PP-567-PP",
        )
        self.client.force_login(other_user)

        response = self.client.post(
            reverse("parking:confirm_arrival", args=[reservation.id])
        )

        self.assertEqual(response.status_code, 404)
        reservation.refresh_from_db()
        self.assertIsNone(reservation.arrived_at)

    def test_arrival_confirmation_requires_post(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        reservation = Reservation.objects.create(
            user=user,
            spot=self.parking.spots.get(number=1),
            plate="QQ-678-QQ",
        )
        self.client.force_login(user)

        response = self.client.get(
            reverse("parking:confirm_arrival", args=[reservation.id])
        )

        self.assertEqual(response.status_code, 405)
        reservation.refresh_from_db()
        self.assertIsNone(reservation.arrived_at)

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

    def test_cancellation_requires_post(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        reservation = Reservation.objects.create(
            user=user,
            spot=self.parking.spots.get(number=1),
            plate="EE-567-EE",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("parking:cancel_reservation", args=[reservation.id]))

        self.assertEqual(response.status_code, 405)
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

    def test_agent_dashboard_shows_actions_and_current_occupancy(self):
        agent = get_user_model().objects.create_user(username="dashboard-agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        Reservation.objects.create(
            spot=self.parking.spots.get(number=1),
            plate="AA-123-AA",
        )
        self.client.force_login(agent)

        response = self.client.get(reverse("parking:agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["occupied"], 1)
        self.assertContains(response, "50 %")
        for name in ("agent_plate_check", "agent_stats", "agent_affluence"):
            self.assertContains(response, reverse(f"parking:{name}"))
        self.assertContains(response, "créer une contravention")
        self.assertEqual(response.content.count(b"/agent/plaque/"), 2)  # navigation and dashboard action

    def test_agent_dashboard_handles_no_parking_data(self):
        agent = get_user_model().objects.create_user(username="dashboard-agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        Parking.objects.all().delete()
        self.client.force_login(agent)

        response = self.client.get(reverse("parking:agent_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucune place n’est configurée")
        self.assertEqual(response.context["occupied"], 0)

    def test_non_agent_and_anonymous_cannot_access_agent_dashboard(self):
        url = reverse("parking:agent_dashboard")
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('parking:agent_login')}?next={url}")

        user = get_user_model().objects.create_user(username="regular-user", password="password")
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('parking:agent_login')}?next={url}")

    def test_agent_can_end_an_active_reservation(self):
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        reservation = Reservation.objects.create(
            user=agent,
            spot=self.parking.spots.get(number=1),
            plate="AA-123-AA",
        )
        self.client.login(username="agent", password="password")

        response = self.client.post(
            reverse("parking:agent_end_reservation", args=[reservation.id])
        )

        self.assertRedirects(
            response,
            f"{reverse('parking:agent_plate_check')}?plate=AA-123-AA",
        )
        reservation.refresh_from_db()
        reservation.spot.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.COMPLETED)
        self.assertIsNotNone(reservation.ended_at)
        self.assertTrue(reservation.spot.is_available)

    def test_agent_closure_requires_post(self):
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        reservation = Reservation.objects.create(
            spot=self.parking.spots.get(number=1),
            plate="EE-567-EE",
        )
        self.client.force_login(agent)

        response = self.client.get(reverse("parking:agent_end_reservation", args=[reservation.id]))

        self.assertEqual(response.status_code, 405)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)

    def test_agent_plate_filter_rejects_invalid_and_overlong_input(self):
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

        response = self.client.get(
            reverse("parking:agent_plate_check"),
            {"plate": "x" * 100},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["plate"], "")
        self.assertIsNone(response.context["result"])

    def test_plate_check_explains_when_no_plate_has_been_checked(self):
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

        response = self.client.get(reverse("parking:agent_plate_check"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucune plaque vérifiée")
        self.assertContains(response, "Saisissez une plaque")

    def test_agent_logout_requires_post(self):
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

        response = self.client.get(reverse("parking:agent_logout"))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_non_agent_cannot_end_an_active_reservation(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        reservation = Reservation.objects.create(
            user=user,
            spot=self.parking.spots.get(number=1),
            plate="BB-234-BB",
        )
        self.client.login(username="alice", password="password")

        response = self.client.post(
            reverse("parking:agent_end_reservation", args=[reservation.id])
        )

        self.assertRedirects(
            response,
            f"{reverse('parking:agent_login')}?next={reverse('parking:agent_end_reservation', args=[reservation.id])}",
        )
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)

    def test_agent_can_create_a_contravention_for_a_non_conforming_plate(self):
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

        response = self.client.post(
            reverse("parking:create_contravention"),
            {"plate": "AA-123-AA", "reason": "Stationnement sans réservation"},
            follow=True,
        )

        self.assertRedirects(
            response,
            f"{reverse('parking:agent_plate_check')}?plate=AA-123-AA",
        )
        contravention = Contravention.objects.get()
        self.assertEqual(contravention.agent, agent)
        self.assertEqual(contravention.plate, "AA-123-AA")
        self.assertEqual(contravention.reason, "Stationnement sans réservation")
        self.assertContains(response, "La contravention a bien été créée.")

    def test_non_agent_cannot_create_a_contravention(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        self.client.force_login(user)

        response = self.client.post(
            reverse("parking:create_contravention"),
            {"plate": "AA-123-AA", "reason": "Motif"},
            follow=True,
        )

        self.assertRedirects(
            response,
            f"{reverse('parking:agent_login')}?next={reverse('parking:create_contravention')}",
        )
        self.assertFalse(Contravention.objects.exists())

    def test_agent_cannot_create_a_contravention_for_an_active_reservation(self):
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        Reservation.objects.create(
            user=agent,
            spot=self.parking.spots.get(number=1),
            plate="AA-123-AA",
        )
        self.client.force_login(agent)

        response = self.client.post(
            reverse("parking:create_contravention"),
            {"plate": "AA-123-AA", "reason": "Motif"},
            follow=True,
        )

        self.assertRedirects(
            response,
            f"{reverse('parking:agent_plate_check')}?plate=AA-123-AA",
        )
        self.assertFalse(Contravention.objects.exists())
        self.assertContains(response, "Ce véhicule possède une réservation active.")

    def test_invalid_contravention_shows_an_error_message(self):
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

        response = self.client.post(
            reverse("parking:create_contravention"),
            {"plate": "AA-123-AA", "reason": "   "},
            follow=True,
        )

        self.assertRedirects(
            response,
            f"{reverse('parking:agent_plate_check')}?plate=AA-123-AA",
        )
        self.assertFalse(Contravention.objects.exists())
        self.assertContains(response, "La plaque et le motif sont invalides.")

    def test_plate_check_shows_contravention_form_only_for_non_conforming_plate(self):
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

        response = self.client.get(
            reverse("parking:agent_plate_check"),
            {"plate": "AA-123-AA"},
        )
        self.assertContains(response, "Créer une contravention")
        self.assertContains(response, "Non conforme — aucune réservation active")
        self.assertContains(response, 'name="reason"')
        self.assertContains(response, "obligatoire")
        self.assertContains(response, "confirm('Créer une contravention")

        reservation = Reservation.objects.create(
            user=agent,
            spot=self.parking.spots.get(number=1),
            plate="BB-234-BB",
        )
        response = self.client.get(
            reverse("parking:agent_plate_check"),
            {"plate": "BB-234-BB"},
        )
        self.assertContains(response, "Non confirmée")

        reservation.arrived_at = timezone.now()
        reservation.save()
        response = self.client.get(
            reverse("parking:agent_plate_check"),
            {"plate": "BB-234-BB"},
        )
        self.assertContains(response, "BB-234-BB")
        self.assertContains(response, "Parking Central")
        self.assertContains(response, "Place")
        self.assertContains(response, "Confirmée le")
        self.assertContains(response, "Clôturer le stationnement")
        self.assertNotContains(response, "Créer une contravention")

    def test_parking_list_page(self):
        self.authenticate_as_user()

        response = self.client.get(reverse("parking:parking_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Central")
        self.assertContains(response, "1 rue du Centre")
        self.assertContains(response, "1")
        self.assertContains(response, "2")

    def test_parking_detail_page(self):
        self.authenticate_as_user()
        self.parking.latitude = 48.8566
        self.parking.longitude = 2.3522
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()

        response = self.client.get(
            reverse(
                "parking:parking_detail",
                args=[self.parking.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Central")
        self.assertContains(response, "Place n°1")
        self.assertNotContains(response, "Place n°2")
        self.assertContains(response, 'class="topbar"')
        self.assertContains(response, 'href="/parkings/">Parkings</a>')
        self.assertContains(response, 'href="/parkings/">Retour à la liste des parkings</a>')
        self.assertContains(response, "Réserver")
        self.assertContains(response, "Places disponibles")
        self.assertContains(response, "1/2")
        self.assertContains(response, "Réserver la place n°1")
        self.assertNotContains(response, 'name="card_number"')
        self.assertContains(response, 'id="detail-map"')
        self.assertContains(response, 'id="parking-data"')
        self.assertContains(response, "zoom: 15")
        self.assertEqual(response.context["parking_data"]["latitude"], 48.8566)
        self.assertEqual(response.context["parking_data"]["longitude"], 2.3522)

    def test_parking_detail_links_to_checkout_without_plate_field(self):
        self.authenticate_as_user()
        spot = self.parking.spots.get(number=1)

        response = self.client.get(
            reverse(
                "parking:parking_detail",
                args=[self.parking.id],
            )
        )

        self.assertNotContains(response, 'name="plate"')
        self.assertContains(
            response,
            f'href="{reverse("parking:reserve_spot", args=[self.parking.id, spot.id])}"',
        )

    def test_missing_parking_returns_not_found(self):
        self.authenticate_as_user()

        response = self.client.get(
            reverse("parking:parking_detail", args=[999])
        )

        self.assertEqual(response.status_code, 404)

    def test_out_of_range_database_id_returns_not_found(self):
        self.authenticate_as_user()

        response = self.client.get("/parkings/999999999999999999999999/")

        self.assertEqual(response.status_code, 404)

    def test_parking_list_contains_map_and_parking_data(self):
        self.authenticate_as_user()
        self.parking.latitude = 48.8566
        self.parking.longitude = 2.3522
        self.parking.save()

        response = self.client.get(reverse("parking:parking_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="map"')
        self.assertContains(response, 'class="topbar"')
        self.assertContains(response, 'href="/">Accueil</a>')
        self.assertContains(response, "Parking Central")
        self.assertContains(response, 'id="parkings-data"')
        self.assertContains(response, "Voir sur la carte")
        self.assertContains(response, "const marker = parkingMarkers.get(button.dataset.parkingId)")
        self.assertContains(response, "map.panTo(marker.getPosition())")
        self.assertContains(response, "map.setZoom(15)")
        self.assertContains(response, 'google.maps.event.trigger(marker, "click")')
        self.assertEqual(response.content.count(b'document.querySelectorAll(".focus-map-button")'), 1)

    def test_parking_detail_shows_pricing(self):
        self.authenticate_as_user()

        self.parking.hourly_rate = Decimal("2.50")
        self.parking.max_duration_minutes = 120
        self.parking.opening_time = time(7, 0)
        self.parking.closing_time = time(21, 0)
        self.parking.save()

        response = self.client.get(reverse("parking:parking_detail", args=[self.parking.id]))

        self.assertContains(response, "2,50 € / heure")
        self.assertContains(response, "Durée maximale : 2 h")
        self.assertContains(response, "07:00 – 21:00")
        self.assertContains(response, "Places disponibles")
        self.assertContains(response, "1/2")
        self.assertContains(response, "Réserver la place n°1")

    def test_parking_list_shows_pricing(self):
        self.authenticate_as_user()

        self.parking.hourly_rate = Decimal("1.80")
        self.parking.save()

        response = self.client.get(reverse("parking:parking_list"))

        self.assertContains(response, "1,80 € / heure")
        self.assertContains(response, "Ouvert 24h/24")

    def test_parking_without_rate_shows_not_provided(self):
        self.authenticate_as_user()

        response = self.client.get(reverse("parking:parking_detail", args=[self.parking.id]))

        self.assertContains(response, "non renseigné")

    def test_free_parking_shows_free(self):
        self.authenticate_as_user()

        self.parking.hourly_rate = Decimal("0")
        self.parking.save()

        response = self.client.get(reverse("parking:parking_detail", args=[self.parking.id]))

        self.assertContains(response, "Gratuit")

    def test_authentificated_user_can_log_out(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        self.client.login(username="alice", password="password")

        response = self.client.post(reverse("parking:logout"))

        response = self.client.get(reverse("parking:reservation_list"))
        self.assertRedirects(
            response,
            f"{reverse('parking:login')}?next={reverse('parking:reservation_list')}",
        )

    def test_home_page_shows_logout_button_for_authenticated_user(self):
        get_user_model().objects.create_user(
            username="alice",
            password="password",
        )
        self.client.login(username="alice", password="password")

        response = self.client.get(reverse("parking:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Se déconnecter")
        self.assertContains(response, reverse("parking:logout"))
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_home_page_does_not_show_logout_button_for_anonymous_user(self):
            response = self.client.get(reverse("parking:home"))

            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Se déconnecter") 

    def test_agent_can_still_access_agent_login_page(self):
            response = self.client.get(reverse("parking:agent_login"))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Connexion agent")

    def test_parking_list_filters_by_maximum_rate(self):
        self.authenticate_as_user()

        self.parking.hourly_rate = Decimal("1.50")
        self.parking.save()

        expensive_parking = Parking.objects.create(
            name="Parking Cher",
            address="2 rue du Centre",
            hourly_rate=Decimal("4.00"),
        )

        response = self.client.get(
            reverse("parking:parking_list"),
            {"max_rate": "2.00"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Central")
        self.assertNotContains(response, "Parking Cher")


    def test_parking_list_filters_by_duration(self):
        self.authenticate_as_user()

        self.parking.max_duration_minutes = 60
        self.parking.save()

        long_duration_parking = Parking.objects.create(
            name="Parking Longue Durée",
            address="3 rue du Centre",
            max_duration_minutes=180,
        )

        response = self.client.get(
            reverse("parking:parking_list"),
            {"minimum_duration": "2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Longue Durée")
        self.assertNotContains(response, "Parking Central")

class FavoriteTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alice",
            password="password123",
        )
        self.parking = Parking.objects.create(
            name="Parking Central",
            address="1 rue du Centre",
        )

    def test_user_can_create_favorite(self):
        favorite = Favorite.objects.create(
            user=self.user,
            parking=self.parking,
        )

        self.assertEqual(Favorite.objects.count(), 1)
        self.assertEqual(favorite.user, self.user)
        self.assertEqual(favorite.parking, self.parking)

    def test_same_parking_cannot_be_favorited_twice_by_same_user(self):
        Favorite.objects.create(
            user=self.user,
            parking=self.parking,
        )

        with self.assertRaises(IntegrityError):
            Favorite.objects.create(
                user=self.user,
                parking=self.parking,
            )

    def test_different_users_can_favorite_same_parking(self):
        another_user = get_user_model().objects.create_user(
            username="bob",
            password="password123",
        )

        Favorite.objects.create(
            user=self.user,
            parking=self.parking,
        )
        Favorite.objects.create(
            user=another_user,
            parking=self.parking,
        )

        self.assertEqual(
            Favorite.objects.filter(parking=self.parking).count(),
            2,
        )

    def test_deleting_parking_deletes_its_favorites(self):
        Favorite.objects.create(
            user=self.user,
            parking=self.parking,
        )

        self.parking.delete()

        self.assertEqual(Favorite.objects.count(), 0)

    def test_deleting_user_deletes_their_favorites(self):
        Favorite.objects.create(
            user=self.user,
            parking=self.parking,
        )

        self.user.delete()

        self.assertEqual(Favorite.objects.count(), 0)

class FavoriteViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alice",
            password="password123",
        )
        self.other_user = get_user_model().objects.create_user(
            username="bob",
            password="password123",
        )
        self.parking = Parking.objects.create(
            name="Parking Central",
            address="1 rue du Centre",
        )

        self.toggle_url = reverse(
            "parking:toggle_favorite",
            kwargs={"parking_id": self.parking.id},
        )
        self.favorite_list_url = reverse("parking:favorite_list")
        self.parking_list_url = reverse("parking:parking_list")

    def test_authenticated_user_can_add_parking_to_favorites(self):
        self.client.force_login(self.user)

        response = self.client.post(self.toggle_url)

        self.assertRedirects(response, self.parking_list_url)
        self.assertTrue(
            Favorite.objects.filter(
                user=self.user,
                parking=self.parking,
            ).exists()
        )

    def test_authenticated_user_can_remove_parking_from_favorites(self):
        self.client.force_login(self.user)

        Favorite.objects.create(
            user=self.user,
            parking=self.parking,
        )

        response = self.client.post(self.toggle_url)

        self.assertRedirects(response, self.parking_list_url)
        self.assertFalse(
            Favorite.objects.filter(
                user=self.user,
                parking=self.parking,
            ).exists()
        )

    def test_get_request_is_not_allowed_for_toggle_favorite(self):
        self.client.force_login(self.user)

        response = self.client.get(self.toggle_url)

        self.assertEqual(response.status_code, 405)
        self.assertFalse(Favorite.objects.exists())

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.post(self.toggle_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/connexion/", response.url)
        self.assertFalse(Favorite.objects.exists())

    def test_user_cannot_see_another_users_favorites(self):
        self.client.force_login(self.user)

        Favorite.objects.create(
            user=self.other_user,
            parking=self.parking,
        )

        response = self.client.get(self.favorite_list_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.parking.name)

    def test_favorite_list_contains_current_user_favorites(self):
        self.client.force_login(self.user)

        Favorite.objects.create(
            user=self.user,
            parking=self.parking,
        )

        response = self.client.get(self.favorite_list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.parking.name)

    def test_parking_list_contains_parking_as_favorite(self):
        self.client.force_login(self.user)

        Favorite.objects.create(
            user=self.user,
            parking=self.parking,
        )

        response = self.client.get(self.parking_list_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            self.parking.id,
            response.context["favorite_parking_ids"],
        )
        self.assertContains(response, "Retirer des favoris")

    def test_parking_list_contains_add_favorite_button(self):
        self.client.force_login(self.user)

        response = self.client.get(self.parking_list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ajouter aux favoris")
        self.assertNotContains(response, "Retirer des favoris")

    def test_add_favorite_displays_success_message(self):
        self.client.force_login(self.user)

        response = self.client.post(self.toggle_url, follow=True)

        self.assertContains(
            response,
            "Parking Central a été ajouté à vos favoris.",
        )

    def test_remove_favorite_displays_success_message(self):
        self.client.force_login(self.user)

        Favorite.objects.create(
            user=self.user,
            parking=self.parking,
        )

        response = self.client.post(self.toggle_url, follow=True)

        self.assertContains(
            response,
            "Parking Central a été retiré de vos favoris.",
        )

class AgentStatsTests(TestCase):
    def setUp(self):
        self.parking = Parking.objects.create(name="Parking Gare", address="2 place de la Gare")
        self.spot_1 = Spot.objects.create(parking=self.parking, number=1)
        self.spot_2 = Spot.objects.create(parking=self.parking, number=2)
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

    def test_non_agent_is_redirected(self):
        self.client.force_login(get_user_model().objects.create_user(username="bob", password="password"))

        response = self.client.get(reverse("parking:agent_stats"))

        self.assertRedirects(
            response,
            f"{reverse('parking:agent_login')}?next={reverse('parking:agent_stats')}",
            fetch_redirect_response=False,
        )

    def test_stats_show_parked_plates_and_occupancy(self):
        Reservation.objects.create(spot=self.spot_1, plate="AB-123-CD")

        response = self.client.get(reverse("parking:agent_stats"))

        self.assertEqual(response.status_code, 200)
        entry = response.context["stats"][0]
        self.assertEqual(entry["occupied"], 1)
        self.assertEqual(entry["free"], 1)
        self.assertEqual(entry["rate"], 50)
        self.assertEqual([r.plate for r in entry["active_reservations"]], ["AB-123-CD"])
        self.assertContains(response, "AB-123-CD")

    def test_movements_list_plates_with_most_recent_first(self):
        reservation = Reservation.objects.create(spot=self.spot_1, plate="AB-123-CD")
        reservation.status = Reservation.Status.COMPLETED
        reservation.ended_at = reservation.created_at + timedelta(hours=1)
        reservation.save()
        Reservation.objects.create(spot=self.spot_2, plate="EF-456-GH")

        response = self.client.get(reverse("parking:agent_stats"))

        entry = response.context["stats"][0]
        self.assertEqual(entry["occupied"], 1)
        self.assertEqual(entry["active_reservations"][0].plate, "EF-456-GH")
        self.assertEqual(
            [(m["label"], m["plate"]) for m in entry["movements"]],
            [("Départ", "AB-123-CD"), ("Réservation", "EF-456-GH"), ("Réservation", "AB-123-CD")],
        )
        self.assertContains(response, "Départ")

    def test_cancelled_reservation_frees_the_spot(self):
        reservation = Reservation.objects.create(spot=self.spot_1, plate="AB-123-CD")
        reservation.status = Reservation.Status.CANCELLED
        reservation.ended_at = timezone.now()
        reservation.save()

        response = self.client.get(reverse("parking:agent_stats"))

        entry = response.context["stats"][0]
        self.assertEqual(entry["occupied"], 0)
        self.assertEqual(entry["movements"][0]["label"], "Annulation")
        self.assertEqual(entry["movements"][0]["occupied"], 0)


class UserDepartureAndSummaryTests(TestCase):
    def setUp(self):
        self.parking = Parking.objects.create(name="Parking Gare", address="2 place de la Gare")
        self.spot = Spot.objects.create(parking=self.parking, number=1)
        self.user = get_user_model().objects.create_user(username="alice", password="password")
        self.client.force_login(self.user)

    def create_reservation(self, **kwargs):
        return Reservation.objects.create(
            user=self.user,
            spot=self.spot,
            plate="AB-123-CD",
            duration_hours=2,
            amount_paid=Decimal("5.00"),
            **kwargs,
        )

    def test_user_can_declare_departure_after_arrival(self):
        reservation = self.create_reservation(arrived_at=timezone.now() - timedelta(minutes=30))

        response = self.client.post(reverse("parking:declare_departure", args=[reservation.id]))

        self.assertRedirects(response, reverse("parking:reservation_summary", args=[reservation.id]))
        reservation.refresh_from_db()
        self.spot.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.COMPLETED)
        self.assertIsNotNone(reservation.ended_at)
        self.assertTrue(self.spot.is_available)

    def test_departure_requires_confirmed_arrival(self):
        reservation = self.create_reservation()

        response = self.client.post(reverse("parking:declare_departure", args=[reservation.id]))

        self.assertEqual(response.status_code, 404)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)

    def test_user_cannot_declare_departure_for_another_user(self):
        other = get_user_model().objects.create_user(username="bob", password="password")
        reservation = Reservation.objects.create(
            user=other, spot=self.spot, plate="EF-456-GH", arrived_at=timezone.now()
        )

        response = self.client.post(reverse("parking:declare_departure", args=[reservation.id]))

        self.assertEqual(response.status_code, 404)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)

    def test_departure_requires_post(self):
        reservation = self.create_reservation(arrived_at=timezone.now())

        response = self.client.get(reverse("parking:declare_departure", args=[reservation.id]))

        self.assertEqual(response.status_code, 405)

    def test_user_deletion_frees_spot_after_reservation_cascade(self):
        reservation = self.create_reservation()
        self.spot.refresh_from_db()
        self.assertFalse(self.spot.is_available)

        self.user.delete()

        self.spot.refresh_from_db()
        self.assertTrue(self.spot.is_available)
        self.assertFalse(Reservation.objects.filter(pk=reservation.pk).exists())

    def test_reservation_list_shows_departure_button_only_after_arrival(self):
        reservation = self.create_reservation()
        url = reverse("parking:declare_departure", args=[reservation.id])

        self.assertNotContains(self.client.get(reverse("parking:reservation_list")), url)

        reservation.arrived_at = timezone.now()
        reservation.save()
        response = self.client.get(reverse("parking:reservation_list"))
        self.assertContains(response, url)
        self.assertContains(response, reverse("parking:reservation_summary", args=[reservation.id]))

    def test_closed_reservations_show_status_without_active_actions(self):
        cancelled = self.create_reservation()
        cancelled.status = Reservation.Status.CANCELLED
        cancelled.ended_at = timezone.now()
        cancelled.save()
        completed = Reservation.objects.create(
            user=self.user,
            spot=self.spot,
            plate="EF-456-GH",
            duration_hours=2,
            amount_paid=Decimal("5.00"),
            arrived_at=timezone.now(),
        )
        completed.status = Reservation.Status.COMPLETED
        completed.ended_at = timezone.now()
        completed.save()

        response = self.client.get(reverse("parking:reservation_list"))

        self.assertContains(response, "Annulée")
        self.assertContains(response, "Terminée")
        self.assertContains(response, "Annulée le :")
        self.assertContains(response, "Terminée le :")
        for reservation in (cancelled, completed):
            for view_name in ("confirm_arrival", "declare_departure", "cancel_reservation"):
                self.assertNotContains(
                    response,
                    reverse(f"parking:{view_name}", args=[reservation.id]),
                )

    def test_summary_shows_arrival_departure_duration_and_amount(self):
        arrived_at = timezone.now() - timedelta(hours=1, minutes=5)
        reservation = self.create_reservation(arrived_at=arrived_at)
        reservation.status = Reservation.Status.COMPLETED
        reservation.ended_at = arrived_at + timedelta(hours=1, minutes=5)
        reservation.save()

        response = self.client.get(reverse("parking:reservation_summary", args=[reservation.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Parking Gare")
        self.assertContains(response, "AB-123-CD")
        self.assertContains(response, "1 h 05")
        self.assertContains(response, "5,00 €")
        self.assertNotContains(response, "Durée réservée dépassée")

    def test_summary_flags_exceeded_duration(self):
        arrived_at = timezone.now() - timedelta(hours=3)
        reservation = self.create_reservation(arrived_at=arrived_at)
        reservation.status = Reservation.Status.COMPLETED
        reservation.ended_at = timezone.now()
        reservation.save()

        response = self.client.get(reverse("parking:reservation_summary", args=[reservation.id]))

        self.assertContains(response, "Durée réservée dépassée")

    def test_user_cannot_see_summary_of_another_user(self):
        other = get_user_model().objects.create_user(username="bob", password="password")
        reservation = Reservation.objects.create(user=other, spot=self.spot, plate="EF-456-GH")

        response = self.client.get(reverse("parking:reservation_summary", args=[reservation.id]))

        self.assertEqual(response.status_code, 404)


class AgentAffluenceTests(TestCase):
    def setUp(self):
        self.parking = Parking.objects.create(name="Parking Gare", address="2 place de la Gare")
        self.other_parking = Parking.objects.create(name="Parking Nord", address="3 rue du Nord")
        self.spots = [Spot.objects.create(parking=self.parking, number=n) for n in range(1, 5)]
        self.other_spot = Spot.objects.create(parking=self.other_parking, number=1)
        agent = get_user_model().objects.create_user(username="agent", password="password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)
        self.yesterday = timezone.localdate() - timedelta(days=1)

    def at(self, hour, minute=0):
        return timezone.make_aware(datetime.combine(self.yesterday, time(hour, minute)))

    def create_past_reservation(self, spot, plate, start, end):
        reservation = Reservation.objects.create(spot=spot, plate=plate, status=Reservation.Status.COMPLETED)
        Reservation.objects.filter(pk=reservation.pk).update(created_at=start, ended_at=end)

    def create_yesterday_traffic(self):
        self.create_past_reservation(self.spots[0], "AA-111-AA", self.at(10), self.at(12))
        self.create_past_reservation(self.spots[1], "BB-222-BB", self.at(11), self.at(11, 30))
        self.create_past_reservation(self.spots[2], "CC-333-CC", self.at(11, 15), self.at(11, 20))
        self.create_past_reservation(self.other_spot, "DD-444-DD", self.at(18), self.at(19))

    def test_non_agent_is_redirected(self):
        self.client.force_login(get_user_model().objects.create_user(username="bob", password="password"))

        response = self.client.get(reverse("parking:agent_affluence"))

        self.assertEqual(response.status_code, 302)

    def test_daily_peak_and_entries(self):
        self.create_yesterday_traffic()

        response = self.client.get(reverse("parking:agent_affluence"), {"parking": self.parking.id})

        self.assertEqual(response.status_code, 200)
        yesterday = next(entry for entry in response.context["daily"] if entry["day"] == self.yesterday)
        self.assertEqual(yesterday["entries"], 3)
        self.assertEqual(yesterday["peak"], 3)
        self.assertEqual(yesterday["peak_at"], self.at(11, 15))
        self.assertEqual(yesterday["peak_rate"], 75)
        self.assertEqual(response.context["busiest_day"]["day"], self.yesterday)

    def test_busiest_hour_and_weekday(self):
        self.create_yesterday_traffic()

        response = self.client.get(reverse("parking:agent_affluence"), {"parking": self.parking.id})

        self.assertEqual(response.context["busiest_hour"], 11)
        weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        self.assertEqual(response.context["busiest_weekday"], weekdays[self.yesterday.weekday()])
        self.assertContains(response, "11 h")

    def test_all_parkings_include_every_reservation(self):
        self.create_yesterday_traffic()

        response = self.client.get(reverse("parking:agent_affluence"))

        self.assertEqual(response.context["total_entries"], 4)
        self.assertEqual(response.context["total_spots"], 5)

    def test_period_filter(self):
        response = self.client.get(reverse("parking:agent_affluence"))
        self.assertEqual(len(response.context["daily"]), 7)

        response = self.client.get(reverse("parking:agent_affluence"), {"jours": "30"})
        self.assertEqual(len(response.context["daily"]), 30)

        response = self.client.get(reverse("parking:agent_affluence"), {"jours": "abc"})
        self.assertEqual(len(response.context["daily"]), 7)

    def test_oversized_parking_filter_is_ignored(self):
        response = self.client.get(reverse("parking:agent_affluence"), {"parking": "9" * 100})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["selected_parking"])

    def test_empty_history(self):
        response = self.client.get(reverse("parking:agent_affluence"))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["busiest_day"])
        self.assertIsNone(response.context["busiest_hour"])


class CsrfProtectionTests(TestCase):
    def setUp(self):
        self.parking = Parking.objects.create(
            name="Parking sécurisé",
            address="1 rue du Centre",
            hourly_rate=Decimal("2.50"),
        )
        self.spot = Spot.objects.create(parking=self.parking, number=1)
        self.user = get_user_model().objects.create_user(username="alice", password="password")
        self.agent = get_user_model().objects.create_user(username="agent", password="password")
        self.agent.groups.add(Group.objects.create(name="Agents"))
        self.client = Client(enforce_csrf_checks=True)

    def test_user_mutations_require_csrf_token(self):
        self.client.force_login(self.user)
        active = Reservation.objects.create(user=self.user, spot=self.spot, plate="AA-123-AA")
        arrived = Reservation.objects.create(
            user=self.user,
            spot=Spot.objects.create(parking=self.parking, number=2),
            plate="BB-234-BB",
            arrived_at=timezone.now(),
        )
        urls_and_data = [
            (
                reverse("parking:reserve_spot", args=[self.parking.id, Spot.objects.create(parking=self.parking, number=3).id]),
                {
                    "plate": "CC-345-CC",
                    "duration_hours": "1",
                    "card_number": "1234567890123456",
                    "expiration_date": "12/30",
                    "security_code": "123",
                },
            ),
            (reverse("parking:cancel_reservation", args=[active.id]), {}),
            (reverse("parking:confirm_arrival", args=[active.id]), {}),
            (reverse("parking:declare_departure", args=[arrived.id]), {}),
            (
                reverse("parking:payment_methods"),
                {"card_number": "1234567890123456", "expiration_date": "12/30", "security_code": "123"},
            ),
        ]

        for url, data in urls_and_data:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)

        self.assertFalse(Reservation.objects.filter(plate="CC-345-CC").exists())
        self.assertFalse(DemoPaymentMethod.objects.exists())
        active.refresh_from_db()
        self.assertIsNone(active.arrived_at)
        self.assertEqual(active.status, Reservation.Status.ACTIVE)
        arrived.refresh_from_db()
        self.assertEqual(arrived.status, Reservation.Status.ACTIVE)

    def test_agent_closure_requires_csrf_token(self):
        self.client.force_login(self.agent)
        reservation = Reservation.objects.create(
            spot=self.spot,
            plate="DD-456-DD",
        )

        response = self.client.post(reverse("parking:agent_end_reservation", args=[reservation.id]))

        self.assertEqual(response.status_code, 403)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)
