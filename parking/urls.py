from django.contrib.auth import views as auth_views
from django.urls import path # type: ignore 

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
]
