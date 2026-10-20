from django.contrib.auth import views as auth_views
from django.urls import path, register_converter

from . import views


class DatabaseIdConverter:
    regex = r"[0-9]{1,19}"

    def to_python(self, value):
        value = int(value)
        if value > 9223372036854775807:
            raise ValueError
        return value

    def to_url(self, value):
        return str(value)


register_converter(DatabaseIdConverter, "dbid")

app_name = "parking"

urlpatterns = [
    path("", views.home, name="home"),
    path("inscription/", views.signup, name="signup"),
    path(
        "connexion/",
        auth_views.LoginView.as_view(
            template_name="parking/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("moyens-de-paiement/", views.payment_methods, name="payment_methods"),
    path("parkings/", views.parking_list, name="parking_list"),
    path("parkings/<dbid:parking_id>/", views.parking_detail, name="parking_detail"),
    path("mes-reservations/", views.reservation_list, name="reservation_list"),
    path(
        "mes-reservations/<dbid:reservation_id>/confirmer-arrivee/",
        views.confirm_arrival,
        name="confirm_arrival",
    ),
    path(
        "mes-reservations/<dbid:reservation_id>/annuler/",
        views.cancel_reservation,
        name="cancel_reservation",
    ),
    path(
        "mes-reservations/<dbid:reservation_id>/depart/",
        views.declare_departure,
        name="declare_departure",
    ),
    path(
        "mes-reservations/<dbid:reservation_id>/",
        views.reservation_summary,
        name="reservation_summary",
    ),
    path(
        "parkings/<dbid:parking_id>/places/<dbid:spot_id>/reserver/",
        views.reserve_spot,
        name="reserve_spot",
    ),
    path("agent/login/", views.agent_login, name="agent_login"),
    path("agent/logout/", views.agent_logout, name="agent_logout"),
    path("agent/", views.agent_dashboard, name="agent_dashboard"),
    path("agent/plaque/", views.agent_plate_check, name="agent_plate_check"),
    path(
        "agent/contraventions/creer/",
        views.create_contravention,
        name="create_contravention",
    ),
    path(
        "agent/reservations/<dbid:reservation_id>/terminer/",
        views.agent_end_reservation,
        name="agent_end_reservation",
    ),
    path("agent/statistiques/", views.agent_stats, name="agent_stats"),
    path("agent/affluence/", views.agent_affluence, name="agent_affluence"),
    path("acces-professionnel/", views.professional_login,name="professional_login"),
]
