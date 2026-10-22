from datetime import datetime, time, timedelta

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import ContraventionForm, PaymentDetailsForm, ReservationForm, ParkingFilterForm
from .models import Contravention, DemoPaymentMethod, Parking, Reservation, Spot, Favorite, plate_validator

STATS_MOVEMENTS_LIMIT = 20
HISTORY_PERIODS = ["7", "30", "90"]
WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def home(request):
    return render(request, "parking/home.html")


@require_http_methods(["GET", "POST"])
def signup(request):
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Votre compte a été créé. Bienvenue !")
        return redirect("parking:parking_list")
    return render(request, "parking/signup.html", {"form": form})


def _is_agent(user):
    return user.is_authenticated and user.groups.filter(name="Agents").exists()

@login_required(login_url="parking:login")
@require_POST
def toggle_favorite(request, parking_id):
    parking = get_object_or_404(Parking, pk=parking_id)

    favorite, created = Favorite.objects.get_or_create(
        user=request.user,
        parking=parking,
    )

    if created:
        messages.success(
            request,
            f"{parking.name} a été ajouté à vos favoris.",
        )
    else:
        favorite.delete()
        messages.success(
            request,
            f"{parking.name} a été retiré de vos favoris.",
        )

    return redirect("parking:parking_list")

@login_required(login_url="parking:login")
def favorite_list(request):
    favorites = (
        Favorite.objects.filter(user=request.user)
        .select_related("parking")
        .annotate(
            total_spots_count=Count("parking__spots"),
            available_spots_count=Count(
                "parking__spots",
                filter=Q(parking__spots__is_available=True),
            ),
        )
    )

    return render(
        request,
        "parking/favorite_list.html",
        {"favorites": favorites},
    )

@login_required(login_url="parking:login")
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
            "parking_data": {
                "name": parking.name,
                "address": parking.address,
                "latitude": parking.latitude,
                "longitude": parking.longitude,
            },
        },
    )


@login_required(login_url="parking:login")
@require_http_methods(["GET", "POST"])
def payment_methods(request):
    payment_method = DemoPaymentMethod.objects.filter(user=request.user).first()

    if request.method == "POST":
        form = PaymentDetailsForm(request.POST)
        if form.is_valid():
            DemoPaymentMethod.objects.get_or_create(user=request.user)
            messages.success(
                request,
                "Moyen de paiement simulé enregistré. "
                "Les informations de carte ne sont pas conservées.",
            )
            return redirect("parking:payment_methods")
        form_errors = [
            f"{form.fields[field].label or field} : {error}"
            for field, errors in form.errors.items()
            for error in errors
        ]
        form = PaymentDetailsForm()
    else:
        form = PaymentDetailsForm()
        form_errors = []

    return render(
        request,
        "parking/payment_methods.html",
        {
            "payment_method": payment_method,
            "form": form,
            "form_errors": form_errors,
        },
    )


