from django.shortcuts import get_object_or_404, render  # type: ignore[reportMissingImports]
from .models import Parking 

def parking_list(request):
    parkings = Parking.objects.all()
    return render(request, 'parking/parking_list.html', {'parkings': parkings})

def parking_detail(request, parking_id):
    parking = get_object_or_404(Parking, id=parking_id)
    available_spots = parking.spots.filter(is_available=True)

    return render(
        request,
        "parking/parking_detail.html",
        {
            "parking": parking,
            "available_spots": available_spots,
        },
    )