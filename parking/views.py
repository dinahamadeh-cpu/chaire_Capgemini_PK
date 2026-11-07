from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import mimetypes
import uuid

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.db.models import Avg, Count, Exists, Max, OuterRef, Q, Subquery
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from urllib.parse import urlsplit

from .forms import (
    AgentActionFilterForm,
    AgentReservationRefusalForm,
    AccountPasswordResetForm,
    AccountDeletionForm,
    ContraventionForm,
    ContraventionOppositionForm,
    ParkingReportForm,
    ParkingReportFilterForm,
    ParkingReportReplyForm,
    ParkingReportUpdateForm,
    ParkingAvailabilityAlertForm,
    ParkingReviewForm,
    ParkingWaitlistForm,
    ParkingSpotClosureForm,
    PaymentDetailsForm,
    ReservationForm,
    RecurringReservationPlanForm,
    SavedVehicleForm,
    ParkingFilterForm,
    SignupForm,
    UserProfileForm,
)
from .models import (
    Contravention,
    DemoPaymentMethod,
    Parking,
    ParkingHoursException,
    ParkingReview,
    ParkingSpotClosure,
    PaymentTransaction,
    Reservation,
    ReservationHistoryEntry,
    RecurringReservationPlan,
    SavedVehicle,
    Spot,
    Favorite,
    ParkingReport,
    ParkingReportComment,
    AgentActionLog,
    ParkingWaitlist,
    UserNotification,
    UserProfile,
    VehicleType,
    plate_validator,
    notify_parking_availability,
    send_monthly_budget_notification,
    sync_spot_availability,
)
from .qr_codes import create_reservation_qr, verify_reservation_qr
from .services import expire_late_reservations

STATS_MOVEMENTS_LIMIT = 20
HISTORY_PERIODS = ["7", "30", "90"]
WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def _available_spot_count(at=None, *, pmr_only=False, relation="spots"):
    at = at or timezone.now()
    filters = Q(**{f"{relation}__is_available": True})
    if pmr_only:
        filters &= Q(**{f"{relation}__is_pmr": True})
    unavailable_spot_ids = ParkingSpotClosure.objects.filter(
        closed_at__isnull=True,
        starts_at__lte=at,
        ends_at__gt=at,
    ).values("spot_id")
    filters &= ~Q(**{f"{relation}__pk__in": Subquery(unavailable_spot_ids)})
    return Count(relation, filter=filters, distinct=True)


def _currently_available_spots(queryset, at=None):
    at = at or timezone.now()
    active_closures = ParkingSpotClosure.objects.filter(
        spot_id=OuterRef("pk"),
        closed_at__isnull=True,
        starts_at__lte=at,
        ends_at__gt=at,
    )
    return queryset.filter(is_available=True).annotate(
        has_active_closure=Exists(active_closures)
    ).filter(has_active_closure=False)


def _record_agent_action(
    actor,
    action_type,
    summary,
    *,
    report=None,
    spot_closure=None,
    contravention=None,
    reservation=None,
):
    return AgentActionLog.objects.create(
        actor=actor,
        action_type=action_type,
        summary=summary,
        report=report,
        spot_closure=spot_closure,
        contravention=contravention,
        reservation=reservation,
    )


def _next_weekly_occurrence(weekday, start_time, after=None):
    after = after or timezone.now()
    local_after = timezone.localtime(after)
    days_ahead = (weekday - local_after.weekday()) % 7
    candidate_date = local_after.date() + timedelta(days=days_ahead)
    candidate = timezone.make_aware(
        datetime.combine(candidate_date, start_time),
        timezone.get_current_timezone(),
    )
    if candidate <= after:
        candidate += timedelta(days=7)
    return candidate


def _record_reservation_history(actor, reservation, action, summary):
    return ReservationHistoryEntry.objects.create(
        reservation=reservation,
        actor=actor,
        action=action,
        summary=summary,
        plate=reservation.plate,
        parking_name=reservation.spot.parking.name,
        spot_number=reservation.spot.number,
    )


def _reservation_conflicts_with_hours_exception(parking, starts_at, ends_at):
    date_to_check = timezone.localtime(starts_at).date()
    while True:
        day_start = timezone.make_aware(
            datetime.combine(date_to_check, time.min),
            timezone.get_current_timezone(),
        )
        next_day_start = timezone.make_aware(
            datetime.combine(date_to_check + timedelta(days=1), time.min),
            timezone.get_current_timezone(),
        )
        segment_start = max(starts_at, day_start)
        segment_end = min(ends_at, next_day_start)
        if segment_start >= segment_end:
            return False
        exception = ParkingHoursException.objects.filter(
            parking=parking,
            date=date_to_check,
        ).first()
        if exception:
            if exception.is_closed:
                return True
            opening = timezone.make_aware(
                datetime.combine(date_to_check, exception.opening_time),
                timezone.get_current_timezone(),
            )
            closing = timezone.make_aware(
                datetime.combine(date_to_check, exception.closing_time),
                timezone.get_current_timezone(),
            )
            if segment_start < opening or segment_end > closing:
                return True
        if segment_end >= ends_at:
            return False
        date_to_check += timedelta(days=1)


def home(request):
    return render(request, "parking/home.html")


@require_http_methods(["GET", "POST"])
def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.email = form.cleaned_data["email"]
        user.save(update_fields=["email"])
        UserProfile.objects.create(
            user=user,
            phone_number=form.cleaned_data["phone_number"],
            vehicle_model=form.cleaned_data["vehicle_model"],
        )
        login(request, user)
        messages.success(request, "Votre compte a été créé. Bienvenue !")
        return redirect("parking:parking_list")
    return render(request, "parking/signup.html", {"form": form})


