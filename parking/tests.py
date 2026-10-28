from datetime import datetime, timedelta, time
from decimal import Decimal
from io import StringIO
import re
from unittest.mock import patch

from django.core import mail
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Contravention,
    DemoPaymentMethod,
    Favorite,
    Parking,
    Reservation,
    Spot,
    UserProfile,
)


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
        for parking in Parking.objects.all():
            with self.subTest(parking=parking.name):
                self.assertEqual(parking.spots.filter(is_pmr=True).count(), 2)
        self.assertEqual(Reservation.objects.filter(user__in=agents).count(), 0)
        self.assertEqual(Reservation.objects.filter(user=demo_user).count(), 3)
        demo_summary = Reservation.objects.get(plate="II-901-II")
        self.assertEqual(demo_summary.user, demo_user)
        self.assertEqual(demo_summary.duration_minutes, 210)
        self.assertEqual(demo_summary.actual_duration_display, "136 min")
        self.assertEqual(demo_summary.amount_charged, Decimal("6.30"))
        self.assertEqual(demo_summary.amount_paid, Decimal("4.08"))
        self.assertEqual(demo_summary.amount_refunded, Decimal("2.22"))
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

    def test_seed_data_creates_contraventions_with_agents_and_demo_owner(self):
        call_command("seed_data", stdout=StringIO())

        self.assertEqual(Contravention.objects.count(), 2)
        first_fine = Contravention.objects.get(plate="YY-111-YY")
        second_fine = Contravention.objects.get(plate="ZZ-222-ZZ")
        self.assertEqual(first_fine.agent.username, "agent1")
        self.assertEqual(first_fine.user.username, "demo")
        self.assertEqual(first_fine.fine_type, Contravention.FineType.NO_PAYMENT)
        self.assertEqual(first_fine.amount, Decimal("50.00"))
        self.assertEqual(first_fine.parking.name, "Parking Centre-Ville")
        self.assertEqual(second_fine.agent.username, "agent2")
        self.assertIsNone(second_fine.user)
        self.assertEqual(second_fine.fine_type, Contravention.FineType.OVERSTAY)
        self.assertEqual(second_fine.amount, Decimal("35.00"))

    def test_seed_data_is_idempotent_for_contraventions(self):
        call_command("seed_data", stdout=StringIO())
        first_ids = set(Contravention.objects.values_list("id", flat=True))

        call_command("seed_data", stdout=StringIO())

        self.assertEqual(Contravention.objects.count(), 2)
        self.assertSetEqual(
            set(Contravention.objects.values_list("id", flat=True)),
            first_ids,
        )
        self.assertEqual(
            Contravention.objects.get(plate="YY-111-YY").parking.name,
            "Parking Centre-Ville",
        )


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

    def test_home_page_presents_user_and_professional_entry_points(self):
        response = self.client.get(reverse("parking:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La bonne place.")
        self.assertContains(response, "LE STATIONNEMENT, PLUS SIMPLE")
        self.assertContains(response, "Accès professionnel")
        self.assertContains(response, reverse("parking:signup"))
        self.assertContains(response, reverse("parking:login"))
        self.assertContains(response, reverse("parking:agent_login"))
        self.assertNotContains(response, reverse("admin:index"))
        self.assertNotContains(response, reverse("parking:reservation_list"))

    def test_home_page_shows_faq_about_parking_reservations_and_pmr(self):
        response = self.client.get(reverse("parking:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Questions fréquentes")
        self.assertContains(response, "Comment trouver un parking disponible ?")
        self.assertContains(response, "Comment réserver une place ?")
        self.assertContains(response, "Où retrouver mes réservations ?")
        self.assertContains(response, "Comment accéder aux places PMR ?")
        self.assertContains(response, "Activez la déclaration de justificatif PMR")

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

    def test_topbar_dropdowns_are_configured_to_close_each_other(self):
        user = get_user_model().objects.create_user(
            username="staff-agent",
            password="valid-test-password",
            is_staff=True,
        )
        user.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(user)

        response = self.client.get(reverse("parking:agent_dashboard"))

        self.assertContains(response, 'class="nav-menu"')
        self.assertContains(response, 'class="account-menu"')
        self.assertContains(response, 'querySelectorAll(".topbar-inner details")')

    def test_account_form_updates_email_and_vehicle_model(self):
        self.authenticate_as_user()

        response = self.client.post(
            reverse("parking:account"),
            {
                "email": "parking-viewer@example.com",
                "phone_number": "06 12 34 56 78",
                "vehicle_model": "peugeot_208",
            },
            follow=True,
        )

        user = get_user_model().objects.get(username="parking-viewer")
        profile = UserProfile.objects.get(user=user)
        self.assertRedirects(response, reverse("parking:account"))
        self.assertEqual(user.email, "parking-viewer@example.com")
        self.assertEqual(profile.vehicle_model, "peugeot_208")

    def test_settings_page_groups_profile_vehicle_notifications_and_payment(self):
        self.authenticate_as_user()

        response = self.client.get(reverse("parking:settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paramètres")
        self.assertContains(response, "Véhicule et accessibilité")
        self.assertContains(response, "Notifications")
        self.assertContains(response, reverse("parking:password_change"))
        self.assertContains(response, reverse("parking:payment_methods"))
        self.assertContains(response, 'name="notifications_enabled"')

    def test_settings_can_disable_stationing_reminders(self):
        self.authenticate_as_user()

        response = self.client.post(
            reverse("parking:settings"),
            {
                "email": "parking-viewer@example.com",
                "phone_number": "",
                "vehicle_model": "peugeot_208",
                "notifications_enabled": "",
            },
        )

        self.assertRedirects(response, reverse("parking:settings"))
        profile = UserProfile.objects.get(user__username="parking-viewer")
        self.assertFalse(profile.notifications_enabled)

    def test_user_can_change_password_from_settings(self):
        user = get_user_model().objects.create_user(
            username="settings-password-user",
            password="Original-password-123!",
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("parking:password_change"),
            {
                "old_password": "Original-password-123!",
                "new_password1": "New-password-456!",
                "new_password2": "New-password-456!",
            },
        )

        self.assertRedirects(response, reverse("parking:settings"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("New-password-456!"))
        self.assertEqual(
            self.client.get(reverse("parking:settings")).status_code,
            200,
        )

    def test_account_deletion_requires_exact_username_and_confirmation(self):
        self.authenticate_as_user()
        user = get_user_model().objects.get(username="parking-viewer")

        response = self.client.post(
            reverse("parking:delete_account"),
            {
                "confirm_deletion": "on",
                "username_confirmation": "Parking-viewer",
            },
            follow=True,
        )

        self.assertContains(response, "Le nom saisi ne correspond pas")
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_account_deletion_requires_explicit_confirmation(self):
        self.authenticate_as_user()
        user = get_user_model().objects.get(username="parking-viewer")

        response = self.client.post(
            reverse("parking:delete_account"),
            {"username_confirmation": user.username},
            follow=True,
        )

        self.assertContains(
            response,
            "Confirmez que vous souhaitez supprimer définitivement votre compte.",
        )
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())

    def test_account_deletion_is_blocked_while_user_has_active_reservation(self):
        self.authenticate_as_user()
        user = get_user_model().objects.get(username="parking-viewer")
        Reservation.objects.create(
            user=user,
            spot=self.parking.spots.get(number=1),
            plate="AB-123-CD",
            status=Reservation.Status.ACTIVE,
        )

        response = self.client.post(
            reverse("parking:delete_account"),
            {
                "confirm_deletion": "on",
                "username_confirmation": user.username,
            },
            follow=True,
        )

        self.assertContains(response, "un stationnement est en cours")
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_account_deletion_is_blocked_while_user_has_contravention(self):
        self.authenticate_as_user()
        user = get_user_model().objects.get(username="parking-viewer")
        agent = get_user_model().objects.create_user(username="deletion-agent", password="unused")
        agent.groups.add(Group.objects.create(name="Agents"))
        Contravention.objects.create(
            agent=agent,
            user=user,
            plate="AB-123-CD",
            reason="Stationnement interdit",
        )

        response = self.client.post(
            reverse("parking:delete_account"),
            {
                "confirm_deletion": "on",
                "username_confirmation": user.username,
            },
            follow=True,
        )

        self.assertContains(response, "une contravention reçue lui est associée")
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_account_deletion_is_allowed_when_user_only_issued_contravention(self):
        self.authenticate_as_user()
        user = get_user_model().objects.get(username="parking-viewer")
        observer = get_user_model().objects.create_user(
            username="remaining-agent",
            password="unused",
        )
        observer.groups.add(Group.objects.create(name="Agents"))
        contravention = Contravention.objects.create(
            agent=user,
            plate="AB-123-CD",
            reason="Stationnement interdit",
        )

        response = self.client.post(
            reverse("parking:delete_account"),
            {
                "confirm_deletion": "on",
                "username_confirmation": user.username,
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("parking:home"))
        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertContains(response, "Votre compte a été supprimé.")
        contravention.refresh_from_db()
        self.assertIsNone(contravention.agent)
        self.assertEqual(contravention.agent_name, "parking-viewer")
        self.client.force_login(observer)
        detail = self.client.get(
            reverse(
                "parking:agent_contravention_detail",
                args=[contravention.id],
            )
        )
        self.assertContains(detail, "<dt>Agent</dt><dd>parking-viewer</dd>")

    def test_account_deletion_succeeds_when_confirmed_and_unblocked(self):
        self.authenticate_as_user()
        user = get_user_model().objects.get(username="parking-viewer")

        response = self.client.post(
            reverse("parking:delete_account"),
            {
                "confirm_deletion": "on",
                "username_confirmation": user.username,
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("parking:home"))
        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "Votre compte a été supprimé.")

    def test_account_saves_pmr_justification_declaration(self):
        self.authenticate_as_user()

        self.client.post(
            reverse("parking:account"),
            {
                "email": "parking-viewer@example.com",
                "phone_number": "",
                "vehicle_model": "",
                "pmr_justification_registered": "on",
            },
        )

        profile = UserProfile.objects.get(user__username="parking-viewer")
        self.assertTrue(profile.pmr_justification_registered)

    def test_account_shows_saved_simulated_payment_method_without_card_data(self):
        self.authenticate_as_user()
        DemoPaymentMethod.objects.create(
            user=get_user_model().objects.get(username="parking-viewer")
        )

        response = self.client.get(reverse("parking:account"))

        self.assertContains(response, "Un moyen de paiement simulé est associé à votre compte.")
        self.assertContains(response, reverse("parking:payment_methods"))
        self.assertContains(response, "Aucune donnée de carte bancaire n’est conservée")
        self.assertNotContains(response, "1234567890123456")

    def test_account_offers_to_add_a_payment_method_when_none_is_saved(self):
        self.authenticate_as_user()

        response = self.client.get(reverse("parking:account"))

        self.assertContains(response, "Aucun moyen de paiement simulé n’est encore enregistré.")
        self.assertContains(response, "Ajouter un moyen de paiement")

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

        self.assertContains(checkout, 'name="duration_minutes"')
        self.assertContains(checkout, "Durée")
        self.assertContains(checkout, 'for="id_duration_days"')
        self.assertContains(checkout, 'for="id_duration_hours"')
        self.assertContains(checkout, 'for="id_duration_extra_minutes"')
        self.assertContains(checkout, 'for="id_plate"')
        self.assertContains(checkout, "Plaque d&#x27;immatriculation")
        self.assertContains(self.client.get(reverse("parking:signup")), "Modèle du véhicule (facultatif)")
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

        self.assertContains(response, "PAIEMENT SIMULÉ")
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
                "email": "alice@example.com",
                "password1": "A-valid-password-123!",
                "password2": "A-valid-password-123!",
                "phone_number": "06 12 34 56 78",
                "vehicle_model": "renault_clio",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("parking:parking_list"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertTrue(get_user_model().objects.filter(username="alice").exists())
        self.assertEqual(
            UserProfile.objects.get(user__username="alice").phone_number,
            "06 12 34 56 78",
        )
        self.assertEqual(
            UserProfile.objects.get(user__username="alice").vehicle_model,
            "renault_clio",
        )
        self.assertEqual(
            get_user_model().objects.get(username="alice").email,
            "alice@example.com",
        )
        self.assertContains(response, "message-success")
        self.assertContains(response, "Votre compte a été créé. Bienvenue !")

    def test_user_can_sign_up_without_choosing_vehicle_model(self):
        response = self.client.post(
            reverse("parking:signup"),
            {
                "username": "without-car-model",
                "email": "without-car@example.com",
                "password1": "A-valid-password-123!",
                "password2": "A-valid-password-123!",
                "vehicle_model": "",
            },
        )

        self.assertRedirects(response, reverse("parking:parking_list"))
        profile = UserProfile.objects.get(user__username="without-car-model")
        self.assertEqual(profile.vehicle_model, "")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_user_can_reset_password_from_email_link(self):
        user = get_user_model().objects.create_user(
            username="reset-user",
            email="reset@example.com",
            password="Old-password-123!",
        )

        response = self.client.post(
            reverse("parking:password_reset"),
            {"email": "reset@example.com"},
        )

        self.assertRedirects(response, reverse("parking:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        reset_path = re.search(r"http://testserver(\S+)", mail.outbox[0].body).group(1)
        confirm_page = self.client.get(reset_path, follow=True)
        self.assertEqual(confirm_page.status_code, 200)
        self.assertContains(confirm_page, "Choisir un nouveau mot de passe")

        response = self.client.post(
            confirm_page.request["PATH_INFO"],
            {
                "new_password1": "New-password-456!",
                "new_password2": "New-password-456!",
            },
        )

        self.assertRedirects(response, reverse("parking:password_reset_complete"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("New-password-456!"))

    def test_password_reset_rejects_an_unknown_email(self):
        response = self.client.post(
            reverse("parking:password_reset"),
            {"email": "unknown@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucun compte n’est associé à cette adresse e-mail.")
        self.assertEqual(len(mail.outbox), 0)

    def test_user_can_add_a_phone_number_to_their_account(self):
        self.authenticate_as_user()

        response = self.client.post(
            reverse("parking:account"),
            {"phone_number": "+33 6 12 34 56 78"},
            follow=True,
        )

        self.assertRedirects(response, reverse("parking:account"))
        profile = UserProfile.objects.get(user__username="parking-viewer")
        self.assertEqual(profile.phone_number, "+33 6 12 34 56 78")
        self.assertContains(response, "Votre profil a été mis à jour.")

    def test_account_rejects_invalid_phone_numbers(self):
        self.authenticate_as_user()

        response = self.client.post(
            reverse("parking:account"),
            {"phone_number": "telephone"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saisissez un numéro de téléphone valide.")

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
                "duration_minutes": "180",
                "card_number": "1234567890123456",
                "expiration_date": "12/30",
                "security_code": "123",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("parking:parking_detail", args=[self.parking.id]))
        self.assertContains(response, "message-success")
        self.assertContains(response, "Estimation du montant simulé : 7.50 €.")
        self.assertContains(response, "Référence de paiement :")
        reservation = Reservation.objects.get(plate="GG-789-GG")
        self.assertEqual(reservation.user, user)
        self.assertEqual(reservation.duration_minutes, 180)
        self.assertEqual(reservation.amount_paid, Decimal("7.50"))
        self.assertEqual(reservation.amount_charged, Decimal("7.50"))
        self.assertContains(response, str(reservation.payment_reference))

    def test_reservation_conflict_shows_a_user_facing_error(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        spot = self.parking.spots.get(number=2)

        response = self.client.post(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
            {
                "plate": "AA-123-AA",
                "duration_minutes": "60",
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
                "duration_minutes": "120",
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
                "duration_minutes": "60",
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
        self.assertContains(response, 'name="duration_minutes"')
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
            {"plate": "GG-789-GG", "duration_minutes": "60"},
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
                "duration_minutes": "60",
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
                "duration_minutes": "180",
                "card_number": "1234567890123456",
                "expiration_date": "12/30",
                "security_code": "123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La durée dépasse la limite de ce parking.")
        self.assertFalse(Reservation.objects.filter(plate="GG-789-GG").exists())

    def test_reservation_duration_can_be_selected_in_hours_or_days(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        cases = (
            ("AA-123-AA", "0", "2", "0", 120, Decimal("5.00"), self.parking.spots.get(number=1)),
            (
                "BB-234-BB",
                "1",
                "2",
                "30",
                1590,
                Decimal("66.25"),
                Spot.objects.create(parking=self.parking, number=3),
            ),
        )
        for plate, days, hours, minutes, expected_minutes, expected_amount, spot in cases:
            with self.subTest(duration=(days, hours, minutes)):
                response = self.client.post(
                    reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
                    {
                        "plate": plate,
                        "duration_days": days,
                        "duration_hours": hours,
                        "duration_extra_minutes": minutes,
                        "card_number": "1234567890123456",
                        "expiration_date": "12/30",
                        "security_code": "123",
                    },
                )
                self.assertEqual(response.status_code, 302)
                reservation = Reservation.objects.get(plate=plate)
                self.assertEqual(reservation.duration_minutes, expected_minutes)
                self.assertEqual(reservation.amount_paid, expected_amount)

    def test_composed_reservation_duration_is_checked_against_maximum_minutes(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.max_duration_minutes = 120
        self.parking.save()
        spot = self.parking.spots.get(number=1)

        response = self.client.post(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
            {
                "plate": "AA-123-AA",
                "duration_days": "0",
                "duration_hours": "3",
                "duration_extra_minutes": "0",
                "card_number": "1234567890123456",
                "expiration_date": "12/30",
                "security_code": "123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La durée dépasse la limite de ce parking.")
        self.assertFalse(Reservation.objects.exists())

    def test_checkout_hides_days_and_caps_hours_for_two_hour_parking(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.max_duration_minutes = 120
        self.parking.save()
        spot = self.parking.spots.get(number=1)

        response = self.client.get(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id])
        )

        self.assertNotContains(response, '<label for="id_duration_days">')
        self.assertContains(response, 'max="2"')
        self.assertContains(response, 'data-max-duration-minutes="120"')

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
            duration_minutes=120,
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
        self.assertContains(response, "data-duration-minutes=\"120\"")
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

    def test_agent_plate_check_confirms_duration_and_simulated_payment(self):
        agent = get_user_model().objects.create_user(
            username="duration-payment-agent",
            password="test-password",
        )
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        now = timezone.now()
        reservation = Reservation.objects.create(
            user=agent,
            spot=self.parking.spots.get(number=1),
            plate="AA-123-AA",
            duration_minutes=60,
            amount_paid=Decimal("2.50"),
            arrived_at=now - timedelta(minutes=30),
        )

        with patch("parking.views.timezone.now", return_value=now):
            response = self.client.get(
                reverse("parking:agent_plate_check"),
                {"plate": reservation.plate},
            )

        self.assertTrue(response.context["result"]["is_compliant"])
        self.assertEqual(response.context["result"]["duration_elapsed_minutes"], 30)
        self.assertTrue(response.context["result"]["payment_verified"])
        self.assertEqual(
            response.context["result"]["expected_payment_amount"],
            Decimal("2.50"),
        )
        self.assertContains(response, "Conforme — durée et paiement vérifiés")
        self.assertContains(response, "Paiement simulé vérifié")
        self.assertContains(response, "Montant attendu")
        self.assertContains(response, str(reservation.payment_reference))

    def test_agent_plate_check_flags_exceeded_duration_and_incorrect_payment(self):
        agent = get_user_model().objects.create_user(
            username="duration-payment-agent",
            password="test-password",
        )
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        now = timezone.now()

        exceeded = Reservation.objects.create(
            spot=self.parking.spots.get(number=1),
            plate="AA-123-AA",
            duration_minutes=60,
            amount_paid=Decimal("2.50"),
            arrived_at=now - timedelta(minutes=61),
        )
        underpaid = Reservation.objects.create(
            spot=Spot.objects.create(parking=self.parking, number=3),
            plate="BB-234-BB",
            duration_minutes=60,
            amount_paid=Decimal("1.00"),
            arrived_at=now - timedelta(minutes=30),
        )

        with patch("parking.views.timezone.now", return_value=now):
            exceeded_response = self.client.get(
                reverse("parking:agent_plate_check"),
                {"plate": exceeded.plate},
            )
            underpaid_response = self.client.get(
                reverse("parking:agent_plate_check"),
                {"plate": underpaid.plate},
            )

        self.assertFalse(exceeded_response.context["result"]["is_compliant"])
        self.assertTrue(exceeded_response.context["result"]["duration_exceeded"])
        self.assertTrue(exceeded_response.context["result"]["payment_verified"])
        self.assertContains(exceeded_response, "durée dépassée")
        self.assertContains(
            exceeded_response,
            "Non conforme — durée, paiement ou justificatif à vérifier",
        )
        self.assertFalse(underpaid_response.context["result"]["is_compliant"])
        self.assertFalse(underpaid_response.context["result"]["payment_verified"])
        self.assertContains(underpaid_response, "Paiement absent ou montant incorrect")

    def test_agent_plate_check_waits_for_arrival_before_duration_check(self):
        agent = get_user_model().objects.create_user(
            username="duration-payment-agent",
            password="test-password",
        )
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        reservation = Reservation.objects.create(
            spot=self.parking.spots.get(number=1),
            plate="AA-123-AA",
            duration_minutes=60,
            amount_paid=Decimal("2.50"),
        )

        response = self.client.get(
            reverse("parking:agent_plate_check"),
            {"plate": reservation.plate},
        )

        self.assertFalse(response.context["result"]["is_compliant"])
        self.assertIsNone(response.context["result"]["duration_elapsed_minutes"])
        self.assertTrue(response.context["result"]["payment_verified"])
        self.assertContains(response, "Contrôle incomplet — arrivée non confirmée")
        self.assertContains(response, "Décompte non commencé")

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
            {
                "plate": "AA-123-AA",
                "fine_type": "other",
                "reason": "Stationnement exceptionnel non prévu",
                "parking": str(self.parking.id),
                "amount": "75.00",
                "comment": "Panneau de signalisation visible",
            },
            follow=True,
        )

        self.assertRedirects(
            response,
            f"{reverse('parking:agent_plate_check')}?plate=AA-123-AA",
        )
        contravention = Contravention.objects.get()
        self.assertEqual(contravention.agent, agent)
        self.assertEqual(contravention.plate, "AA-123-AA")
        self.assertEqual(contravention.reason, "Stationnement exceptionnel non prévu")
        self.assertEqual(contravention.fine_type, Contravention.FineType.OTHER)
        self.assertEqual(contravention.parking, self.parking)
        self.assertEqual(contravention.amount, Decimal("75.00"))
        self.assertEqual(contravention.comment, "Panneau de signalisation visible")
        self.assertEqual(contravention.status, Contravention.Status.ISSUED)
        self.assertIsNotNone(contravention.number)
        self.assertContains(response, "La contravention a bien été créée.")

        history = self.client.get(reverse("parking:agent_contraventions"))
        self.assertContains(history, "Historique des contraventions")
        self.assertContains(history, "Stationnement exceptionnel non prévu")
        self.assertContains(history, self.parking.name)
        self.assertNotContains(history, "Latitude")
        self.assertNotContains(history, "Longitude")
        self.assertNotContains(history, "Utiliser ma position")
        self.assertContains(
            history,
            reverse("parking:agent_contravention_detail", args=[contravention.id]),
        )

        detail = self.client.get(
            reverse("parking:agent_contravention_detail", args=[contravention.id])
        )
        self.assertContains(detail, str(contravention.number))
        self.assertContains(detail, "75,00 €")
        self.assertContains(detail, "Panneau de signalisation visible")
        self.assertContains(detail, "<dt>Motif</dt>")
        self.assertNotContains(detail, "<dt>Type</dt>")

    def test_contravention_is_kept_and_creator_shown_after_switching_agents(self):
        agent1 = get_user_model().objects.create_user(
            username="agent1",
            password="test-password",
        )
        agent1.groups.add(Group.objects.create(name="Agents"))
        agent2 = get_user_model().objects.create_user(
            username="agent2",
            password="test-password",
        )
        agent2.groups.add(Group.objects.get(name="Agents"))
        self.client.force_login(agent1)

        response = self.client.post(
            reverse("parking:create_contravention"),
            {
                "plate": "AA-123-AA",
                "fine_type": "other",
                "reason": "Stationnement exceptionnel",
                "amount": "60.00",
                "parking": str(self.parking.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        contravention = Contravention.objects.get()
        self.assertEqual(contravention.agent, agent1)

        self.client.force_login(agent2)
        history_for_agent2 = self.client.get(reverse("parking:agent_contraventions"))
        self.assertContains(history_for_agent2, "Stationnement exceptionnel")
        self.assertContains(history_for_agent2, "agent1")
        detail_url = reverse(
            "parking:agent_contravention_detail",
            args=[contravention.id],
        )
        detail_for_agent2 = self.client.get(detail_url)
        self.assertContains(detail_for_agent2, "<dt>Agent</dt><dd>agent1</dd>")

        self.client.force_login(agent1)
        history_for_agent1 = self.client.get(reverse("parking:agent_contraventions"))
        self.assertContains(history_for_agent1, "Stationnement exceptionnel")
        self.assertContains(history_for_agent1, "agent1")

    def test_predefined_contravention_types_set_their_reason_and_amount(self):
        agent = get_user_model().objects.create_user(username="preset-agent", password="test-password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)
        presets = {
            "no_reservation": ("Stationnement sans réservation", Decimal("50.00")),
            "pmr_abuse": ("Usage abusif d’une place PMR", Decimal("135.00")),
            "overstay": ("Dépassement de la durée réservée", Decimal("35.00")),
            "wrong_spot": ("Stationnement sur une place non autorisée", Decimal("50.00")),
            "obstructing": ("Stationnement gênant ou bloquant", Decimal("75.00")),
            "no_payment": ("Paiement ou titre de stationnement absent", Decimal("50.00")),
        }

        for fine_type, (reason, amount) in presets.items():
            with self.subTest(fine_type=fine_type):
                response = self.client.post(
                    reverse("parking:create_contravention"),
                    {
                        "plate": "AA-123-AA",
                        "fine_type": fine_type,
                        "reason": "Tentative de modification du motif",
                        "amount": "30.00",
                        "parking": str(self.parking.id),
                    },
                )
                self.assertEqual(response.status_code, 302)
                contravention = Contravention.objects.latest("pk")
                self.assertEqual(contravention.fine_type, fine_type)
                self.assertEqual(contravention.reason, reason)
                self.assertEqual(contravention.amount, amount)

    def test_other_contravention_requires_a_custom_reason_and_amount(self):
        agent = get_user_model().objects.create_user(username="other-agent", password="test-password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)
        url = reverse("parking:create_contravention")

        self.client.post(
            url,
            {
                "plate": "AA-123-AA",
                "fine_type": "other",
                "parking": str(self.parking.id),
            },
        )
        self.assertFalse(Contravention.objects.exists())

        response = self.client.post(
            url,
            {
                "plate": "AA-123-AA",
                "fine_type": "other",
                "reason": "Motif détaillé",
                "amount": "80.00",
                "parking": str(self.parking.id),
            },
        )
        contravention = Contravention.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(contravention.reason, "Motif détaillé")
        self.assertEqual(contravention.amount, Decimal("80.00"))

    def test_other_contravention_rejects_blank_reason_and_out_of_range_amount(self):
        agent = get_user_model().objects.create_user(
            username="invalid-other-agent",
            password="test-password",
        )
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

        for reason, amount in (("   ", "80.00"), ("Motif renseigné", "201.00")):
            with self.subTest(reason=reason, amount=amount):
                self.client.post(
                    reverse("parking:create_contravention"),
                    {
                        "plate": "AA-123-AA",
                        "fine_type": "other",
                        "reason": reason,
                        "amount": amount,
                        "parking": str(self.parking.id),
                    },
                )

        self.assertFalse(Contravention.objects.exists())

    def test_agent_creation_rejects_unknown_type_invalid_plate_and_missing_parking(self):
        agent = get_user_model().objects.create_user(
            username="invalid-fine-agent",
            password="test-password",
        )
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)
        url = reverse("parking:create_contravention")
        valid_data = {
            "plate": "AA-123-AA",
            "fine_type": "no_reservation",
            "reason": "ignored for predefined type",
            "parking": str(self.parking.id),
        }

        invalid_requests = (
            {**valid_data, "fine_type": "unknown"},
            {**valid_data, "plate": "NOT-A-PLATE"},
            {**valid_data, "parking": ""},
        )
        for data in invalid_requests:
            with self.subTest(data=data):
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 302)

        self.assertFalse(Contravention.objects.exists())

    def test_contravention_amount_must_be_between_30_and_200_euros(self):
        agent = get_user_model().objects.create_user(username="fine-agent", password="test-password")
        agent.groups.add(Group.objects.create(name="Agents"))
        self.client.force_login(agent)

        for amount in ("29.99", "200.01"):
            with self.subTest(amount=amount):
                self.client.post(
                    reverse("parking:create_contravention"),
                    {
                        "plate": "AA-123-AA",
                        "fine_type": "other",
                        "reason": "Stationnement sans réservation",
                        "parking": str(self.parking.id),
                        "amount": amount,
                    },
                )
        self.assertFalse(Contravention.objects.exists())

    def test_pmr_spot_control_shows_justification_and_noncompliance(self):
        agent = get_user_model().objects.create_user(username="pmr-agent", password="test-password")
        agent.groups.add(Group.objects.create(name="Agents"))
        user = get_user_model().objects.create_user(username="pmr-driver", password="test-password")
        self.client.force_login(agent)
        spot = self.parking.spots.get(number=1)
        spot.is_pmr = True
        spot.save()
        Reservation.objects.create(
            user=user,
            spot=spot,
            plate="AA-123-AA",
        )

        response = self.client.get(
            reverse("parking:agent_plate_check"),
            {"plate": "AA-123-AA"},
        )

        self.assertContains(response, "Aucun justificatif — véhicule non conforme")

        UserProfile.objects.create(user=user, pmr_justification_registered=True)
        response = self.client.get(
            reverse("parking:agent_plate_check"),
            {"plate": "AA-123-AA"},
        )
        self.assertContains(response, "Justificatif PMR enregistré — à vérifier")
        self.assertNotContains(response, "Aucun justificatif — véhicule non conforme")

    def test_user_can_view_and_contest_their_contravention(self):
        user = get_user_model().objects.create_user(username="ticket-owner", password="test-password")
        agent = get_user_model().objects.create_user(username="ticket-agent", password="test-password")
        agent.groups.add(Group.objects.create(name="Agents"))
        Reservation.objects.create(
            user=user,
            spot=self.parking.spots.get(number=1),
            plate="AA-123-AA",
            status=Reservation.Status.COMPLETED,
            ended_at=timezone.now(),
        )
        self.client.force_login(agent)
        self.client.post(
            reverse("parking:create_contravention"),
            {
                "plate": "AA-123-AA",
                "fine_type": "no_reservation",
                "reason": "Stationnement sans réservation",
                "parking": str(self.parking.id),
            },
        )
        contravention = Contravention.objects.get()
        self.client.force_login(user)

        history = self.client.get(reverse("parking:user_contraventions"))
        self.assertContains(history, str(contravention.number))
        detail_url = reverse(
            "parking:user_contravention_detail",
            args=[contravention.id],
        )
        detail = self.client.get(detail_url)
        self.assertContains(detail, "Contester cet avis")
        self.assertContains(detail, "50,00 €")

        response = self.client.post(
            reverse("parking:contest_contravention", args=[contravention.id]),
            {"reason": "Le véhicule était autorisé à stationner."},
            follow=True,
        )
        contravention.refresh_from_db()
        self.assertEqual(contravention.status, Contravention.Status.CONTESTING)
        self.assertEqual(
            contravention.opposition_reason,
            "Le véhicule était autorisé à stationner.",
        )
        self.assertIsNotNone(contravention.opposition_submitted_at)
        self.assertContains(response, "En cours de contestation")
        self.assertContains(response, "Le véhicule était autorisé à stationner.")

    def test_user_cannot_view_another_users_contravention(self):
        owner = get_user_model().objects.create_user(username="ticket-owner", password="test-password")
        other_user = get_user_model().objects.create_user(username="other-driver", password="test-password")
        agent = get_user_model().objects.create_user(username="ticket-agent", password="test-password")
        contravention = Contravention.objects.create(
            agent=agent,
            user=owner,
            plate="AA-123-AA",
            reason="Stationnement interdit",
        )
        self.client.force_login(other_user)

        response = self.client.get(
            reverse("parking:user_contravention_detail", args=[contravention.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_user_contravention_list_contains_only_their_own_notices(self):
        owner = get_user_model().objects.create_user(
            username="notice-owner",
            password="test-password",
        )
        other_user = get_user_model().objects.create_user(
            username="other-notice-owner",
            password="test-password",
        )
        agent = get_user_model().objects.create_user(
            username="notice-agent",
            password="test-password",
        )
        own_notice = Contravention.objects.create(
            agent=agent,
            user=owner,
            plate="AA-123-AA",
            reason="Avis associé",
        )
        other_notice = Contravention.objects.create(
            agent=agent,
            user=other_user,
            plate="BB-234-BB",
            reason="Avis confidentiel",
        )
        self.client.force_login(owner)

        response = self.client.get(reverse("parking:user_contraventions"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(own_notice.number))
        self.assertNotContains(response, str(other_notice.number))
        self.assertNotContains(response, "Avis confidentiel")

    def test_agent_contravention_detail_requires_agent_group(self):
        agent = get_user_model().objects.create_user(
            username="detail-agent",
            password="test-password",
        )
        contravention = Contravention.objects.create(
            agent=agent,
            plate="AA-123-AA",
            reason="Avis réservé aux agents",
        )
        url = reverse(
            "parking:agent_contravention_detail",
            args=[contravention.id],
        )
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f"{reverse('parking:agent_login')}?next={url}",
            fetch_redirect_response=False,
        )

        user = get_user_model().objects.create_user(
            username="ordinary-user",
            password="test-password",
        )
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f"{reverse('parking:agent_login')}?next={url}",
            fetch_redirect_response=False,
        )

    def test_opposition_requires_reason_and_cannot_be_submitted_twice(self):
        user = get_user_model().objects.create_user(
            username="opposition-owner",
            password="test-password",
        )
        agent = get_user_model().objects.create_user(
            username="opposition-agent",
            password="test-password",
        )
        contravention = Contravention.objects.create(
            agent=agent,
            user=user,
            plate="AA-123-AA",
            reason="Stationnement interdit",
        )
        self.client.force_login(user)
        contest_url = reverse(
            "parking:contest_contravention",
            args=[contravention.id],
        )

        response = self.client.post(contest_url, {"reason": "   "}, follow=True)
        contravention.refresh_from_db()
        self.assertEqual(contravention.status, Contravention.Status.ISSUED)
        self.assertContains(response, "Saisissez le motif de votre opposition.")

        self.client.post(contest_url, {"reason": "Motif recevable"})
        response = self.client.post(
            contest_url,
            {"reason": "Motif différent"},
            follow=True,
        )
        contravention.refresh_from_db()
        self.assertEqual(contravention.status, Contravention.Status.CONTESTING)
        self.assertEqual(contravention.opposition_reason, "Motif recevable")
        self.assertContains(response, "déjà contesté")

    def test_opposition_is_rejected_after_30_days(self):
        user = get_user_model().objects.create_user(username="ticket-owner", password="test-password")
        agent = get_user_model().objects.create_user(username="ticket-agent", password="test-password")
        contravention = Contravention.objects.create(
            agent=agent,
            user=user,
            plate="AA-123-AA",
            reason="Stationnement interdit",
        )
        Contravention.objects.filter(pk=contravention.pk).update(
            created_at=timezone.now() - timedelta(days=31)
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("parking:contest_contravention", args=[contravention.id]),
            {"reason": "Je conteste."},
            follow=True,
        )

        contravention.refresh_from_db()
        self.assertEqual(contravention.status, Contravention.Status.ISSUED)
        self.assertContains(response, "Le délai d’opposition est dépassé")

    def test_non_agent_cannot_create_a_contravention(self):
        user = get_user_model().objects.create_user(username="alice", password="password")
        self.client.force_login(user)

        response = self.client.post(
            reverse("parking:create_contravention"),
            {
                "plate": "AA-123-AA",
                "fine_type": "no_reservation",
                "reason": "Motif",
                "parking": str(self.parking.id),
            },
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
            {
                "plate": "AA-123-AA",
                "fine_type": "no_reservation",
                "reason": "Motif",
                "parking": str(self.parking.id),
            },
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
        self.assertContains(response, "Les informations de la contravention sont invalides.")

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
        self.assertContains(response, 'name="parking"')
        self.assertContains(response, "Choisir un parking")
        self.assertNotContains(response, "Utiliser ma position")
        self.assertNotContains(response, "Latitude")
        self.assertNotContains(response, "Longitude")
        self.assertContains(response, "Choisir un type")
        self.assertContains(response, "Usage abusif d’une place PMR")
        self.assertContains(response, "fine-preset-preview")
        self.assertContains(response, "fine-amount-field")
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
        self.assertContains(response, 'href="/parkings/">')
        self.assertContains(response, "Trouver un parking")
        self.assertContains(response, 'href="#icon-search"')
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
        pmr_spot = self.parking.spots.get(number=1)
        pmr_spot.is_pmr = True
        pmr_spot.save()

        response = self.client.get(reverse("parking:parking_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="map"')
        self.assertContains(response, 'class="topbar"')
        self.assertContains(response, 'class="brand" href="/"')
        self.assertContains(response, "Parking Central")
        self.assertContains(response, 'id="parkings-data"')
        self.assertContains(response, "Voir sur la carte")
        self.assertContains(response, "const entry = parkingMarkers.get(button.dataset.parkingId)")
        self.assertContains(response, "map.panTo(marker.getPosition())")
        self.assertContains(response, "map.setZoom(15)")
        self.assertContains(response, 'google.maps.event.trigger(marker, "click")')
        self.assertContains(response, "Places PMR disponibles")
        self.assertContains(response, 'id="terrain-map-toggle"')
        self.assertContains(response, "Terrain")
        self.assertContains(response, "google.maps.ControlPosition.BOTTOM_LEFT")
        self.assertContains(response, "google.maps.MapTypeId.TERRAIN")
        self.assertContains(response, "available_pmr_spots_count")
        self.assertContains(response, "#176349")
        self.assertEqual(response.context["parking_data"][0]["available_pmr_spots_count"], 1)
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

    def test_pmr_spot_cannot_be_selected_without_profile_justification(self):
        self.authenticate_as_user()
        spot = self.parking.spots.get(number=1)
        spot.is_pmr = True
        spot.save()

        response = self.client.get(
            reverse("parking:parking_detail", args=[self.parking.id])
        )

        self.assertContains(response, "Place PMR")
        self.assertContains(response, "Réservation PMR indisponible")
        self.assertContains(response, "Vous ne disposez pas de Justificatif PMR")
        self.assertNotContains(
            response,
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
        )

    def test_pmr_spot_can_be_selected_with_profile_justification(self):
        self.authenticate_as_user()
        user = get_user_model().objects.get(username="parking-viewer")
        UserProfile.objects.create(user=user, pmr_justification_registered=True)
        spot = self.parking.spots.get(number=1)
        spot.is_pmr = True
        spot.save()

        response = self.client.get(
            reverse("parking:parking_detail", args=[self.parking.id])
        )

        self.assertContains(
            response,
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id]),
        )
        self.assertNotContains(response, "Réservation PMR indisponible")

    def test_direct_pmr_reservation_is_blocked_without_profile_justification(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        spot = self.parking.spots.get(number=1)
        spot.is_pmr = True
        spot.save()
        url = reverse("parking:reserve_spot", args=[self.parking.id, spot.id])

        response = self.client.get(url, follow=True)

        self.assertContains(
            response,
            "Vous ne disposez pas de Justificatif PMR",
        )
        self.assertFalse(Reservation.objects.exists())

    def test_direct_pmr_reservation_is_allowed_with_profile_justification(self):
        self.authenticate_as_user()
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        user = get_user_model().objects.get(username="parking-viewer")
        UserProfile.objects.create(user=user, pmr_justification_registered=True)
        spot = self.parking.spots.get(number=1)
        spot.is_pmr = True
        spot.save()

        response = self.client.get(
            reverse("parking:reserve_spot", args=[self.parking.id, spot.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirmer la réservation")

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
            self.assertContains(response, "PARKING KING")
            self.assertContains(response, 'class="brand-emblem"')
            self.assertContains(response, 'class="button-icon"')

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
        self.assertContains(
            response,
            f"{reverse('parking:agent_plate_check')}?plate=AB-123-CD",
        )

    def test_stats_contravention_links_to_full_details(self):
        contravention = Contravention.objects.create(
            agent=get_user_model().objects.get(username="agent"),
            plate="AB-123-CD",
            reason="Stationnement interdit",
            amount=Decimal("65.00"),
            comment="Signalisation présente",
            parking=self.parking,
        )

        response = self.client.get(reverse("parking:agent_stats"))

        detail_url = reverse(
            "parking:agent_contravention_detail",
            args=[contravention.id],
        )
        self.assertContains(response, detail_url)
        self.assertContains(response, "Voir le détail")
        self.assertContains(response, "65,00 €")
        self.assertContains(response, "agent")

        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, str(contravention.number))
        self.assertContains(detail, contravention.plate)
        self.assertContains(detail, contravention.reason)
        self.assertContains(detail, "65,00 €")
        local_created_at = timezone.localtime(contravention.created_at)
        self.assertContains(detail, local_created_at.strftime("%d/%m/%Y"))
        self.assertContains(detail, local_created_at.strftime("%H:%M"))
        self.assertContains(detail, contravention.comment)
        self.assertContains(detail, contravention.get_status_display())

    def test_agent_dashboard_alerts_per_parking_at_eighty_percent(self):
        Reservation.objects.create(spot=self.spot_1, plate="AB-123-CD")
        Reservation.objects.create(spot=self.spot_2, plate="EF-456-GH")

        response = self.client.get(reverse("parking:agent_dashboard"))

        self.assertContains(response, "Forte occupation (80 % ou plus)")
        self.assertContains(response, "Parking Gare : 2/2 places (100 %)")

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
        reservation_data = {
            "duration_minutes": 120,
            "amount_paid": Decimal("5.00"),
        }
        reservation_data.update(kwargs)
        reservation_data.setdefault(
            "amount_charged",
            reservation_data["amount_paid"] or Decimal("0.00"),
        )
        return Reservation.objects.create(
            user=self.user,
            spot=self.spot,
            plate="AB-123-CD",
            **reservation_data,
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

    def test_departure_recalculates_payment_from_actual_minutes(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        fixed_now = timezone.now()
        reservation = self.create_reservation(
            arrived_at=fixed_now - timedelta(minutes=30),
        )

        with patch("parking.views.timezone.now", return_value=fixed_now):
            response = self.client.post(
                reverse("parking:declare_departure", args=[reservation.id])
            )

        self.assertRedirects(response, reverse("parking:reservation_summary", args=[reservation.id]))
        reservation.refresh_from_db()
        self.assertEqual(reservation.actual_duration_display, "30 min")
        self.assertEqual(reservation.amount_paid, Decimal("1.25"))

    def test_reservation_reminds_user_fifteen_minutes_before_end(self):
        now = timezone.now()
        reservation = self.create_reservation(
            duration_minutes=120,
            arrived_at=now - timedelta(minutes=105),
        )

        response = self.client.get(reverse("parking:reservation_list"))

        self.assertContains(response, "Votre stationnement se termine dans moins de 15 minutes.")
        self.assertEqual(response.context["reservations"][0], reservation)

    def test_user_can_disable_stationing_reminders(self):
        reservation = self.create_reservation(
            duration_minutes=120,
            arrived_at=timezone.now() - timedelta(minutes=105),
        )
        UserProfile.objects.create(
            user=self.user,
            notifications_enabled=False,
        )

        response = self.client.get(reverse("parking:reservation_list"))

        self.assertFalse(response.context["reservations"][0].reminder_due)

    def test_user_can_extend_reservation_up_to_parking_limit(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.max_duration_minutes = 90
        self.parking.save()
        reservation = self.create_reservation(
            duration_minutes=60,
            arrived_at=timezone.now(),
            amount_paid=Decimal("2.50"),
        )

        response = self.client.post(
            reverse("parking:extend_reservation", args=[reservation.id]),
            {"extra_minutes": "30"},
            follow=True,
        )

        self.assertContains(response, "Stationnement prolongé de 30 minutes.")
        reservation.refresh_from_db()
        self.assertEqual(reservation.duration_minutes, 90)
        self.assertEqual(reservation.amount_paid, Decimal("3.75"))
        self.assertEqual(reservation.amount_charged, Decimal("3.75"))

        response = self.client.post(
            reverse("parking:extend_reservation", args=[reservation.id]),
            {"extra_minutes": "15"},
            follow=True,
        )
        self.assertContains(response, "La durée maximale autorisée")
        reservation.refresh_from_db()
        self.assertEqual(reservation.duration_minutes, 90)

    def test_user_can_choose_a_custom_extension_in_minutes(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        reservation = self.create_reservation(
            duration_minutes=20,
            arrived_at=timezone.now(),
            amount_paid=Decimal("0.83"),
        )

        response = self.client.post(
            reverse("parking:extend_reservation", args=[reservation.id]),
            {"extra_minutes": "17"},
            follow=True,
        )

        self.assertContains(response, "Stationnement prolongé de 17 minutes.")
        reservation.refresh_from_db()
        self.assertEqual(reservation.duration_minutes, 37)
        self.assertContains(response, 'type="number"')
        self.assertEqual(reservation.amount_paid, Decimal("1.54"))

    def test_user_can_extend_reservation_with_composed_duration(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        for plate, days, hours, minutes, expected_duration, expected_amount in (
            ("AB-123-CD", "0", "1", "0", 180, Decimal("7.50")),
            ("EF-456-GH", "1", "2", "30", 1710, Decimal("71.25")),
        ):
            with self.subTest(duration=(days, hours, minutes)):
                reservation = Reservation.objects.create(
                    user=self.user,
                    spot=Spot.objects.create(
                        parking=self.parking,
                        number=2 if plate == "AB-123-CD" else 3,
                    ),
                    plate=plate,
                    duration_minutes=120,
                    amount_paid=Decimal("5.00"),
                    amount_charged=Decimal("5.00"),
                    arrived_at=timezone.now(),
                )

                response = self.client.post(
                    reverse("parking:extend_reservation", args=[reservation.id]),
                    {
                        "extra_days": days,
                        "extra_hours": hours,
                        "extra_minutes": minutes,
                    },
                    follow=True,
                )

                self.assertContains(response, "Stationnement prolongé")
                reservation.refresh_from_db()
                self.assertEqual(reservation.duration_minutes, expected_duration)
                self.assertEqual(reservation.amount_paid, expected_amount)

    def test_departure_requires_confirmed_arrival(self):
        reservation = self.create_reservation()

        response = self.client.post(reverse("parking:declare_departure", args=[reservation.id]))

        self.assertEqual(response.status_code, 404)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.ACTIVE)

    def test_cancelling_before_arrival_refunds_the_simulated_amount(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        reservation = self.create_reservation(amount_paid=Decimal("5.00"))

        self.client.post(reverse("parking:cancel_reservation", args=[reservation.id]))

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, Reservation.Status.CANCELLED)
        self.assertEqual(reservation.amount_paid, Decimal("0.00"))
        self.assertEqual(reservation.amount_refunded, Decimal("5.00"))

        summary = self.client.get(
            reverse("parking:reservation_summary", args=[reservation.id])
        )
        self.assertContains(summary, "Montant remboursé")
        self.assertContains(summary, "5,00 €")
        self.assertContains(summary, "Remboursement calculé")
        self.assertContains(summary, "remboursés pour le temps non utilisé")

    def test_partial_refund_is_shown_in_the_reservation_summary(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        now = timezone.now()
        reservation = self.create_reservation(
            arrived_at=now - timedelta(minutes=2),
        )
        reservation.amount_paid = Decimal("2.50")
        reservation.amount_charged = Decimal("2.50")
        reservation.save(update_fields=["amount_paid", "amount_charged"])

        with patch("parking.views.timezone.now", return_value=now):
            self.client.post(
                reverse("parking:cancel_reservation", args=[reservation.id])
            )

        reservation.refresh_from_db()
        self.assertEqual(reservation.amount_refunded, Decimal("2.42"))
        self.assertEqual(reservation.amount_paid, Decimal("0.08"))
        self.assertEqual(reservation.amount_charged, Decimal("2.50"))
        summary = self.client.get(
            reverse("parking:reservation_summary", args=[reservation.id])
        )
        self.assertContains(summary, "Montant remboursé")
        self.assertContains(summary, "2,42 €")
        self.assertContains(summary, "Montant initialement payé")
        self.assertContains(summary, "2,50 €")
        self.assertContains(summary, "Remboursement calculé")

    def test_sixteen_minute_use_keeps_initial_charge_and_refunds_unused_time(self):
        self.parking.hourly_rate = Decimal("2.50")
        self.parking.save()
        now = timezone.now()
        reservation = self.create_reservation(
            duration_minutes=60,
            amount_paid=Decimal("2.50"),
            amount_charged=Decimal("2.50"),
            arrived_at=now - timedelta(minutes=15),
        )

        with patch("parking.views.timezone.now", return_value=now):
            self.client.post(reverse("parking:declare_departure", args=[reservation.id]))

        reservation.refresh_from_db()
        self.assertEqual(reservation.amount_charged, Decimal("2.50"))
        self.assertEqual(reservation.amount_paid, Decimal("0.63"))
        self.assertEqual(reservation.amount_refunded, Decimal("1.87"))

        summary = self.client.get(
            reverse("parking:reservation_summary", args=[reservation.id])
        )
        self.assertContains(summary, "Montant initialement payé")
        self.assertContains(summary, "2,50 €")
        self.assertContains(summary, "0,63 €")
        self.assertContains(summary, "1,87 €")

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
            duration_minutes=120,
            amount_paid=Decimal("5.00"),
            arrived_at=timezone.now(),
        )
        completed.status = Reservation.Status.COMPLETED
        completed.ended_at = timezone.now()
        completed.save()

        response = self.client.get(reverse("parking:reservation_list"))

        self.assertContains(response, "Annulée")
        self.assertContains(response, "Terminée")
        self.assertContains(response, 'class="reservation-status reservation-status--cancelled"')
        self.assertContains(response, 'class="reservation-status reservation-status--completed"')
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
        self.assertContains(response, "65 min")
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
                    "duration_minutes": "60",
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

    def test_agent_contravention_creation_requires_csrf_token(self):
        self.client.force_login(self.agent)

        response = self.client.post(
            reverse("parking:create_contravention"),
            {
                "plate": "AA-123-AA",
                "fine_type": "other",
                "reason": "Stationnement interdit",
                "amount": "50.00",
                "parking": str(self.parking.id),
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Contravention.objects.exists())

    def test_contravention_opposition_requires_csrf_token(self):
        contravention = Contravention.objects.create(
            agent=self.agent,
            user=self.user,
            plate="AA-123-AA",
            reason="Stationnement interdit",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "parking:contest_contravention",
                args=[contravention.id],
            ),
            {"reason": "Je souhaite contester cet avis."},
        )

        self.assertEqual(response.status_code, 403)
        contravention.refresh_from_db()
        self.assertEqual(contravention.status, Contravention.Status.ISSUED)
        self.assertEqual(contravention.opposition_reason, "")
