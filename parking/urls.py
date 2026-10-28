from django.contrib.auth import views as auth_views
from django.urls import path, register_converter, reverse_lazy

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
    path(
        "mot-de-passe-oublie/",
        auth_views.PasswordResetView.as_view(
            template_name="parking/password_reset_form.html",
            email_template_name="parking/password_reset_email.txt",
            subject_template_name="parking/password_reset_subject.txt",
            form_class=views.AccountPasswordResetForm,
            success_url=reverse_lazy("parking:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "mot-de-passe-oublie/envoye/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="parking/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "reinitialiser-mot-de-passe/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="parking/password_reset_confirm.html",
            success_url=reverse_lazy("parking:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "mot-de-passe-reinitialise/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="parking/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("mon-compte/", views.account, name="account"),
    path("parametres/", views.account, name="settings"),
    path("parametres/supprimer-compte/", views.delete_account, name="delete_account"),
    path(
        "parametres/mot-de-passe/",
        auth_views.PasswordChangeView.as_view(
            template_name="parking/password_change_form.html",
            success_url=reverse_lazy("parking:settings"),
        ),
        name="password_change",
    ),
    path("mes-contraventions/", views.user_contraventions, name="user_contraventions"),
    path(
        "mes-contraventions/<dbid:contravention_id>/",
        views.user_contravention_detail,
        name="user_contravention_detail",
    ),
    path(
        "mes-contraventions/<dbid:contravention_id>/contester/",
        views.contest_contravention,
        name="contest_contravention",
    ),
    path("moyens-de-paiement/", views.payment_methods, name="payment_methods"),
    path("parkings/", views.parking_list, name="parking_list"),
    path("parkings/<dbid:parking_id>/", views.parking_detail, name="parking_detail"),
    path("mes-reservations/", views.reservation_list, name="reservation_list"),
    path(
        "mes-reservations/<dbid:reservation_id>/prolonger/",
        views.extend_reservation,
        name="extend_reservation",
    ),
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
        "agent/contraventions/",
        views.agent_contraventions,
        name="agent_contraventions",
    ),
    path(
        "agent/contraventions/creer/",
        views.create_contravention,
        name="create_contravention",
    ),
    path(
        "agent/contraventions/<dbid:contravention_id>/",
        views.agent_contravention_detail,
        name="agent_contravention_detail",
    ),
    path(
        "agent/reservations/<dbid:reservation_id>/terminer/",
        views.agent_end_reservation,
        name="agent_end_reservation",
    ),
    path("agent/statistiques/", views.agent_stats, name="agent_stats"),
    path("agent/affluence/", views.agent_affluence, name="agent_affluence"),
    path("acces-professionnel/", views.professional_login,name="professional_login"),
    path("parkings/<int:parking_id>/favori/", views.toggle_favorite, name="toggle_favorite"),
    path("mes-favoris/", views.favorite_list, name="favorite_list"),
]
