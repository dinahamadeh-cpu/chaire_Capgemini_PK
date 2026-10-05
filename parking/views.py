from django.shortcuts import get_object_or_404, render  # type: ignore[reportMissingImports]
from django.conf import settings  # type: ignore[reportMissingImports]
from .models import Parking 

def parking_list(request):
    parkings = Parking.objects.all()

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

    return render(
        request,
        "parking/parking_details.html",
        {
            "parking": parking,
            "available_spots": available_spots,
        },
    )