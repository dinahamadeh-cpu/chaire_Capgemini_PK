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
    path("mes-vehicules/", views.user_vehicles, name="user_vehicles"),
    path(
        "mes-habitudes-de-reservation/",
        views.recurring_reservation_plans,
        name="recurring_reservation_plans",
    ),
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
    path("mes-depenses/", views.user_financial_history, name="user_financial_history"),
    path("mon-historique/", views.user_history, name="user_history"),
    path("mes-notifications/", views.user_notifications, name="user_notifications"),
    path(
        "mes-notifications/<dbid:notification_id>/consulter/",
        views.consult_user_notification,
        name="consult_user_notification",
    ),
    path("signaler-un-probleme/", views.submit_parking_report, name="submit_parking_report"),
    path("mes-signalements/", views.user_parking_reports, name="user_parking_reports"),
    path(
        "mes-signalements/<dbid:report_id>/",
        views.user_parking_report_detail,
        name="user_parking_report_detail",
    ),
    path(
        "mes-signalements/<dbid:report_id>/photo/",
        views.parking_report_photo,
        name="parking_report_photo",
    ),
    path("administration/tableau-de-bord/", views.admin_dashboard, name="admin_dashboard"),
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
    path(
        "mes-contraventions/<dbid:contravention_id>/payer/",
        views.pay_contravention,
        name="pay_contravention",
    ),
    path("moyens-de-paiement/", views.payment_methods, name="payment_methods"),
    path("parkings/", views.parking_list, name="parking_list"),
    path("parkings/comparer/", views.compare_parkings, name="compare_parkings"),
    path(
        "parkings/disponibilite/",
        views.parking_availability,
        name="parking_availability",
    ),
    path("parkings/<dbid:parking_id>/", views.parking_detail, name="parking_detail"),
    path(
        "parkings/<dbid:parking_id>/disponibilite/",
        views.parking_detail_availability,
        name="parking_detail_availability",
    ),
    path(
        "parkings/<dbid:parking_id>/liste-attente/",
        views.toggle_waitlist,
        name="toggle_waitlist",
    ),
    path("mes-reservations/", views.reservation_list, name="reservation_list"),
    path(
        "mes-reservations/<dbid:reservation_id>/qr/",
        views.reservation_qr,
        name="reservation_qr",
    ),
    path(
        "mes-reservations/<dbid:reservation_id>/qr/donnees/",
        views.reservation_qr_data,
        name="reservation_qr_data",
    ),
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
        "mes-reservations/<dbid:reservation_id>/signaler-retard/",
        views.report_late_arrival,
        name="report_late_arrival",
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
        "mes-reservations/<dbid:reservation_id>/avis/",
        views.submit_parking_review,
        name="submit_parking_review",
    ),
    path(
        "parkings/<dbid:parking_id>/places/<dbid:spot_id>/reserver/",
        views.reserve_spot,
        name="reserve_spot",
    ),
    path("agent/login/", views.agent_login, name="agent_login"),
    path("agent/logout/", views.agent_logout, name="agent_logout"),
    path("agent/", views.agent_dashboard, name="agent_dashboard"),
    path(
        "agent/signalements/",
        views.agent_parking_reports,
        name="agent_parking_reports",
    ),
    path(
        "agent/places-indisponibles/",
        views.agent_spot_closures,
        name="agent_spot_closures",
    ),
    path(
        "agent/places-indisponibles/<dbid:closure_id>/terminer/",
        views.agent_end_spot_closure,
        name="agent_end_spot_closure",
    ),
    path(
        "agent/historique-actions/",
        views.agent_action_history,
        name="agent_action_history",
    ),
    path(
        "agent/signalements/<dbid:report_id>/",
        views.agent_parking_report_detail,
        name="agent_parking_report_detail",
    ),
    path(
        "agent/qr/<str:token>/",
        views.agent_qr_verify,
        name="agent_qr_verify",
    ),
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
        "agent/contraventions/<dbid:contravention_id>/photo/",
        views.agent_contravention_photo,
        name="agent_contravention_photo",
    ),
    path(
        "agent/reservations/<dbid:reservation_id>/terminer/",
        views.agent_end_reservation,
        name="agent_end_reservation",
    ),
    path(
        "agent/reservations/<dbid:reservation_id>/refuser/",
        views.agent_refuse_reservation,
        name="agent_refuse_reservation",
    ),
    path("agent/statistiques/", views.agent_stats, name="agent_stats"),
    path("agent/affluence/", views.agent_affluence, name="agent_affluence"),
    path("acces-professionnel/", views.professional_login,name="professional_login"),
    path("parkings/<int:parking_id>/favori/", views.toggle_favorite, name="toggle_favorite"),
    path("mes-favoris/", views.favorite_list, name="favorite_list"),
    path(
        "mes-favoris/<dbid:parking_id>/alerte/",
        views.set_favorite_availability_alert,
        name="set_favorite_availability_alert",
    ),
]