@login_required(login_url="parking:login")
@require_http_methods(["GET", "POST"])
def account(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = UserProfileForm(
            request.POST,
            initial={"vehicle_type": profile.vehicle_type},
        )
        if form.is_valid():
            request.user.email = form.cleaned_data["email"]
            request.user.save(update_fields=["email"])
            profile.phone_number = form.cleaned_data["phone_number"]
            profile.vehicle_model = form.cleaned_data["vehicle_model"]
            profile.vehicle_type = (
                form.cleaned_data["vehicle_type"] or profile.vehicle_type
            )
            profile.pmr_justification_registered = form.cleaned_data[
                "pmr_justification_registered"
            ]
            profile.notifications_enabled = form.cleaned_data[
                "notifications_enabled"
            ]
            profile.prefers_covered_parking = form.cleaned_data[
                "prefers_covered_parking"
            ]
            profile.vehicle_height_m = form.cleaned_data["vehicle_height_m"]
            profile.requires_ev_charging = form.cleaned_data["requires_ev_charging"]
            profile.color_vision_mode = form.cleaned_data["color_vision_mode"]
            profile.monthly_budget_limit = form.cleaned_data["monthly_budget_limit"]
            profile.save(
                update_fields=[
                    "phone_number",
                    "vehicle_model",
                    "vehicle_type",
                    "pmr_justification_registered",
                    "notifications_enabled",
                    "prefers_covered_parking",
                    "vehicle_height_m",
                    "requires_ev_charging",
                    "color_vision_mode",
                    "monthly_budget_limit",
                ]
            )
            send_monthly_budget_notification(request.user.pk)
            messages.success(
                request,
                "Votre profil a été mis à jour. Vos paramètres sont enregistrés.",
            )
            return redirect(f"parking:{request.resolver_match.url_name}")
    else:
        form = UserProfileForm(
            initial={
                "email": request.user.email,
                "phone_number": profile.phone_number,
                "vehicle_model": profile.vehicle_model,
                "vehicle_type": profile.vehicle_type,
                "pmr_justification_registered": profile.pmr_justification_registered,
                "notifications_enabled": profile.notifications_enabled,
                "prefers_covered_parking": profile.prefers_covered_parking,
                "vehicle_height_m": profile.vehicle_height_m,
                "requires_ev_charging": profile.requires_ev_charging,
                "color_vision_mode": profile.color_vision_mode,
                "monthly_budget_limit": profile.monthly_budget_limit,
            }
        )
    payment_methods = DemoPaymentMethod.objects.filter(user=request.user).order_by(
        "created_at", "id"
    )
    month = timezone.localdate()
    transactions_this_month = PaymentTransaction.objects.filter(
        user=request.user,
        created_at__year=month.year,
        created_at__month=month.month,
    )
    spent_this_month = sum(
        (
            -transaction.amount
            if transaction.kind == PaymentTransaction.Kind.REFUND
            else transaction.amount
        )
        for transaction in transactions_this_month
    )
    return render(
        request,
        "parking/account.html",
        {
            "form": form,
            "payment_methods": payment_methods,
            "settings_page": request.resolver_match.url_name == "settings",
            "spent_this_month": spent_this_month,
        },
    )


@login_required(login_url="parking:login")
@require_http_methods(["GET", "POST"])
def user_vehicles(request):
    if request.method == "POST" and request.POST.get("delete_vehicle_id"):
        vehicle = get_object_or_404(
            SavedVehicle,
            pk=request.POST["delete_vehicle_id"],
            user=request.user,
        )
        vehicle.delete()
        messages.success(request, "Le véhicule enregistré a été supprimé.")
        return redirect("parking:user_vehicles")

    form = SavedVehicleForm(
        request.POST or None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        vehicle = form.save(commit=False)
        vehicle.user = request.user
        try:
            vehicle.save()
        except IntegrityError:
            form.add_error("plate", "Cette plaque est déjà enregistrée dans votre compte.")
        else:
            messages.success(request, "Votre véhicule a été enregistré.")
            return redirect("parking:user_vehicles")
    vehicles = SavedVehicle.objects.filter(user=request.user)
    return render(
        request,
        "parking/user_vehicles.html",
        {"form": form, "vehicles": vehicles},
    )


@login_required(login_url="parking:login")
@require_http_methods(["GET", "POST"])
def recurring_reservation_plans(request):
    if request.method == "POST" and request.POST.get("delete_plan_id"):
        plan = get_object_or_404(
            RecurringReservationPlan,
            pk=request.POST["delete_plan_id"],
            user=request.user,
        )
        plan.delete()
        messages.success(request, "Le rappel récurrent a été supprimé.")
        return redirect("parking:recurring_reservation_plans")

    form = RecurringReservationPlanForm(
        request.POST or None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        plan = form.save(commit=False)
        plan.user = request.user
        plan.next_reminder_at = _next_weekly_occurrence(
            plan.weekday,
            plan.start_time,
        ) - timedelta(minutes=30)
        plan.save()
        messages.success(
            request,
            "Le rappel est enregistré. Vous recevrez une notification à chaque occurrence "
            "et devrez confirmer vous-même la réservation.",
        )
        return redirect("parking:recurring_reservation_plans")
    plans = RecurringReservationPlan.objects.filter(
        user=request.user,
        is_active=True,
    ).select_related("parking", "vehicle")
    return render(
        request,
        "parking/recurring_reservation_plans.html",
        {"form": form, "plans": plans},
    )


@login_required(login_url="parking:login")
@require_POST
def delete_account(request):
    user = request.user
    form = AccountDeletionForm(request.POST, username=user.get_username())
    if not form.is_valid():
        for error in form.errors.values():
            for message in error:
                messages.error(request, message)
        return redirect("parking:settings")

    with transaction.atomic():
        locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
        if Reservation.objects.filter(
            user=locked_user,
            status=Reservation.Status.ACTIVE,
        ).exists():
            messages.error(
                request,
                "Votre compte ne peut pas être supprimé tant qu’un stationnement est en cours.",
            )
            return redirect("parking:settings")
        if Contravention.objects.filter(user=locked_user).exists():
            messages.error(
                request,
                "Votre compte ne peut pas être supprimé tant qu’une contravention reçue lui est associée.",
            )
            return redirect("parking:settings")

        locked_user.delete()

    logout(request)
    messages.success(request, "Votre compte a été supprimé.")
    return redirect("parking:home")


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
@require_POST
def set_favorite_availability_alert(request, parking_id):
    favorite = get_object_or_404(
        Favorite.objects.select_related("parking"),
        user=request.user,
        parking_id=parking_id,
    )
    if request.POST.get("disable_alert") == "1":
        favorite.availability_alert_threshold = None
        favorite.availability_alert_sent_at = None
        favorite.save(
            update_fields=[
                "availability_alert_threshold",
                "availability_alert_sent_at",
            ]
        )
        messages.success(request, "L’alerte de disponibilité a été désactivée.")
        return redirect("parking:favorite_list")
    form = ParkingAvailabilityAlertForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Le seuil d’alerte doit être un nombre de places valide.")
        return redirect("parking:favorite_list")
    threshold = form.cleaned_data["threshold"]
    if threshold is not None and threshold > favorite.parking.spots.count():
        messages.error(
            request,
            "Le seuil ne peut pas dépasser le nombre total de places de ce parking.",
        )
        return redirect("parking:favorite_list")
    favorite.availability_alert_threshold = threshold
    favorite.availability_alert_sent_at = None
    favorite.save(
        update_fields=["availability_alert_threshold", "availability_alert_sent_at"]
    )
    currently_available = _currently_available_spots(
        favorite.parking.spots.all()
    ).count()
    if threshold is not None and currently_available >= threshold:
        UserNotification.objects.create(
            user=request.user,
            title="Disponibilité de votre parking favori",
            message=(
                f"{currently_available} places sont déjà disponibles au "
                f"{favorite.parking.name}, au-dessus de votre seuil."
            ),
            url=reverse("parking:parking_detail", args=[favorite.parking_id]),
        )
        favorite.availability_alert_sent_at = timezone.now()
        favorite.save(update_fields=["availability_alert_sent_at"])
        messages.success(
            request,
            f"Le seuil est déjà atteint : une notification vous a été envoyée.",
        )
        return redirect("parking:favorite_list")
    messages.success(request, f"Vous serez averti dès {threshold} place(s) libre(s).")
    return redirect("parking:favorite_list")


@login_required(login_url="parking:login")
def favorite_list(request):
    favorites = (
        Favorite.objects.filter(user=request.user)
        .select_related("parking")
        .annotate(
            total_spots_count=Count("parking__spots"),
            available_spots_count=_available_spot_count(
                relation="parking__spots"
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
    expire_late_reservations()
    parking = get_object_or_404(Parking, id=parking_id)
    available_spots = _currently_available_spots(parking.spots.all())
    total_spots = parking.spots.count()
    last_availability_update = parking.spots.aggregate(
        latest=Max("availability_updated_at")
    )["latest"]
    pmr_justification_registered = UserProfile.objects.filter(
        user=request.user,
        pmr_justification_registered=True,
    ).exists()
    favorite = Favorite.objects.filter(
        user=request.user,
        parking=parking,
    ).first()
    review_stats = ParkingReview.objects.filter(parking=parking).aggregate(
        average=Avg("rating"),
        count=Count("id"),
    )
    upcoming_hours_exceptions = ParkingHoursException.objects.filter(
        parking=parking,
        date__gte=timezone.localdate(),
        date__lte=timezone.localdate() + timedelta(days=30),
    ).order_by("date")

    return render(
        request,
        "parking/parking_details.html",
        {
            "parking": parking,
            "available_spots": available_spots,
            "total_spots": total_spots,
            "is_waitlisted": ParkingWaitlist.objects.filter(
                user=request.user,
                parking=parking,
            ).exists(),
            "waitlist_form": ParkingWaitlistForm(
                initial={
                    "starts_at": timezone.localtime(
                        timezone.now() + timedelta(hours=1)
                    ).strftime("%Y-%m-%dT%H:%M"),
                    "ends_at": timezone.localtime(
                        timezone.now() + timedelta(days=7)
                    ).strftime("%Y-%m-%dT%H:%M"),
                }
            ),
            "favorite": favorite,
            "availability_alert_form": ParkingAvailabilityAlertForm(
                initial={
                    "threshold": (
                        favorite.availability_alert_threshold if favorite else None
                    )
                }
            ),
            "reviews": ParkingReview.objects.filter(parking=parking).select_related(
                "user"
            )[:20],
            "review_average": review_stats["average"],
            "review_count": review_stats["count"],
            "upcoming_hours_exceptions": upcoming_hours_exceptions,
            "availability_last_updated": (
                timezone.localtime(last_availability_update).strftime(
                    "%d/%m/%Y à %H:%M:%S"
                )
                if last_availability_update
                else None
            ),
            "pmr_justification_registered": pmr_justification_registered,
            "parking_data": {
                "name": parking.name,
                "address": parking.address,
                "latitude": parking.latitude,
                "longitude": parking.longitude,
            },
        },
    )


@login_required(login_url="parking:login")
@never_cache
def parking_availability(request):
    expire_late_reservations()
    waitlisted_parking_ids = set(
        ParkingWaitlist.objects.filter(user=request.user).values_list(
            "parking_id",
            flat=True,
        )
    )
    now = timezone.now()
    parkings = Parking.objects.annotate(
        total_spots_count=Count("spots"),
        available_spots_count=_available_spot_count(now),
        available_pmr_spots_count=_available_spot_count(now, pmr_only=True),
        last_availability_update=Max("spots__availability_updated_at"),
    )
    return JsonResponse(
        {
            "parkings": [
                {
                    "id": parking.pk,
                    "total_spots": parking.total_spots_count,
                    "available_spots": parking.available_spots_count,
                    "available_pmr_spots": parking.available_pmr_spots_count,
                    "waitlisted": parking.pk in waitlisted_parking_ids,
                    "updated_at": (
                        timezone.localtime(
                            parking.last_availability_update
                        ).isoformat()
                        if parking.last_availability_update
                        else None
                    ),
                }
                for parking in parkings
            ]
        }
    )


@login_required(login_url="parking:login")
@never_cache
def parking_detail_availability(request, parking_id):
    expire_late_reservations()
    parking = get_object_or_404(Parking, pk=parking_id)
    available_spots = _currently_available_spots(parking.spots.all())
    total_spots = parking.spots.count()
    pmr_justification_registered = UserProfile.objects.filter(
        user=request.user,
        pmr_justification_registered=True,
    ).exists()
    last_availability_update = parking.spots.aggregate(
        latest=Max("availability_updated_at")
    )["latest"]
    spots_html = render_to_string(
        "parking/_available_spots.html",
        {
            "parking": parking,
            "available_spots": available_spots,
            "pmr_justification_registered": pmr_justification_registered,
            "is_waitlisted": ParkingWaitlist.objects.filter(
                user=request.user,
                parking=parking,
            ).exists(),
            "waitlist_form": ParkingWaitlistForm(
                initial={
                    "starts_at": timezone.localtime(
                        timezone.now() + timedelta(hours=1)
                    ).strftime("%Y-%m-%dT%H:%M"),
                    "ends_at": timezone.localtime(
                        timezone.now() + timedelta(days=7)
                    ).strftime("%Y-%m-%dT%H:%M"),
                }
            ),
        },
        request=request,
    )
    return JsonResponse(
        {
            "available_spots": available_spots.count(),
            "total_spots": total_spots,
            "updated_at": (
                timezone.localtime(last_availability_update).isoformat()
                if last_availability_update
                else None
            ),
            "spots_html": spots_html,
        }
    )


@login_required(login_url="parking:login")
@require_http_methods(["GET", "POST"])
def payment_methods(request):
    if request.method == "POST":
        payment_method_id = request.POST.get("remove_payment_method_id")
        if payment_method_id:
            payment_method = get_object_or_404(
                DemoPaymentMethod,
                pk=payment_method_id,
                user=request.user,
            )
            payment_method.delete()
            messages.success(request, "Moyen de paiement simulé supprimé.")
            return redirect("parking:payment_methods")

        form = PaymentDetailsForm(request.POST)
        if form.is_valid():
            payment_method = DemoPaymentMethod.objects.create(
                user=request.user,
                name=form.cleaned_data["name"],
            )
            messages.success(
                request,
                f"Moyen de paiement simulé « {payment_method.name} » enregistré. "
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

    payment_methods = DemoPaymentMethod.objects.filter(user=request.user).order_by(
        "created_at", "id"
    )
    return render(
        request,
        "parking/payment_methods.html",
        {
            "payment_methods": payment_methods,
            "payment_method": payment_methods.exists(),
            "form": form,
            "form_errors": form_errors,
        },
    )


@login_required(login_url="parking:login")
@require_http_methods(["GET", "POST"])
def reserve_spot(request, parking_id, spot_id):
    expire_late_reservations()
    spot = get_object_or_404(Spot, pk=spot_id, parking_id=parking_id)
    spot.refresh_from_db()
    if spot.is_pmr and not UserProfile.objects.filter(
        user=request.user,
        pmr_justification_registered=True,
    ).exists():
        messages.error(
            request,
            "Vous ne disposez pas de Justificatif PMR.",
        )
        return redirect("parking:parking_detail", parking_id=parking_id)

    if spot.parking.hourly_rate is None:
        messages.error(
            request,
            "La réservation est impossible : le tarif de ce parking n'est pas renseigné.",
        )
        return redirect("parking:parking_detail", parking_id=parking_id)

    if not spot.is_available:
        messages.error(request, "Cette place n'est plus disponible.")
        return redirect("parking:parking_detail", parking_id=parking_id)
    if ParkingSpotClosure.objects.filter(
        spot=spot,
        closed_at__isnull=True,
        starts_at__lte=timezone.now(),
        ends_at__gt=timezone.now(),
    ).exists():
        messages.error(request, "Cette place est temporairement indisponible.")
        return redirect("parking:parking_detail", parking_id=parking_id)

    saved_payment_methods = list(
        DemoPaymentMethod.objects.filter(user=request.user).order_by(
            "created_at", "id"
        )
    )
    has_saved_payment_method = bool(saved_payment_methods)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    rate_cents = int(spot.parking.hourly_rate * 100)

    if request.method == "GET":
        form = ReservationForm(
            saved_payment_methods=saved_payment_methods,
            max_duration_minutes=spot.parking.max_duration_minutes,
            user=request.user,
            initial={
                "starts_at": timezone.localtime(
                    timezone.now() + timedelta(minutes=30)
                ).strftime("%Y-%m-%dT%H:%M"),
            },
        )
        return render(
            request,
            "parking/reservation_checkout.html",
            {
                "parking": spot.parking,
                "spot": spot,
                "form": form,
                "has_saved_payment_method": has_saved_payment_method,
                "rate_cents": rate_cents,
                "vehicle_type": profile.vehicle_type,
            },
        )

    if request.method != "POST":
        return redirect("parking:parking_detail", parking_id=parking_id)

    form = ReservationForm(
        request.POST,
        saved_payment_methods=saved_payment_methods,
        max_duration_minutes=spot.parking.max_duration_minutes,
        user=request.user,
    )
    if not form.is_valid():
        form_errors = [
            f"{form.fields[field].label or field} : {error}"
            for field, errors in form.errors.items()
            for error in errors
        ]
        safe_form = ReservationForm(
            saved_payment_methods=saved_payment_methods,
            max_duration_minutes=spot.parking.max_duration_minutes,
            user=request.user,
            initial={
                "duration_days": request.POST.get("duration_days", ""),
                "duration_hours": request.POST.get("duration_hours", ""),
                "duration_extra_minutes": request.POST.get(
                    "duration_extra_minutes", ""
                ),
                "duration_minutes": request.POST.get("duration_minutes", ""),
                "plate": request.POST.get("plate", ""),
                "payment_method": request.POST.get("payment_method", ""),
                "starts_at": request.POST.get("starts_at", ""),
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
                "has_saved_payment_method": has_saved_payment_method,
                "rate_cents": rate_cents,
                "vehicle_type": profile.vehicle_type,
            },
        )

    duration_minutes = form.cleaned_data["duration_minutes"]
    reservation_start = form.cleaned_data["starts_at"] or timezone.now()
    reservation_end = reservation_start + timedelta(minutes=duration_minutes)
    if _reservation_conflicts_with_hours_exception(
        spot.parking,
        reservation_start,
        reservation_end,
    ):
        messages.error(
            request,
            "Le créneau demandé ne respecte pas les horaires exceptionnels de ce parking.",
        )
        return redirect("parking:parking_detail", parking_id=parking_id)
    if ParkingSpotClosure.objects.filter(
        spot=spot,
        closed_at__isnull=True,
        starts_at__lt=reservation_end,
        ends_at__gt=reservation_start,
    ).exists():
        messages.error(
            request,
            "La place est indisponible pendant tout ou partie du créneau choisi.",
        )
        return redirect("parking:parking_detail", parking_id=parking_id)
    amount_paid = (
        spot.parking.hourly_rate * duration_minutes / 60
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        with transaction.atomic():
            reservation = Reservation.objects.create(
                user=request.user,
                spot=spot,
                plate=form.cleaned_data["plate"],
                saved_vehicle=form.cleaned_data.get("saved_vehicle"),
                vehicle_type=(
                    form.cleaned_data["saved_vehicle"].vehicle_type
                    if form.cleaned_data.get("saved_vehicle")
                    else profile.vehicle_type
                ),
                starts_at=form.cleaned_data["starts_at"],
                duration_minutes=duration_minutes,
                amount_paid=amount_paid,
                amount_charged=amount_paid,
            )
            PaymentTransaction.objects.create(
                user=request.user,
                reservation=reservation,
                kind=PaymentTransaction.Kind.RESERVATION,
                amount=amount_paid,
            )
    except IntegrityError:
        messages.error(
            request,
            "Une réservation utilise déjà cette place ou cette plaque. Vérifiez vos réservations.",
        )
    else:
        messages.success(
            request,
            f"Réservation confirmée. Estimation du montant simulé : {amount_paid:.2f} €. "
            f"Référence de paiement : {reservation.payment_reference}. "
            "Le montant final sera recalculé selon la durée réelle. "
            "Aucune donnée de carte n'a été enregistrée.",
        )

    return redirect("parking:parking_detail", parking_id=parking_id)


@login_required(login_url="parking:login")
def reservation_list(request):
    expire_late_reservations()
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    reservations = (
        Reservation.objects.filter(user=request.user)
        .select_related("spot", "spot__parking")
        .order_by("-created_at")
    )
    now = timezone.now()
    for reservation in reservations:
        remaining = reservation.expected_end - now
        reservation.free_cancellation = (
            reservation.starts_at is None
            or reservation.starts_at - now >= timedelta(minutes=30)
        )
        reservation.reminder_due = (
            profile.notifications_enabled
            and reservation.status == Reservation.Status.ACTIVE
            and reservation.arrived_at is not None
            and timedelta(0) < remaining <= timedelta(minutes=10)
        )
    return render(
        request,
        "parking/reservation_list.html",
        {"reservations": reservations},
    )


@login_required(login_url="parking:login")
def user_history(request):
    entries = [
        {
            "kind": "reservation",
            "created_at": reservation.created_at,
            "reservation": reservation,
        }
        for reservation in Reservation.objects.filter(user=request.user)
        .select_related("spot__parking")
    ]
    entries.extend(
        {
            "kind": "contravention",
            "created_at": contravention.created_at,
            "contravention": contravention,
        }
        for contravention in Contravention.objects.filter(user=request.user)
        .select_related("parking", "spot")
    )
    entries.sort(key=lambda entry: entry["created_at"], reverse=True)
    return render(request, "parking/user_history.html", {"entries": entries})


@login_required(login_url="parking:login")
def user_notifications(request):
    notifications = UserNotification.objects.filter(user=request.user)
    notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return render(
        request,
        "parking/user_notifications.html",
        {"notifications": notifications},
    )


@login_required(login_url="parking:login")
def consult_user_notification(request, notification_id):
    notification = get_object_or_404(
        UserNotification,
        pk=notification_id,
        user=request.user,
    )
    target_url = notification.url
    if not target_url or not url_has_allowed_host_and_scheme(
        target_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        messages.info(request, "Cette notification ne possède pas de lien consultable.")
        return redirect("parking:user_notifications")

    try:
        match = resolve(urlsplit(target_url).path)
    except Resolver404:
        messages.info(
            request,
            "Le contenu lié à cette notification n’est plus disponible.",
        )
        return redirect("parking:user_notifications")

    if match.view_name == "parking:reservation_summary":
        reservation = Reservation.objects.filter(
            pk=match.kwargs["reservation_id"],
            user=request.user,
        ).first()
        if reservation is None:
            messages.info(
                request,
                "La réservation liée n’est plus disponible. Consultez vos réservations.",
            )
            return redirect("parking:reservation_list")

    if match.view_name == "parking:parking_detail":
        if not Parking.objects.filter(pk=match.kwargs["parking_id"]).exists():
            messages.info(
                request,
                "Le parking lié n’est plus disponible. Consultez la liste des parkings.",
            )
            return redirect("parking:parking_list")

    return redirect(target_url)


@login_required(login_url="parking:login")
def compare_parkings(request):
    selected_ids = request.GET.getlist("parking_ids")
    if not 2 <= len(selected_ids) <= 3 or any(
        not value.isdecimal() for value in selected_ids
    ):
        return render(
            request,
            "parking/parking_comparison.html",
            {"parkings": [], "selection_error": True},
        )

    selected_ids = list(dict.fromkeys(int(value) for value in selected_ids))
    if not 2 <= len(selected_ids) <= 3:
        return render(
            request,
            "parking/parking_comparison.html",
            {"parkings": [], "selection_error": True},
        )

    parkings_by_id = Parking.objects.filter(pk__in=selected_ids).annotate(
        total_spots_count=Count("spots"),
        available_spots_count=_available_spot_count(timezone.now()),
        average_rating=Avg("reviews__rating"),
        review_count=Count("reviews", distinct=True),
    )
    parkings = {parking.pk: parking for parking in parkings_by_id}
    if len(parkings) != len(selected_ids):
        return render(
            request,
            "parking/parking_comparison.html",
            {"parkings": [], "selection_error": True},
        )

    return render(
        request,
        "parking/parking_comparison.html",
        {
            "parkings": [parkings[parking_id] for parking_id in selected_ids],
            "selection_error": False,
        },
    )


@login_required(login_url="parking:login")
@require_POST
def toggle_waitlist(request, parking_id):
    parking = get_object_or_404(Parking, pk=parking_id)
    existing_entry = ParkingWaitlist.objects.filter(
        user=request.user,
        parking=parking,
    ).first()
    if existing_entry:
        existing_entry.delete()
        messages.success(request, f"Vous avez quitté la liste d’attente de {parking.name}.")
        return redirect("parking:parking_detail", parking_id=parking.pk)
    data = request.POST.copy()
    if not data.get("starts_at") and not data.get("ends_at"):
        now = timezone.localtime()
        starts_at = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        data["starts_at"] = starts_at.strftime("%Y-%m-%dT%H:%M")
        data["ends_at"] = (starts_at + timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M"
        )
    form = ParkingWaitlistForm(data)
    if not form.is_valid():
        messages.error(request, "Choisissez une période valide pour la liste d’attente.")
        return redirect("parking:parking_detail", parking_id=parking.pk)
    starts_at = form.cleaned_data["starts_at"]
    ends_at = form.cleaned_data["ends_at"]
    if _currently_available_spots(parking.spots.all()).exists():
        messages.info(request, "Une place est disponible : consultez le parking pour la réserver.")
    else:
        ParkingWaitlist.objects.create(
            user=request.user,
            parking=parking,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        messages.success(
            request,
            f"Vous serez averti dans vos notifications si une place se libère "
            f"à {parking.name} entre "
            f"{timezone.localtime(starts_at):%d/%m/%Y %H:%M} et "
            f"{timezone.localtime(ends_at):%d/%m/%Y %H:%M}.",
        )
    return redirect("parking:parking_detail", parking_id=parking.pk)


@login_required(login_url="parking:login")
@require_http_methods(["GET", "POST"])
def submit_parking_report(request):
    form = ParkingReportForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        report = form.save(commit=False)
        report.user = request.user
        report.save()
        messages.success(
            request,
            "Merci, votre signalement a été transmis à l’équipe.",
        )
        return redirect("parking:submit_parking_report")
    return render(
        request,
        "parking/parking_report_form.html",
        {"form": form},
    )


@login_required(login_url="parking:login")
def user_parking_reports(request):
    reports = (
        ParkingReport.objects.filter(user=request.user)
        .select_related("parking", "spot", "reservation")
        .order_by("-created_at")
    )
    return render(
        request,
        "parking/user_parking_reports.html",
        {"reports": reports},
    )


@login_required(login_url="parking:login")
def user_parking_report_detail(request, report_id):
    report = get_object_or_404(
        ParkingReport.objects.select_related("parking", "spot", "reservation")
        .prefetch_related("comments__author"),
        pk=report_id,
        user=request.user,
    )
    form = ParkingReportReplyForm()
    if request.method == "POST":
        form = ParkingReportReplyForm(request.POST)
        if form.is_valid():
            reopened = report.status in (
                ParkingReport.Status.RESOLVED,
                ParkingReport.Status.REFUSED,
            )
            with transaction.atomic():
                if reopened:
                    report.status = ParkingReport.Status.IN_PROGRESS
                report.save(update_fields=["status", "updated_at"])
                ParkingReportComment.objects.create(
                    report=report,
                    author=request.user,
                    message=form.cleaned_data["message"],
                )
                agents = get_user_model().objects.filter(
                    is_active=True,
                    groups__name="Agents",
                ).exclude(pk=request.user.pk).distinct()
                UserNotification.objects.bulk_create(
                    [
                        UserNotification(
                            user=agent,
                            title="Nouvelle réponse à un signalement",
                            message=(
                                f"{request.user.username} a répondu au signalement "
                                f"« {report.title or report.get_category_display()} »."
                            ),
                            url=reverse(
                                "parking:agent_parking_report_detail",
                                args=[report.pk],
                            ),
                        )
                        for agent in agents
                    ]
                )
            if reopened:
                messages.success(
                    request,
                    "Votre signalement a été rouvert et transmis à l’équipe.",
                )
            else:
                messages.success(request, "Votre réponse a été transmise à l’équipe.")
            return redirect(
                "parking:user_parking_report_detail",
                report_id=report.pk,
            )
    return render(
        request,
        "parking/user_parking_report_detail.html",
        {"report": report, "form": form},
    )


@login_required(login_url="parking:login")
def parking_report_photo(request, report_id):
    report = get_object_or_404(ParkingReport, pk=report_id)
    if report.user_id != request.user.pk and not _is_agent(request.user):
        raise Http404
    if not report.photo:
        raise Http404("Aucune photo n’est associée à ce signalement.")
    photo = report.photo.open("rb")
    header = photo.read(12)
    photo.seek(0)
    if header.startswith(b"\xff\xd8\xff"):
        content_type = "image/jpeg"
    elif header.startswith(b"\x89PNG\r\n\x1a\n"):
        content_type = "image/png"
    elif header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        content_type = "image/webp"
    else:
        photo.close()
        raise Http404("Le fichier associé n’est pas une image autorisée.")
    response = FileResponse(photo, content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@login_required(login_url="parking:login")
@never_cache
def reservation_qr(request, reservation_id):
    reservation = get_object_or_404(
        Reservation,
        pk=reservation_id,
        user=request.user,
        status=Reservation.Status.ACTIVE,
    )
    qr_data = create_reservation_qr(reservation.id, request)
    qr_data["consumed"] = reservation.qr_verified_bucket == qr_data["bucket"]
    if qr_data["consumed"]:
        qr_data["image_data_uri"] = None
        qr_data["verification_code"] = None
    return render(
        request,
        "parking/reservation_qr.html",
        {
            "reservation": reservation,
            "qr_data": qr_data,
        },
    )


@login_required(login_url="parking:login")
@never_cache
def reservation_qr_data(request, reservation_id):
    reservation = get_object_or_404(
        Reservation,
        pk=reservation_id,
        user=request.user,
        status=Reservation.Status.ACTIVE,
    )
    qr_data = create_reservation_qr(reservation.id, request)
    qr_data["consumed"] = reservation.qr_verified_bucket == qr_data["bucket"]
    if qr_data["consumed"]:
        qr_data["image_data_uri"] = None
        qr_data["verification_code"] = None
    return JsonResponse(qr_data)


@login_required(login_url="parking:login")
@require_POST
def extend_reservation(request, reservation_id):
    reservation = get_object_or_404(
        Reservation.objects.select_related("spot__parking"),
        pk=reservation_id,
        user=request.user,
        status=Reservation.Status.ACTIVE,
        arrived_at__isnull=False,
    )
    try:
        extra_days = int(request.POST.get("extra_days", "0") or "0")
        extra_hours = int(request.POST.get("extra_hours", "0") or "0")
        extra_minutes = int(request.POST.get("extra_minutes", "0") or "0")
    except (TypeError, ValueError):
        extra_days = extra_hours = extra_minutes = -1
    if min(extra_days, extra_hours, extra_minutes) < 0:
        messages.error(request, "Saisissez une durée de prolongation valide.")
        return redirect("parking:reservation_list")

    extra_minutes = extra_days * 1440 + extra_hours * 60 + extra_minutes
    if extra_minutes < 1:
        messages.error(request, "Saisissez une durée de prolongation supérieure à zéro.")
        return redirect("parking:reservation_list")
    if extra_minutes > 2147483647 - reservation.duration_minutes:
        messages.error(request, "La durée de prolongation est trop longue.")
        return redirect("parking:reservation_list")
    extended_duration = reservation.duration_minutes + extra_minutes
    max_duration = reservation.spot.parking.max_duration_minutes
    if max_duration is not None and extended_duration > max_duration:
        messages.error(request, "La durée maximale autorisée par ce parking serait dépassée.")
        return redirect("parking:reservation_list")

    rate = reservation.spot.parking.hourly_rate
    if rate is None:
        messages.error(request, "La prolongation est impossible : le tarif du parking n'est pas renseigné.")
        return redirect("parking:reservation_list")

    previous_duration = reservation.duration_minutes
    previous_charge = reservation.amount_charged or reservation.amount_paid or Decimal("0.00")
    reservation.duration_minutes = extended_duration
    reservation.amount_paid = (
        rate * extended_duration / 60
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    reservation.amount_charged = reservation.amount_paid
    reservation.save(
        update_fields=["duration_minutes", "amount_paid", "amount_charged"]
    )
    _record_reservation_history(
        request.user,
        reservation,
        ReservationHistoryEntry.Action.EXTENDED,
        (
            f"Durée modifiée de {previous_duration} à {extended_duration} minutes. "
            f"Montant simulé mis à jour à {reservation.amount_paid:.2f} €."
        ),
    )
    added_charge = reservation.amount_charged - previous_charge
    if added_charge > 0 and reservation.user_id:
        PaymentTransaction.objects.create(
            user=reservation.user,
            reservation=reservation,
            kind=PaymentTransaction.Kind.RESERVATION,
            amount=added_charge,
        )
    messages.success(request, f"Stationnement prolongé de {extra_minutes} minutes.")
    return redirect("parking:reservation_list")


@login_required(login_url="parking:login")
@require_POST
def confirm_arrival(request, reservation_id):
    expire_late_reservations()
    reservation = get_object_or_404(
        Reservation,
        pk=reservation_id,
        user=request.user,
    )
    if reservation.status != Reservation.Status.ACTIVE:
        messages.info(request, "Cette réservation n’est plus active.")
        return redirect("parking:reservation_list")
    if reservation.starts_at is not None:
        messages.info(
            request,
            "Pour démarrer le chronomètre, présentez votre QR code à un agent "
            "à partir de l’heure prévue.",
        )
        return redirect("parking:reservation_list")
    arrival_recorded = Reservation.objects.filter(
        pk=reservation.pk,
        status=Reservation.Status.ACTIVE,
        arrived_at__isnull=True,
    ).update(arrived_at=timezone.now())

    if arrival_recorded:
        messages.success(request, "Votre arrivée est confirmée. Le décompte du stationnement commence.")
    else:
        reservation.refresh_from_db()
        if reservation.status != Reservation.Status.ACTIVE:
            messages.info(request, "Cette réservation n’est plus active.")
        else:
            messages.info(request, "Votre arrivée avait déjà été confirmée.")

    return redirect("parking:reservation_list")


@login_required(login_url="parking:login")
@require_POST
def report_late_arrival(request, reservation_id):
    expire_late_reservations()
    reservation = get_object_or_404(
        Reservation.objects.select_related("spot__parking"),
        pk=reservation_id,
        user=request.user,
    )
    if reservation.status != Reservation.Status.ACTIVE:
        messages.error(request, "Cette réservation n’est plus active.")
    elif reservation.arrived_at is not None:
        messages.info(request, "Votre arrivée est déjà confirmée.")
    elif (
        reservation.starts_at is not None
        and reservation.starts_at > timezone.now()
    ):
        messages.error(
            request,
            "Vous pourrez signaler votre retard à partir de l’heure prévue.",
        )
    elif reservation.late_arrival_deadline is not None:
        messages.info(
            request,
            "Votre retard est déjà signalé jusqu’au "
            f"{timezone.localtime(reservation.late_arrival_deadline):%d/%m/%Y à %H:%M}.",
        )
    else:
        reported_at = timezone.now()
        deadline = reported_at + timedelta(
            minutes=reservation.spot.parking.late_arrival_grace_minutes
        )
        updated = Reservation.objects.filter(
            pk=reservation.pk,
            status=Reservation.Status.ACTIVE,
            arrived_at__isnull=True,
            late_arrival_deadline__isnull=True,
        ).update(
            late_arrival_reported_at=reported_at,
            late_arrival_deadline=deadline,
        )
        if updated:
            messages.success(
                request,
                "Votre retard est signalé. Vous pouvez confirmer votre arrivée "
                f"jusqu’au {timezone.localtime(deadline):%d/%m/%Y à %H:%M}.",
            )
        else:
            messages.info(request, "Votre retard a déjà été signalé.")

    return redirect("parking:reservation_list")


@login_required(login_url="parking:login")
@require_POST
def cancel_reservation(request, reservation_id):
    expire_late_reservations()
    reservation = get_object_or_404(
        Reservation,
        pk=reservation_id,
        user=request.user,
    )
    if reservation.status != Reservation.Status.ACTIVE:
        messages.error(request, "Cette réservation n’est plus active.")
        return redirect("parking:reservation_list")
    if reservation.arrived_at is not None:
        messages.error(
            request,
            "L’annulation n’est plus possible après la confirmation d’arrivée. "
            "Déclarez votre départ pour clôturer le stationnement.",
        )
        return redirect("parking:reservation_list")
    now = timezone.now()
    late_cancellation = (
        reservation.starts_at is not None
        and reservation.starts_at - now < timedelta(minutes=30)
    )
    reservation.status = Reservation.Status.CANCELLED
    reservation.ended_at = now
    if late_cancellation:
        reservation.amount_refunded = Decimal("0.00")
        reservation.amount_paid = (
            reservation.amount_charged or reservation.amount_paid
        )
    else:
        reservation.settle_final_amount()
    cancelled = Reservation.objects.filter(
        pk=reservation.pk,
        status=Reservation.Status.ACTIVE,
        arrived_at__isnull=True,
    ).update(
        status=reservation.status,
        ended_at=reservation.ended_at,
        amount_paid=reservation.amount_paid,
        amount_refunded=reservation.amount_refunded,
    )
    if not cancelled:
        reservation.refresh_from_db()
        if reservation.arrived_at is not None:
            messages.error(
                request,
                "L’annulation n’est plus possible après la confirmation d’arrivée. "
                "Déclarez votre départ pour clôturer le stationnement.",
            )
        else:
            messages.error(request, "Cette réservation n’est plus active.")
        return redirect("parking:reservation_list")
    _record_reservation_history(
        request.user,
        reservation,
        ReservationHistoryEntry.Action.CANCELLED,
        (
            f"Réservation annulée. Montant initial : "
            f"{reservation.amount_charged:.2f} €, remboursement : "
            f"{reservation.amount_refunded:.2f} €."
        ),
    )
    sync_spot_availability(reservation.spot_id)
    if reservation.amount_refunded > 0 and reservation.user_id:
        PaymentTransaction.objects.create(
            user=reservation.user,
            reservation=reservation,
            kind=PaymentTransaction.Kind.REFUND,
            amount=reservation.amount_refunded,
        )
    if late_cancellation:
        messages.success(
            request,
            "La réservation a été annulée dans les 30 minutes avant le début. "
            "Le montant prévu est conservé comme frais d’annulation.",
        )
    else:
        messages.success(request, "La réservation a bien été annulée et remboursée.")
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
    previous_charge = (
        reservation.amount_charged
        or reservation.amount_paid
        or Decimal("0.00")
    )
    reservation.status = Reservation.Status.COMPLETED
    reservation.ended_at = timezone.now()
    reservation.settle_final_amount()
    reservation.save()
    _record_reservation_history(
        request.user,
        reservation,
        ReservationHistoryEntry.Action.DEPARTED,
        (
            f"Départ déclaré. Durée réelle : "
            f"{reservation.actual_duration_display or 'non disponible'}, "
            f"montant final : {reservation.amount_paid:.2f} €."
        ),
    )
    additional_charge = (
        (reservation.amount_paid or Decimal("0.00")) - previous_charge
    )
    if additional_charge > 0 and reservation.user_id:
        PaymentTransaction.objects.create(
            user=reservation.user,
            reservation=reservation,
            kind=PaymentTransaction.Kind.RESERVATION,
            amount=additional_charge,
        )
    if reservation.amount_refunded > 0 and reservation.user_id:
        PaymentTransaction.objects.create(
            user=reservation.user,
            reservation=reservation,
            kind=PaymentTransaction.Kind.REFUND,
            amount=reservation.amount_refunded,
        )
    messages.success(
        request,
        "Votre départ est enregistré. Le montant final a été recalculé selon la durée réelle.",
    )
    return redirect("parking:reservation_summary", reservation_id=reservation.id)


@login_required(login_url="parking:login")
def reservation_summary(request, reservation_id):
    reservation = Reservation.objects.filter(
        pk=reservation_id,
        user=request.user,
    ).select_related("spot", "spot__parking").first()
    if reservation is None:
        if Reservation.objects.filter(pk=reservation_id).exists():
            raise Http404
        messages.info(
            request,
            "Cette réservation n’existe plus ou a été supprimée. "
            "Consultez la liste de vos réservations.",
        )
        return redirect("parking:reservation_list")
    review = ParkingReview.objects.filter(reservation=reservation).first()
    review_form = (
        ParkingReviewForm(instance=review)
        if reservation.status == Reservation.Status.COMPLETED
        else None
    )
    return render(
        request,
        "parking/reservation_summary.html",
        {
            "reservation": reservation,
            "review": review,
            "review_form": review_form,
            "cancellation_free": (
                reservation.starts_at is None
                or reservation.starts_at - timezone.now() >= timedelta(minutes=30)
            ),
            "reservation_history": reservation.history_entries.select_related(
                "actor"
            ).all(),
        },
    )


@login_required(login_url="parking:login")
@require_POST
def submit_parking_review(request, reservation_id):
    reservation = get_object_or_404(
        Reservation.objects.select_related("spot__parking"),
        pk=reservation_id,
        user=request.user,
        status=Reservation.Status.COMPLETED,
    )
    review = ParkingReview.objects.filter(reservation=reservation).first()
    form = ParkingReviewForm(request.POST, instance=review)
    if not form.is_valid():
        messages.error(request, "Vérifiez la note et le commentaire de votre avis.")
        return redirect("parking:reservation_summary", reservation_id=reservation.pk)
    review = form.save(commit=False)
    review.reservation = reservation
    review.parking = reservation.spot.parking
    review.user = request.user
    review.save()
    messages.success(request, "Merci, votre avis a été publié sur la fiche du parking.")
    return redirect("parking:reservation_summary", reservation_id=reservation.pk)

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
    occupied_reservations = Reservation.objects.filter(
        status=Reservation.Status.ACTIVE,
    ).filter(Q(arrived_at__isnull=False) | Q(starts_at__isnull=True))
    total_spots = Spot.objects.count()
    occupied = occupied_reservations.count()
    high_occupancy_parkings = []
    for parking in Parking.objects.prefetch_related("spots").all():
        total = parking.spots.count()
        if total:
            occupied_in_parking = occupied_reservations.filter(
                spot__parking=parking,
            ).count()
            rate = round(occupied_in_parking * 100 / total)
            if occupied_in_parking * 100 >= total * 80:
                high_occupancy_parkings.append(
                    {"parking": parking, "rate": rate, "occupied": occupied_in_parking, "total": total}
                )
    return render(
        request,
        "parking/agent_dashboard.html",
        {
            "occupied": occupied,
            "total_spots": total_spots,
            "occupancy_rate": round(occupied * 100 / total_spots) if total_spots else None,
            "high_occupancy_parkings": high_occupancy_parkings,
        },
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
@require_http_methods(["GET", "POST"])
def agent_spot_closures(request):
    form = ParkingSpotClosureForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        spot = form.cleaned_data["spot"]
        starts_at = form.cleaned_data["starts_at"]
        ends_at = form.cleaned_data["ends_at"]
        active_reservations = Reservation.objects.filter(
            spot=spot,
            status=Reservation.Status.ACTIVE,
        )
        reservation_conflict = False
        for reservation in active_reservations:
            reservation_start = (
                reservation.arrived_at
                or reservation.starts_at
                or reservation.created_at
            )
            reservation_end = reservation_start + timedelta(
                minutes=reservation.duration_minutes
            )
            if reservation_start < ends_at and reservation_end > starts_at:
                reservation_conflict = True
                break
        closure_conflict = ParkingSpotClosure.objects.filter(
            spot=spot,
            closed_at__isnull=True,
            starts_at__lt=ends_at,
            ends_at__gt=starts_at,
        ).exists()
        if reservation_conflict:
            form.add_error(
                None,
                "Un stationnement actif chevauche cette période. "
                "Choisissez une autre période.",
            )
        elif closure_conflict:
            form.add_error(
                None,
                "Une indisponibilité existe déjà sur cette place pour cette période.",
            )
        else:
            with transaction.atomic():
                closure = ParkingSpotClosure.objects.create(
                    spot=spot,
                    reason=form.cleaned_data["reason"],
                    starts_at=starts_at,
                    ends_at=ends_at,
                    created_by=request.user,
                )
                _record_agent_action(
                    request.user,
                    AgentActionLog.ActionType.SPOT_BLOCKED,
                    (
                        f"Place n°{spot.number} — {spot.parking.name} rendue "
                        f"indisponible du {timezone.localtime(starts_at):%d/%m/%Y %H:%M} "
                        f"au {timezone.localtime(ends_at):%d/%m/%Y %H:%M}. "
                        f"Motif : {closure.reason}"
                    ),
                    spot_closure=closure,
                )
            messages.success(request, "L’indisponibilité de la place a été enregistrée.")
            return redirect("parking:agent_spot_closures")

    now = timezone.now()
    closures = list(
        ParkingSpotClosure.objects.select_related(
            "spot__parking",
            "created_by",
        ).order_by("-created_at")[:100]
    )
    for closure in closures:
        closure.is_current = (
            closure.closed_at is None
            and closure.starts_at <= now < closure.ends_at
        )
        closure.is_upcoming = closure.closed_at is None and closure.starts_at > now
        closure.is_finished = closure.closed_at is not None or closure.ends_at <= now
    return render(
        request,
        "parking/agent_spot_closures.html",
        {"form": form, "closures": closures},
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
@require_POST
def agent_end_spot_closure(request, closure_id):
    with transaction.atomic():
        closure = get_object_or_404(
            ParkingSpotClosure.objects.select_for_update().select_related(
                "spot__parking"
            ),
            pk=closure_id,
            closed_at__isnull=True,
        )
        closure.closed_at = timezone.now()
        closure.save(update_fields=["closed_at"])
        notify_parking_availability(closure.spot_id)
        _record_agent_action(
            request.user,
            AgentActionLog.ActionType.SPOT_UNBLOCKED,
            (
                f"Indisponibilité levée pour la place n°{closure.spot.number} "
                f"du parking {closure.spot.parking.name}. Motif initial : "
                f"{closure.reason}"
            ),
            spot_closure=closure,
        )
    messages.success(request, "L’indisponibilité de la place a été levée.")
    return redirect("parking:agent_spot_closures")


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_action_history(request):
    filter_form = AgentActionFilterForm(request.GET or None)
    actions = AgentActionLog.objects.select_related(
        "actor",
        "report",
        "spot_closure__spot__parking",
        "contravention",
        "reservation__spot__parking",
    )
    if filter_form.is_valid():
        if filter_form.cleaned_data["action_type"]:
            actions = actions.filter(
                action_type=filter_form.cleaned_data["action_type"]
            )
        if filter_form.cleaned_data["date_from"]:
            actions = actions.filter(
                created_at__date__gte=filter_form.cleaned_data["date_from"]
            )
        if filter_form.cleaned_data["date_to"]:
            actions = actions.filter(
                created_at__date__lte=filter_form.cleaned_data["date_to"]
            )
    recent_actions = list(actions[:101])
    return render(
        request,
        "parking/agent_action_history.html",
        {
            "actions": recent_actions[:100],
            "has_more_actions": len(recent_actions) > 100,
            "filter_form": filter_form,
        },
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_parking_reports(request):
    all_reports = ParkingReport.objects.all()
    report_counts = {
        "new": all_reports.filter(status=ParkingReport.Status.NEW).count(),
        "in_progress": all_reports.filter(status=ParkingReport.Status.IN_PROGRESS).count(),
        "resolved": all_reports.filter(status=ParkingReport.Status.RESOLVED).count(),
        "refused": all_reports.filter(status=ParkingReport.Status.REFUSED).count(),
    }
    report_counts["open"] = report_counts["new"] + report_counts["in_progress"]
    report_counts["stale"] = all_reports.filter(
        status__in=[ParkingReport.Status.NEW, ParkingReport.Status.IN_PROGRESS],
        updated_at__lt=timezone.now() - timedelta(hours=24),
    ).count()
    filter_form = ParkingReportFilterForm(request.GET or None)
    reports = (
        ParkingReport.objects.select_related("user", "parking", "spot")
        .select_related("assigned_agent")
        .prefetch_related("comments__author")
        .order_by("-priority", "-updated_at", "-created_at")
    )
    if filter_form.is_valid():
        if filter_form.cleaned_data["search"]:
            reports = reports.filter(
                Q(title__icontains=filter_form.cleaned_data["search"])
                | Q(description__icontains=filter_form.cleaned_data["search"])
            )
        if filter_form.cleaned_data["status"]:
            reports = reports.filter(status=filter_form.cleaned_data["status"])
        if filter_form.cleaned_data["priority"]:
            reports = reports.filter(priority=filter_form.cleaned_data["priority"])
        if filter_form.cleaned_data["assigned_agent"]:
            reports = reports.filter(
                assigned_agent=filter_form.cleaned_data["assigned_agent"]
            )
        if filter_form.cleaned_data["parking"]:
            reports = reports.filter(parking=filter_form.cleaned_data["parking"])
        if filter_form.cleaned_data["modified_from"]:
            reports = reports.filter(
                updated_at__date__gte=filter_form.cleaned_data["modified_from"]
            )
        if filter_form.cleaned_data["modified_to"]:
            reports = reports.filter(
                updated_at__date__lte=filter_form.cleaned_data["modified_to"]
            )
    return render(
        request,
        "parking/agent_parking_reports.html",
        {
            "reports": reports,
            "open_reports": report_counts["open"],
            "report_counts": report_counts,
            "filter_form": filter_form,
        },
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
@require_http_methods(["GET", "POST"])
def agent_parking_report_detail(request, report_id):
    report = get_object_or_404(
        ParkingReport.objects.select_related(
            "user",
            "parking",
            "spot",
            "reservation",
            "assigned_agent",
        ),
        pk=report_id,
    )
    form = ParkingReportUpdateForm(
        request.POST or None,
        initial={
            "status": report.status,
            "priority": str(report.priority),
            "assigned_agent": report.assigned_agent_id,
        },
        current_status=report.status,
    )
    if request.method == "POST" and form.is_valid():
        previous_status = report.status
        previous_priority = report.priority
        previous_assignee_id = report.assigned_agent_id
        report.status = form.cleaned_data["status"]
        report.priority = int(form.cleaned_data["priority"] or report.priority)
        if "assigned_agent" in request.POST:
            report.assigned_agent = form.cleaned_data["assigned_agent"]
        message = form.cleaned_data["message"]
        with transaction.atomic():
            report.save(
                update_fields=[
                    "status",
                    "priority",
                    "assigned_agent",
                    "updated_at",
                ]
            )
            if message:
                comment = ParkingReportComment.objects.create(
                    report=report,
                    author=request.user,
                    message=message,
                )
                _record_agent_action(
                    request.user,
                    AgentActionLog.ActionType.REPORT_COMMENT,
                    (
                        f"Commentaire ajouté au signalement "
                        f"« {report.title or report.get_category_display()} » : "
                        f"{comment.message}"
                    ),
                    report=report,
                )
            if report.priority != previous_priority:
                _record_agent_action(
                    request.user,
                    AgentActionLog.ActionType.REPORT_PRIORITY,
                    (
                        f"Priorité de « {report.title or report.get_category_display()} » "
                        f"modifiée : {ParkingReport.Priority(previous_priority).label} "
                        f"→ {report.get_priority_display()}."
                    ),
                    report=report,
                )
            if report.assigned_agent_id != previous_assignee_id:
                _record_agent_action(
                    request.user,
                    AgentActionLog.ActionType.REPORT_ASSIGNED,
                    (
                        f"« {report.title or report.get_category_display()} » attribué à "
                        f"{report.assigned_agent.get_full_name() or report.assigned_agent.username}."
                        if report.assigned_agent
                        else f"Attribution retirée pour « {report.title or report.get_category_display()} »."
                    ),
                    report=report,
                )
                if report.assigned_agent_id and report.assigned_agent_id != request.user.pk:
                    UserNotification.objects.create(
                        user=report.assigned_agent,
                        title="Signalement attribué",
                        message=(
                            f"Le signalement « {report.title or report.get_category_display()} » "
                            f"vous a été attribué par {request.user.username}."
                        ),
                        url=reverse(
                            "parking:agent_parking_report_detail",
                            args=[report.pk],
                        ),
                    )
            if report.status != previous_status:
                _record_agent_action(
                    request.user,
                    AgentActionLog.ActionType.REPORT_STATUS,
                    (
                        f"Statut du signalement "
                        f"« {report.title or report.get_category_display()} » "
                        f"modifié : {ParkingReport.Status(previous_status).label} "
                        f"→ {report.get_status_display()}."
                    ),
                    report=report,
                )
            if report.user_id and (
                report.status != previous_status or message
            ):
                notification_text = (
                    f"Le statut de « {report.title or report.get_category_display()} » "
                    f"est maintenant « {report.get_status_display()} »."
                )
                if message:
                    notification_text += f" Réponse de l’équipe : {message}"
                UserNotification.objects.create(
                    user=report.user,
                    title="Mise à jour de votre signalement",
                    message=notification_text,
                    url=reverse(
                        "parking:user_parking_report_detail",
                        args=[report.pk],
                    ),
                )
        messages.success(request, "Le signalement a été mis à jour.")
        return redirect("parking:agent_parking_report_detail", report_id=report.pk)
    report_comments = report.comments.select_related("author").all()
    candidate_reports = (
        ParkingReport.objects.filter(
            parking=report.parking,
            category=report.category,
            created_at__gte=timezone.now() - timedelta(days=60),
        )
        .exclude(pk=report.pk)
        .select_related("parking")
        .order_by("-created_at")[:100]
    )
    report_words = {
        word.casefold()
        for word in report.title.split()
        if len(word) >= 4
    }
    similar_reports = []
    for candidate in candidate_reports:
        candidate_words = {
            word.casefold()
            for word in candidate.title.split()
            if len(word) >= 4
        }
        same_spot = report.spot_id is not None and candidate.spot_id == report.spot_id
        overlap = report_words and candidate_words and (
            len(report_words & candidate_words)
            / max(len(report_words | candidate_words), 1)
            >= 0.4
        )
        if same_spot or overlap:
            similar_reports.append(candidate)
    similar_reports = similar_reports[:5]
    return render(
        request,
        "parking/agent_parking_report_detail.html",
        {
            "report": report,
            "form": form,
            "report_comments": report_comments,
            "similar_reports": similar_reports,
        },
    )


@user_passes_test(
    lambda user: user.is_active and user.is_staff,
    login_url="admin:login",
)
def admin_dashboard(request):
    parkings = Parking.objects.annotate(
        total_spots=Count("spots", distinct=True),
        occupied_spots=Count(
            "spots__reservations",
            filter=Q(spots__reservations__status=Reservation.Status.ACTIVE),
            distinct=True,
        ),
    ).order_by("name")
    for parking in parkings:
        parking.free_spots = parking.total_spots - parking.occupied_spots
        parking.occupancy_rate = (
            round(parking.occupied_spots * 100 / parking.total_spots)
            if parking.total_spots
            else 0
        )
    return render(
        request,
        "parking/admin_dashboard.html",
        {
            "parkings": parkings,
            "active_reservations": Reservation.objects.filter(
                status=Reservation.Status.ACTIVE
            ).count(),
            "open_reports": ParkingReport.objects.exclude(
                status__in=[
                    ParkingReport.Status.RESOLVED,
                    ParkingReport.Status.REFUSED,
                ]
            ).count(),
            "waitlist_entries": ParkingWaitlist.objects.count(),
            "recent_reports": ParkingReport.objects.select_related(
                "user", "parking", "spot"
            ).order_by("-created_at")[:10],
        },
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
@never_cache
def agent_qr_verify(request, token):
    expire_late_reservations()
    verified = verify_reservation_qr(token)
    reservation = None
    arrival_started = False
    if verified is not None:
        with transaction.atomic():
            reservation = (
                Reservation.objects.select_for_update()
                .filter(
                    pk=verified["reservation_id"],
                    status=Reservation.Status.ACTIVE,
                )
                .select_related("spot", "spot__parking")
                .first()
            )
            if (
                reservation is not None
                and reservation.qr_verified_bucket != verified["bucket"]
            ):
                now = timezone.now()
                if reservation.starts_at is None or reservation.starts_at <= now:
                    if reservation.arrived_at is None:
                        reservation.arrived_at = now
                        arrival_started = True
                    reservation.qr_verified_bucket = verified["bucket"]
                    reservation.save(
                        update_fields=["arrived_at", "qr_verified_bucket"]
                    )
            elif reservation is not None:
                reservation = None

    return render(
        request,
        "parking/agent_qr_verify.html",
        {
            "reservation": reservation,
            "verification_code": (
                verified["verification_code"] if reservation is not None else None
            ),
            "arrival_started": arrival_started,
            "arrival_pending": bool(
                reservation is not None
                and reservation.arrived_at is None
                and reservation.starts_at is not None
                and reservation.starts_at > timezone.now()
            ),
        },
        status=200 if reservation is not None else 400,
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
            .select_related("spot", "spot__parking", "user")
            .first()
        )
        justification_registered = False
        is_pmr_spot = bool(reservation and reservation.spot.is_pmr)
        if is_pmr_spot and reservation.user_id:
            justification_registered = UserProfile.objects.filter(
                user_id=reservation.user_id,
                pmr_justification_registered=True,
            ).exists()
        duration_elapsed_minutes = None
        duration_exceeded = False
        if reservation and reservation.arrived_at:
            elapsed = timezone.now() - reservation.arrived_at
            duration_elapsed_minutes = max(0, int(elapsed.total_seconds() // 60))
            duration_exceeded = elapsed > timedelta(
                minutes=reservation.duration_minutes
            )

        expected_payment_amount = None
        payment_verified = False
        if reservation and reservation.spot.parking.hourly_rate is not None:
            expected_payment_amount = (
                reservation.spot.parking.hourly_rate
                * reservation.duration_minutes
                / 60
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            payment_verified = (
                reservation.payment_reference is not None
                and reservation.amount_paid == expected_payment_amount
            )

        is_compliant = bool(
            reservation
            and reservation.arrived_at
            and not duration_exceeded
            and payment_verified
            and (not is_pmr_spot or justification_registered)
        )
        result = {
            "plate": plate,
            "reservation": reservation,
            "is_pmr_spot": is_pmr_spot,
            "pmr_justification_registered": justification_registered,
            "duration_elapsed_minutes": duration_elapsed_minutes,
            "duration_exceeded": duration_exceeded,
            "payment_verified": payment_verified,
            "expected_payment_amount": expected_payment_amount,
            "is_compliant": is_compliant,
        }
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
    form = ContraventionForm(request.POST, request.FILES)
    plate = request.POST.get("plate", "").strip().upper()
    if not form.is_valid():
        messages.error(
            request,
            "Les informations de la contravention sont invalides. "
            "Vérifiez le type, le motif et le montant.",
        )
        return redirect(f"{reverse('parking:agent_plate_check')}?plate={plate}")

    plate = form.cleaned_data["plate"]
    if Reservation.objects.filter(
        plate=plate,
        status=Reservation.Status.ACTIVE,
    ).exists():
        messages.error(request, "Ce véhicule possède une réservation active.")
        return redirect(f"{reverse('parking:agent_plate_check')}?plate={plate}")

    parking = form.cleaned_data["parking"]
    with transaction.atomic():
        contravention = Contravention.objects.create(
            agent=request.user,
            plate=plate,
            fine_type=form.cleaned_data["fine_type"],
            reason=form.cleaned_data["reason"],
            parking=parking,
            spot=form.cleaned_data["spot"],
            amount=form.cleaned_data["amount"],
            comment=form.cleaned_data["comment"],
            photo=form.cleaned_data.get("photo"),
            latitude=parking.latitude,
            longitude=parking.longitude,
            user_id=(
                Reservation.objects.filter(plate=plate)
                .order_by("-created_at")
                .values_list("user_id", flat=True)
                .first()
            ),
        )
        _record_agent_action(
            request.user,
            AgentActionLog.ActionType.CONTRAVENTION_CREATED,
            (
                f"Contravention {contravention.number} créée pour "
                f"{plate} au parking {parking.name}, place "
                f"n°{contravention.spot.number}."
            ),
            contravention=contravention,
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
    previous_charge = (
        reservation.amount_charged
        or reservation.amount_paid
        or Decimal("0.00")
    )
    reservation.status = Reservation.Status.COMPLETED
    reservation.ended_at = timezone.now()
    reservation.settle_final_amount()
    reservation.save()
    _record_reservation_history(
        request.user,
        reservation,
        ReservationHistoryEntry.Action.AGENT_CLOSED,
        (
            f"Stationnement clôturé par l’agent. Durée réelle : "
            f"{reservation.actual_duration_display or 'non disponible'}, "
            f"montant final : {reservation.amount_paid:.2f} €."
        ),
    )
    _record_agent_action(
        request.user,
        AgentActionLog.ActionType.RESERVATION_CLOSED,
        (
            f"Stationnement clôturé pour {reservation.plate}, parking "
            f"{reservation.spot.parking.name}, place n°{reservation.spot.number}."
        ),
        reservation=reservation,
    )
    additional_charge = (
        (reservation.amount_paid or Decimal("0.00")) - previous_charge
    )
    if additional_charge > 0 and reservation.user_id:
        PaymentTransaction.objects.create(
            user=reservation.user,
            reservation=reservation,
            kind=PaymentTransaction.Kind.RESERVATION,
            amount=additional_charge,
        )
    if reservation.amount_refunded > 0 and reservation.user_id:
        PaymentTransaction.objects.create(
            user=reservation.user,
            reservation=reservation,
            kind=PaymentTransaction.Kind.REFUND,
            amount=reservation.amount_refunded,
        )
    messages.success(request, "Le stationnement a bien été clôturé.")
    return redirect(f"{reverse('parking:agent_plate_check')}?plate={reservation.plate}")


@user_passes_test(_is_agent, login_url="parking:agent_login")
@require_POST
def agent_refuse_reservation(request, reservation_id):
    form = AgentReservationRefusalForm(request.POST)
    if not form.is_valid():
        reservation = get_object_or_404(
            Reservation,
            pk=reservation_id,
            status=Reservation.Status.ACTIVE,
            arrived_at__isnull=True,
        )
        messages.error(request, "Saisissez un motif pour refuser la réservation.")
        return redirect(
            f"{reverse('parking:agent_plate_check')}?plate={reservation.plate}"
        )

    with transaction.atomic():
        reservation = get_object_or_404(
            Reservation.objects.select_for_update().select_related(
                "spot__parking",
                "user",
            ),
            pk=reservation_id,
            status=Reservation.Status.ACTIVE,
            arrived_at__isnull=True,
        )
        charged_amount = (
            reservation.amount_charged
            or reservation.amount_paid
            or Decimal("0.00")
        )
        reason = form.cleaned_data["reason"]
        reservation.status = Reservation.Status.REFUSED
        reservation.ended_at = timezone.now()
        reservation.amount_paid = Decimal("0.00")
        reservation.amount_refunded = charged_amount
        reservation.save(
            update_fields=[
                "status",
                "ended_at",
                "amount_paid",
                "amount_refunded",
            ]
        )
        _record_reservation_history(
            request.user,
            reservation,
            ReservationHistoryEntry.Action.AGENT_REFUSED,
            f"Réservation refusée par l’agent. Motif : {reason}",
        )
        _record_agent_action(
            request.user,
            AgentActionLog.ActionType.RESERVATION_REFUSED,
            (
                f"Réservation de {reservation.plate} refusée. Motif : {reason}"
            ),
            reservation=reservation,
        )
        if charged_amount > 0:
            PaymentTransaction.objects.create(
                user=reservation.user,
                reservation=reservation,
                kind=PaymentTransaction.Kind.REFUND,
                amount=charged_amount,
            )
        if reservation.user_id:
            UserNotification.objects.create(
                user=reservation.user,
                title="Votre réservation a été refusée",
                message=(
                    f"Votre réservation au parking {reservation.spot.parking.name} "
                    f"a été refusée par un agent. Motif : {reason} "
                    f"Le montant de {charged_amount:.2f} € a été remboursé "
                    "dans le paiement simulé."
                ),
                url=reverse(
                    "parking:reservation_summary",
                    args=[reservation.pk],
                ),
            )

    messages.success(
        request,
        f"La réservation de {reservation.plate} a été refusée et "
        f"{charged_amount:.2f} € ont été remboursés.",
    )
    return redirect(
        f"{reverse('parking:agent_plate_check')}?plate={reservation.plate}"
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_contraventions(request):
    contraventions = (
        Contravention.objects.select_related("agent", "parking", "spot")
        .order_by("-created_at")
    )
    return render(
        request,
        "parking/agent_contraventions.html",
        {"contraventions": contraventions},
    )


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_contravention_photo(request, contravention_id):
    contravention = get_object_or_404(
        Contravention,
        pk=contravention_id,
    )
    if not contravention.photo:
        raise Http404("Aucune photo n’est associée à cette contravention.")
    content_type, _ = mimetypes.guess_type(contravention.photo.name)
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise Http404("Le fichier associé n’est pas une image autorisée.")
    response = FileResponse(
        contravention.photo.open("rb"),
        content_type=content_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@user_passes_test(_is_agent, login_url="parking:agent_login")
def agent_contravention_detail(request, contravention_id):
    contravention = get_object_or_404(
        Contravention.objects.select_related("agent", "parking", "spot"),
        pk=contravention_id,
    )
    return render(
        request,
        "parking/contravention_detail.html",
        {"contravention": contravention, "is_agent_view": True},
    )


@login_required(login_url="parking:login")
@require_POST
def pay_contravention(request, contravention_id):
    with transaction.atomic():
        contravention = get_object_or_404(
            Contravention.objects.select_for_update(),
            pk=contravention_id,
            user=request.user,
        )
        if contravention.paid_at is not None:
            messages.info(request, "Cette contravention est déjà payée.")
        else:
            contravention.paid_at = timezone.now()
            contravention.payment_reference = uuid.uuid4()
            contravention.save(update_fields=["paid_at", "payment_reference"])
            PaymentTransaction.objects.create(
                user=request.user,
                contravention=contravention,
                kind=PaymentTransaction.Kind.CONTRAVENTION,
                amount=contravention.amount,
            )
            messages.success(
                request,
                "Paiement simulé enregistré. Aucun débit réel n’a été effectué.",
            )
    return redirect(
        "parking:user_contravention_detail",
        contravention_id=contravention_id,
    )


@login_required(login_url="parking:login")
def user_financial_history(request):
    transactions = PaymentTransaction.objects.filter(
        user=request.user
    ).select_related("reservation__spot__parking", "contravention")
    total_expenses = sum(
        (transaction.amount for transaction in transactions if transaction.kind != PaymentTransaction.Kind.REFUND),
        Decimal("0.00"),
    )
    total_refunds = sum(
        (transaction.amount for transaction in transactions if transaction.kind == PaymentTransaction.Kind.REFUND),
        Decimal("0.00"),
    )
    return render(
        request,
        "parking/user_financial_history.html",
        {
            "transactions": transactions,
            "total_expenses": total_expenses,
            "total_refunds": total_refunds,
            "net_total": total_expenses - total_refunds,
        },
    )


@login_required(login_url="parking:login")
def user_contraventions(request):
    contraventions = Contravention.objects.filter(user=request.user).select_related(
        "parking", "spot"
    ).order_by("-created_at")
    return render(
        request,
        "parking/user_contraventions.html",
        {"contraventions": contraventions},
    )


@login_required(login_url="parking:login")
def user_contravention_detail(request, contravention_id):
    contravention = get_object_or_404(
        Contravention.objects.select_related("parking", "spot"),
        pk=contravention_id,
        user=request.user,
    )
    appeal_deadline = contravention.created_at + timedelta(days=30)
    can_contest = (
        contravention.status == Contravention.Status.ISSUED
        and timezone.now() <= appeal_deadline
    )
    form = ContraventionOppositionForm() if can_contest else None
    return render(
        request,
        "parking/contravention_detail.html",
        {
            "contravention": contravention,
            "is_agent_view": False,
            "can_contest": can_contest,
            "appeal_deadline": appeal_deadline,
            "form": form,
        },
    )


@login_required(login_url="parking:login")
@require_POST
def contest_contravention(request, contravention_id):
    contravention = get_object_or_404(
        Contravention,
        pk=contravention_id,
        user=request.user,
    )
    detail_url = reverse(
        "parking:user_contravention_detail",
        args=[contravention.id],
    )
    appeal_deadline = contravention.created_at + timedelta(days=30)
    if (
        contravention.status != Contravention.Status.ISSUED
        or timezone.now() > appeal_deadline
    ):
        messages.error(request, "Le délai d’opposition est dépassé ou l’avis est déjà contesté.")
        return redirect(detail_url)

    form = ContraventionOppositionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Saisissez le motif de votre opposition.")
        return redirect(detail_url)

    contravention.opposition_reason = form.cleaned_data["reason"]
    contravention.opposition_submitted_at = timezone.now()
    contravention.status = Contravention.Status.CONTESTING
    contravention.save(
        update_fields=["opposition_reason", "opposition_submitted_at", "status"]
    )
    messages.success(request, "Votre opposition a été enregistrée.")
    return redirect(detail_url)


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
            (
                r
                for r in reservations
                if r.status == Reservation.Status.ACTIVE
                and (r.arrived_at is not None or r.starts_at is None)
            ),
            key=lambda r: r.spot.number,
        )
        pmr_spots = [spot for spot in spots if spot.is_pmr]
        pmr_active_reservations = [
            reservation
            for reservation in active_reservations
            if reservation.spot.is_pmr
        ]
        events = []
        for reservation in reservations:
            entry_at = reservation.arrived_at
            if entry_at is None and reservation.starts_at is None:
                entry_at = reservation.created_at
            if entry_at is None:
                continue
            entry_label = "Arrivée" if reservation.arrived_at is not None else "Réservation"
            events.append((entry_at, 1, entry_label, reservation))
            if reservation.ended_at:
                events.append(
                    (
                        reservation.ended_at,
                        -1,
                        end_labels.get(reservation.status, "Fin"),
                        reservation,
                    )
                )
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
                "high_occupancy": bool(
                    total_spots and occupied_now * 100 >= total_spots * 80
                ),
                "pmr_total": len(pmr_spots),
                "pmr_occupied": len(pmr_active_reservations),
                "pmr_free": len(pmr_spots) - len(pmr_active_reservations),
                "pmr_reservations": pmr_active_reservations,
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
    chart_bars = [
        {
            "x": 70 + index * 160,
            "center": 110 + index * 160,
            "y": 150 - round(entry["rate"] * 1.4),
            "height": round(entry["rate"] * 1.4),
            "rate": entry["rate"],
            "label": (
                entry["parking"].name
                if len(entry["parking"].name) <= 19
                else f"{entry['parking'].name[:17]}…"
            ),
        }
        for index, entry in enumerate(stats)
    ]
    return render(
        request,
        "parking/agent_stats.html",
        {
            "stats": stats,
            "summary": summary,
            "chart_bars": chart_bars,
            "chart_width": max(540, 140 * len(chart_bars) + 100),
            "movements_limit": STATS_MOVEMENTS_LIMIT,
        },
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

    events = []
    for reservation in reservations.only(
        "created_at",
        "starts_at",
        "arrived_at",
        "ended_at",
        "status",
    ):
        entry_at = reservation.arrived_at
        if entry_at is None and reservation.starts_at is None:
            entry_at = reservation.created_at
        if entry_at is None:
            continue
        events.append((entry_at, 1))
        ended_at = reservation.ended_at
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
    expire_late_reservations()
    filter_form = ParkingFilterForm(request.GET or None)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    now = timezone.now()
    parkings = Parking.objects.annotate(
        total_spots_count=Count("spots"),
        available_spots_count=_available_spot_count(now),
        available_pmr_spots_count=_available_spot_count(now, pmr_only=True),
        last_availability_update=Max("spots__availability_updated_at"),
    )

    if profile.prefers_covered_parking:
        parkings = parkings.filter(is_covered=True)
    if profile.requires_ev_charging:
        parkings = parkings.filter(has_ev_charging=True)
    if profile.vehicle_height_m is not None:
        parkings = parkings.filter(
            Q(max_vehicle_height_m__isnull=True)
            | Q(max_vehicle_height_m__gte=profile.vehicle_height_m)
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
    waitlisted_parking_ids = set(
        ParkingWaitlist.objects.filter(user=request.user).values_list(
            "parking_id",
            flat=True,
        )
    )

    parking_data = list(
        parkings.values(
            "id",
            "name",
            "address",
            "latitude",
            "longitude",
            "available_pmr_spots_count",
            "available_spots_count",
            "total_spots_count",
            "last_availability_update",
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
            "waitlisted_parking_ids": waitlisted_parking_ids,
        },
    )
