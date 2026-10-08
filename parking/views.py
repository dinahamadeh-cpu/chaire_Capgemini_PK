from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ReservationForm
from .models import Parking, Reservation, Spot


def home(request):
    return render(request, "parking/home.html")


def signup(request):
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("parking:parking_list")
    return render(request, "parking/signup.html", {"form": form})


def _is_agent(user):
    return user.is_authenticated and user.groups.filter(name="Agents").exists()


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


@login_required(login_url="parking:login")
def reserve_spot(request, parking_id, spot_id):
    if request.method != "POST":
        return redirect("parking:parking_detail", parking_id=parking_id)

    spot = get_object_or_404(Spot, pk=spot_id, parking_id=parking_id)
    form = ReservationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "La plaque doit respecter le format AA-123-AA.")
        return redirect("parking:parking_detail", parking_id=parking_id)

    try:
        Reservation.objects.create(
            user=request.user,
            spot=spot,
            plate=form.cleaned_data["plate"],
        )
    except IntegrityError:
        messages.error(request, "Cette place ou cette plaque est déjà réservée.")
    else:
        messages.success(request, "La place a bien été réservée.")

    return redirect("parking:parking_detail", parking_id=parking_id)


@login_required(login_url="parking:login")
def reservation_list(request):
    reservations = (
        Reservation.objects.filter(user=request.user)
        .select_related("spot", "spot__parking")
        .order_by("-created_at")
    )
    return render(
        request,
        "parking/reservation_list.html",
        {"reservations": reservations},
    )


@login_required(login_url="parking:login")
def cancel_reservation(request, reservation_id):
    if request.method != "POST":
        return redirect("parking:reservation_list")

    reservation = get_object_or_404(
        Reservation,
        pk=reservation_id,
        user=request.user,
        status=Reservation.Status.ACTIVE,
    )
    reservation.status = Reservation.Status.CANCELLED
    reservation.ended_at = timezone.now()
    reservation.save()
    messages.success(request, "La réservation a bien été annulée.")
    return redirect("parking:reservation_list")


def agent_login(request):
    error = None
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None and _is_agent(user):
            login(request, user)
            return redirect("parking:agent_dashboard")
        error = "Identifiants invalides, ou ce compte n'est pas un compte agent."
    return render(request, "parking/agent_login.html", {"error": error})


def agent_logout(request):
    logout(request)
    return redirect("parking:home")


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_dashboard(request):
    return render(request, "parking/agent_dashboard.html")


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_plate_check(request):
    plate = request.GET.get("plate", "").strip().upper()
    result = None
    if plate:
        reservation = (
            Reservation.objects.filter(plate=plate, status=Reservation.Status.ACTIVE)
            .select_related("spot", "spot__parking")
            .first()
        )
        result = {"plate": plate, "reservation": reservation}
    return render(request, "parking/agent_plate_check.html", {"plate": plate, "result": result})


@user_passes_test(_is_agent, login_url="parking:agent_login")
@require_POST
def agent_end_reservation(request, reservation_id):
    reservation = get_object_or_404(
        Reservation,
        pk=reservation_id,
        status=Reservation.Status.ACTIVE,
    )
    reservation.status = Reservation.Status.COMPLETED
    reservation.ended_at = timezone.now()
    reservation.save()
    messages.success(request, "Le stationnement a bien été clôturé.")
    return redirect(f"{reverse('parking:agent_plate_check')}?plate={reservation.plate}")


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_stats(request):
    history = []
    for parking in Parking.objects.prefetch_related("spots__reservations").all():
        events = []
        for spot in parking.spots.all():
            for reservation in spot.reservations.all():
                events.append((reservation.created_at, 1))
                if reservation.ended_at:
                    events.append((reservation.ended_at, -1))
        events.sort(key=lambda event: event[0])

        total_spots = parking.spots.count()
        occupied = 0
        timeline = []
        for timestamp, delta in events:
            occupied += delta
            timeline.append({"timestamp": timestamp, "occupied": occupied, "total": total_spots})

        history.append(
            {
                "parking": parking,
                "total_spots": total_spots,
                "current_occupied": occupied,
                "timeline": timeline,
            }
        )
    return render(request, "parking/agent_stats.html", {"history": history})