@login_required(login_url="parking:login")
@require_http_methods(["GET", "POST"])
def reserve_spot(request, parking_id, spot_id):
    spot = get_object_or_404(Spot, pk=spot_id, parking_id=parking_id)
    if spot.parking.hourly_rate is None:
        messages.error(
            request,
            "La réservation est impossible : le tarif de ce parking n'est pas renseigné.",
        )
        return redirect("parking:parking_detail", parking_id=parking_id)

    if not spot.is_available:
        messages.error(request, "Cette place n'est plus disponible.")
        return redirect("parking:parking_detail", parking_id=parking_id)

    saved_payment_method = DemoPaymentMethod.objects.filter(user=request.user).exists()
    rate_cents = int(spot.parking.hourly_rate * 100)

    if request.method == "GET":
        form = ReservationForm(
            has_saved_payment_method=saved_payment_method,
            max_duration_minutes=spot.parking.max_duration_minutes,
        )
        return render(
            request,
            "parking/reservation_checkout.html",
            {
                "parking": spot.parking,
                "spot": spot,
                "form": form,
                "has_saved_payment_method": saved_payment_method,
                "rate_cents": rate_cents,
            },
        )

    if request.method != "POST":
        return redirect("parking:parking_detail", parking_id=parking_id)

    form = ReservationForm(
        request.POST,
        has_saved_payment_method=saved_payment_method,
        max_duration_minutes=spot.parking.max_duration_minutes,
    )
    if not form.is_valid():
        form_errors = [
            f"{form.fields[field].label or field} : {error}"
            for field, errors in form.errors.items()
            for error in errors
        ]
        safe_form = ReservationForm(
            has_saved_payment_method=saved_payment_method,
            max_duration_minutes=spot.parking.max_duration_minutes,
            initial={
                "duration_hours": request.POST.get("duration_hours", ""),
                "plate": request.POST.get("plate", ""),
                "payment_method": request.POST.get("payment_method", ""),
            },
        )
        return render(
            request,
            "parking/reservation_checkout.html",
            {
                "parking": spot.parking,
                "spot": spot,
                "form": safe_form,
                "form_errors": form_errors,
                "has_saved_payment_method": saved_payment_method,
                "rate_cents": rate_cents,
            },
        )

    amount_paid = spot.parking.hourly_rate * form.cleaned_data["duration_hours"]
    try:
        with transaction.atomic():
            Reservation.objects.create(
                user=request.user,
                spot=spot,
                plate=form.cleaned_data["plate"],
                duration_hours=form.cleaned_data["duration_hours"],
                amount_paid=amount_paid,
            )
    except IntegrityError:
        messages.error(
            request,
            "Une réservation utilise déjà cette place ou cette plaque. Vérifiez vos réservations.",
        )
    else:
        messages.success(
            request,
            f"Paiement simulé de {amount_paid:.2f} € confirmé. "
            "La place a bien été réservée. Aucune donnée de carte n'a été enregistrée.",
        )

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
@require_POST
def confirm_arrival(request, reservation_id):
    reservation = get_object_or_404(
        Reservation,
        pk=reservation_id,
        user=request.user,
        status=Reservation.Status.ACTIVE,
    )
    arrival_recorded = Reservation.objects.filter(
        pk=reservation.pk,
        arrived_at__isnull=True,
    ).update(arrived_at=timezone.now())

    if arrival_recorded:
        messages.success(request, "Votre arrivée est confirmée. Le décompte du stationnement commence.")
    else:
        messages.info(request, "Votre arrivée avait déjà été confirmée.")

    return redirect("parking:reservation_list")


@login_required(login_url="parking:login")
@require_POST
def cancel_reservation(request, reservation_id):
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


@login_required(login_url="parking:login")
@require_POST
def declare_departure(request, reservation_id):
    reservation = get_object_or_404(
        Reservation,
        pk=reservation_id,
        user=request.user,
        status=Reservation.Status.ACTIVE,
        arrived_at__isnull=False,
    )
    reservation.status = Reservation.Status.COMPLETED
    reservation.ended_at = timezone.now()
    reservation.save()
    messages.success(request, "Votre départ est enregistré. Voici le récapitulatif de votre stationnement.")
    return redirect("parking:reservation_summary", reservation_id=reservation.id)


@login_required(login_url="parking:login")
def reservation_summary(request, reservation_id):
    reservation = get_object_or_404(
        Reservation.objects.select_related("spot", "spot__parking"),
        pk=reservation_id,
        user=request.user,
    )
    return render(request, "parking/reservation_summary.html", {"reservation": reservation})

def professional_login(request):
    return render(request, "parking/professional_login.html")

@require_http_methods(["GET", "POST"])
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


