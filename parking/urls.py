from django.urls import path

from . import views

app_name = "parking"

urlpatterns = [
    path("", views.home, name="home"),
    path("agent/login/", views.agent_login, name="agent_login"),
    path("agent/logout/", views.agent_logout, name="agent_logout"),
    path("agent/", views.agent_dashboard, name="agent_dashboard"),
    path("agent/plaque/", views.agent_plate_check, name="agent_plate_check"),
    path("agent/statistiques/", views.agent_stats, name="agent_stats"),
]
