from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, render  # type: ignore[reportMissingImports]
from django.shortcuts import redirect
from django.conf import settings  # type: ignore[reportMissingImports]
from django.db.models import Count, Q

from .models import Parking 


def home(request):
    return render(request, "parking/home.html")


def signup(request):
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("parking:parking_list")
    return render(request, "parking/signup.html", {"form": form})


def parking_list(request):
    parkings = Parking.objects.annotate(
        total_spots_count=Count("spots"),
        available_spots_count=Count("spots", filter=Q(spots__is_available=True)),
    )

    parking_data = list(
        parkings.values(
            "id",
            "name",
            "address",
            "latitude",
            "longitude",
        )
    )

    return render(
        request,
        "parking/parking_list.html",
        {
            "parkings": parkings,
            "parking_data": parking_data,
            "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
        },
    )

def parking_detail(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)
    available_spots = parking.spots.filter(is_available=True)
    total_spots = parking.spots.count()

    return render(
        request,
        "parking/parking_details.html",
        {
            "parking": parking,
            "available_spots": available_spots,
            "total_spots": total_spots,
        },
    )