@require_POST
def agent_logout(request):
    logout(request)
    return redirect("parking:home")


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_dashboard(request):
    total_spots = Spot.objects.count()
    occupied = Reservation.objects.filter(status=Reservation.Status.ACTIVE).count()
    return render(
        request,
        "parking/agent_dashboard.html",
        {
            "occupied": occupied,
            "total_spots": total_spots,
            "occupancy_rate": round(occupied * 100 / total_spots) if total_spots else None,
        },
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_plate_check(request):
    plate = request.GET.get("plate", "").strip().upper()
    try:
        if not plate or len(plate) > 9:
            raise ValidationError("Plaque invalide")
        plate_validator(plate)
    except ValidationError:
        plate = ""
    result = None
    if plate:
        reservation = (
            Reservation.objects.filter(plate=plate, status=Reservation.Status.ACTIVE)
            .select_related("spot", "spot__parking")
            .first()
        )
        result = {"plate": plate, "reservation": reservation}
    contravention_form = None
    if result and result["reservation"] is None:
        contravention_form = ContraventionForm(initial={"plate": plate})
    return render(
        request,
        "parking/agent_plate_check.html",
        {"plate": plate, "result": result, "contravention_form": contravention_form},
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
@require_POST
def create_contravention(request):
    form = ContraventionForm(request.POST)
    plate = request.POST.get("plate", "").strip().upper()
    if not form.is_valid():
        messages.error(request, "La plaque et le motif sont invalides.")
        return redirect(f"{reverse('parking:agent_plate_check')}?plate={plate}")

    plate = form.cleaned_data["plate"]
    if Reservation.objects.filter(
        plate=plate,
        status=Reservation.Status.ACTIVE,
    ).exists():
        messages.error(request, "Ce véhicule possède une réservation active.")
        return redirect(f"{reverse('parking:agent_plate_check')}?plate={plate}")

    Contravention.objects.create(
        agent=request.user,
        plate=plate,
        reason=form.cleaned_data["reason"],
    )
    messages.success(request, "La contravention a bien été créée.")
    return redirect(f"{reverse('parking:agent_plate_check')}?plate={plate}")


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
    end_labels = {
        Reservation.Status.COMPLETED: "Départ",
        Reservation.Status.CANCELLED: "Annulation",
    }
    stats = []
    for parking in Parking.objects.prefetch_related("spots__reservations").all():
        spots = parking.spots.all()
        reservations = [reservation for spot in spots for reservation in spot.reservations.all()]

        active_reservations = sorted(
            (r for r in reservations if r.status == Reservation.Status.ACTIVE),
            key=lambda r: r.spot.number,
        )
        for reservation in active_reservations:
            reservation.expected_end = reservation.created_at + timedelta(hours=reservation.duration_hours)

        events = []
        for reservation in reservations:
            events.append((reservation.created_at, 1, "Réservation", reservation))
            if reservation.ended_at:
                events.append((reservation.ended_at, -1, end_labels.get(reservation.status, "Fin"), reservation))
        events.sort(key=lambda event: event[0])

        total_spots = len(spots)
        occupied = 0
        movements = []
        for timestamp, delta, label, reservation in events:
            occupied += delta
            movements.append(
                {
                    "timestamp": timestamp,
                    "label": label,
                    "is_entry": delta > 0,
                    "plate": reservation.plate,
                    "spot_number": reservation.spot.number,
                    "occupied": occupied,
                }
            )
        movements.reverse()

        occupied_now = len(active_reservations)
        stats.append(
            {
                "parking": parking,
                "total_spots": total_spots,
                "occupied": occupied_now,
                "free": total_spots - occupied_now,
                "rate": round(occupied_now * 100 / total_spots) if total_spots else 0,
                "active_reservations": active_reservations,
                "movements": movements[:STATS_MOVEMENTS_LIMIT],
                "has_more_movements": len(movements) > STATS_MOVEMENTS_LIMIT,
            }
        )

    total_spots = sum(entry["total_spots"] for entry in stats)
    total_occupied = sum(entry["occupied"] for entry in stats)
    summary = {
        "total_spots": total_spots,
        "occupied": total_occupied,
        "free": total_spots - total_occupied,
        "rate": round(total_occupied * 100 / total_spots) if total_spots else 0,
    }
    return render(
        request,
        "parking/agent_stats.html",
        {"stats": stats, "summary": summary, "movements_limit": STATS_MOVEMENTS_LIMIT},
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_affluence(request):
    period = request.GET.get("jours")
    period_days = int(period if period in HISTORY_PERIODS else HISTORY_PERIODS[0])
    parkings = Parking.objects.all()
    parking_id = request.GET.get("parking", "")
    selected_parking = None
    if parking_id.isascii() and parking_id.isdigit() and len(parking_id) <= 18:
        selected_parking = parkings.filter(pk=parking_id).first()

    today = timezone.localdate()
    days = [today - timedelta(days=offset) for offset in range(period_days - 1, -1, -1)]
    period_start = timezone.make_aware(datetime.combine(days[0], time.min))

    spots = Spot.objects.all()
    reservations = Reservation.objects.filter(
        Q(ended_at__isnull=True) | Q(ended_at__gte=period_start),
        created_at__lte=timezone.now(),
    )
    if selected_parking:
        spots = spots.filter(parking=selected_parking)
        reservations = reservations.filter(spot__parking=selected_parking)
    total_spots = spots.count()

    # Une réservation occupe sa place de sa création jusqu'à sa fin (départ ou annulation).
    events = []
    for created_at, ended_at in reservations.values_list("created_at", "ended_at"):
        events.append((created_at, 1))
        if ended_at:
            events.append((ended_at, -1))
    events.sort()

    entries_by_hour = [0] * 24
    entries_by_weekday = [0] * 7
    daily = []
    occupied = 0
    index = 0
    for day in days:
        day_start = timezone.make_aware(datetime.combine(day, time.min))
        day_end = day_start + timedelta(days=1)
        while index < len(events) and events[index][0] < day_start:
            occupied += events[index][1]
            index += 1

        peak, peak_at, entries = occupied, None, 0
        while index < len(events) and events[index][0] < day_end:
            timestamp, delta = events[index]
            occupied += delta
            index += 1
            if delta > 0:
                entries += 1
                local_timestamp = timezone.localtime(timestamp)
                entries_by_hour[local_timestamp.hour] += 1
                entries_by_weekday[local_timestamp.weekday()] += 1
            if occupied > peak:
                peak, peak_at = occupied, timestamp

        daily.append(
            {
                "day": day,
                "entries": entries,
                "peak": peak,
                "peak_at": peak_at,
                "peak_rate": round(peak * 100 / total_spots) if total_spots else 0,
            }
        )

    def bars(counts, labels):
        highest = max(counts)
        return [
            {
                "label": label,
                "count": count,
                "width": round(count * 100 / highest) if highest else 0,
                "is_max": highest > 0 and count == highest,
            }
            for label, count in zip(labels, counts)
        ]

    busiest_day = max(daily, key=lambda entry: (entry["peak"], entry["entries"]))
    busiest_hour = max(range(24), key=lambda hour: entries_by_hour[hour])
    busiest_weekday = max(range(7), key=lambda weekday: entries_by_weekday[weekday])
    has_entries = any(entries_by_hour)

    return render(
        request,
        "parking/agent_affluence.html",
        {
            "parkings": parkings,
            "selected_parking": selected_parking,
            "periods": HISTORY_PERIODS,
            "period_days": period_days,
            "total_spots": total_spots,
            "daily": list(reversed(daily)),
            "total_entries": sum(entry["entries"] for entry in daily),
            "busiest_day": busiest_day if busiest_day["peak"] else None,
            "busiest_hour": busiest_hour if has_entries else None,
            "busiest_weekday": WEEKDAYS[busiest_weekday] if has_entries else None,
            "hourly": bars(entries_by_hour, [f"{hour:02d} h" for hour in range(24)]),
            "weekly": bars(entries_by_weekday, WEEKDAYS),
        },
    )

@login_required(login_url="parking:login")
def parking_list(request):
    filter_form = ParkingFilterForm(request.GET or None)

    parkings = Parking.objects.annotate(
        total_spots_count=Count("spots"),
        available_spots_count=Count(
            "spots",
            filter=Q(spots__is_available=True),
        ),
    )

    if filter_form.is_valid():
        filters = filter_form.cleaned_data

        min_rate = filters.get("min_rate")
        max_rate = filters.get("max_rate")
        minimum_duration = filters.get("minimum_duration")
        minimum_available_spots = filters.get("minimum_available_spots")
        open_at = filters.get("open_at")

        if min_rate is not None:
            parkings = parkings.filter(
                hourly_rate__isnull=False,
                hourly_rate__gte=min_rate,
            )

        if max_rate is not None:
            parkings = parkings.filter(
                hourly_rate__isnull=False,
                hourly_rate__lte=max_rate,
            )

        if minimum_duration is not None:
            parkings = parkings.filter(
                Q(max_duration_minutes__isnull=True)
                | Q(
                    max_duration_minutes__gte=minimum_duration * 60
                )
            )

        if minimum_available_spots is not None:
            parkings = parkings.filter(
                available_spots_count__gte=minimum_available_spots
            )

        if open_at is not None:
            parkings = parkings.filter(
                Q(opening_time__isnull=True)
                | Q(opening_time__lte=open_at),
                Q(closing_time__isnull=True)
                | Q(closing_time__gte=open_at),
            )

    favorite_parking_ids = set(
        Favorite.objects.filter(user=request.user)
        .values_list("parking_id", flat=True)
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
            "filter_form": filter_form,
            "favorite_parking_ids": favorite_parking_ids,
        },
    )
