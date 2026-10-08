from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


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
    path("parkings/", views.parking_list, name="parking_list"),
    path("parkings/<int:parking_id>/", views.parking_detail, name="parking_detail"),
    path("mes-reservations/", views.reservation_list, name="reservation_list"),
    path(
        "mes-reservations/<int:reservation_id>/annuler/",
        views.cancel_reservation,
        name="cancel_reservation",
    ),
    path(
        "parkings/<int:parking_id>/places/<int:spot_id>/reserver/",
        views.reserve_spot,
        name="reserve_spot",
    ),
    path("agent/login/", views.agent_login, name="agent_login"),
    path("agent/logout/", views.agent_logout, name="agent_logout"),
    path("agent/", views.agent_dashboard, name="agent_dashboard"),
    path("agent/plaque/", views.agent_plate_check, name="agent_plate_check"),
    path("agent/statistiques/", views.agent_stats, name="agent_stats"),
]
