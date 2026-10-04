from django.urls import path # type: ignore 

from . import views


app_name = "parking"

urlpatterns = [
    path("", views.parking_list, name="parking_list"),
    path("<int:parking_id>/", views.parking_detail, name="parking_detail"),
]