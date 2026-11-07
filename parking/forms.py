import re

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.utils import timezone

from .models import (
    AgentActionLog,
    Contravention,
    Favorite,
    ParkingReview,
    ParkingSpotClosure,
    ParkingReport,
    Parking,
    RecurringReservationPlan,
    Reservation,
    SavedVehicle,
    Spot,
    UserProfile,
    VehicleType,
    plate_validator,
)


def clean_phone_number(value):
    phone = value.strip()
    if not phone:
        return phone
    if not re.fullmatch(r"\+?[0-9][0-9 .()-]{8,18}", phone):
        raise forms.ValidationError("Saisissez un numéro de téléphone valide.")
    digits = "".join(character for character in phone if character.isdigit())
    if not 10 <= len(digits) <= 15:
        raise forms.ValidationError(
            "Saisissez un numéro contenant entre 10 et 15 chiffres."
        )
    return phone


class SignupForm(UserCreationForm):
    email = forms.EmailField(label="Adresse e-mail")
    phone_number = forms.CharField(
        label="Numéro de téléphone (facultatif)",
        required=False,
        max_length=20,
        widget=forms.TextInput(
            attrs={"type": "tel", "autocomplete": "tel", "placeholder": "06 12 34 56 78"}
        ),
    )
    vehicle_model = forms.ChoiceField(
        label="Modèle du véhicule (facultatif)",
        required=False,
        choices=(
            ("", "Choisir un modèle"),
            *(
                choice
                for choice in UserProfile.VehicleModel.choices
                if UserProfile.VEHICLE_MODEL_TYPES[choice[0]] == VehicleType.CAR
            ),
        ),
    )
    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

    def clean_phone_number(self):
        return clean_phone_number(self.cleaned_data["phone_number"])


class VehicleModelSelect(forms.Select):
    def __init__(self, *args, **kwargs):
        attrs = kwargs.setdefault("attrs", {})
        attrs["data-vehicle-model-select"] = "true"
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name,
            value,
            label,
            selected,
            index,
            subindex=subindex,
            attrs=attrs,
        )
        model = str(value)
        if model in UserProfile.VEHICLE_MODEL_TYPES:
            option["attrs"]["data-vehicle-type"] = UserProfile.VEHICLE_MODEL_TYPES[model]
            option["attrs"]["data-suggested-height"] = str(
                UserProfile.VEHICLE_MODEL_HEIGHTS[model]
            )
        return option


class UserProfileForm(forms.Form):
    email = forms.EmailField(
        label="Adresse e-mail",
        required=False,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    phone_number = forms.CharField(
        label="Numéro de téléphone",
        required=False,
        max_length=20,
        widget=forms.TextInput(
            attrs={"type": "tel", "autocomplete": "tel", "placeholder": "06 12 34 56 78"}
        ),
    )
    vehicle_model = forms.ChoiceField(
        label="Modèle du véhicule (facultatif)",
        required=False,
        choices=(("", "Choisir un modèle"), *UserProfile.VehicleModel.choices),
        widget=VehicleModelSelect,
    )
    vehicle_type = forms.ChoiceField(
        label="Type de véhicule",
        choices=VehicleType.choices,
        required=False,
    )
    pmr_justification_registered = forms.BooleanField(
        label="J’ai un justificatif PMR à présenter en cas de contrôle",
        required=False,
    )
    notifications_enabled = forms.BooleanField(
        label="Recevoir les rappels de fin de stationnement",
        required=False,
    )
    prefers_covered_parking = forms.BooleanField(
        label="Limiter la recherche aux parkings couverts",
        required=False,
    )
    vehicle_height_m = forms.DecimalField(
        label="Hauteur de mon véhicule (m)",
        required=False,
        min_value=Decimal("0.50"),
        max_value=Decimal("9.99"),
        max_digits=4,
        decimal_places=2,
    )
    monthly_budget_limit = forms.DecimalField(
        label="Alerte de budget mensuel (€)",
        required=False,
        min_value=Decimal("0.01"),
        max_digits=8,
        decimal_places=2,
    )
    requires_ev_charging = forms.BooleanField(
        label="Rechercher uniquement les parkings avec recharge électrique",
        required=False,
    )
    color_vision_mode = forms.BooleanField(
        label="Mode daltonien",
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            vehicle_type = (
                self.data.get("vehicle_type")
                or self.initial.get("vehicle_type")
                or VehicleType.CAR
            )
            model_choices = (
                choice
                for choice in UserProfile.VehicleModel.choices
                if UserProfile.VEHICLE_MODEL_TYPES[choice[0]] == vehicle_type
            )
        else:
            model_choices = iter(UserProfile.VehicleModel.choices)
        self.fields["vehicle_model"].choices = (
            ("", "Choisir un modèle"),
            *model_choices,
        )

    def clean_phone_number(self):
        return clean_phone_number(self.cleaned_data["phone_number"])


class AccountDeletionForm(forms.Form):
    confirm_deletion = forms.BooleanField(
        label="Je comprends que cette action est définitive",
        required=True,
        error_messages={
            "required": "Confirmez que vous souhaitez supprimer définitivement votre compte."
        },
    )
    username_confirmation = forms.CharField(
        label="Saisissez votre nom de compte pour confirmer",
        strip=True,
    )

    def __init__(self, *args, username, **kwargs):
        super().__init__(*args, **kwargs)
        self.username = username

    def clean_username_confirmation(self):
        username = self.cleaned_data["username_confirmation"]
        if username != self.username:
            raise forms.ValidationError(
                "Le nom saisi ne correspond pas à votre nom de compte."
            )
        return username


class PaymentDetailsForm(forms.Form):
    name = forms.CharField(
        label="Nom du moyen de paiement",
        max_length=50,
        widget=forms.TextInput(
            attrs={"placeholder": "Exemple", "autocomplete": "off"}
        ),
    )
    card_number = forms.RegexField(
        regex=r"^[0-9]{13,19}$",
        max_length=19,
        min_length=13,
        label="Numéro de carte",
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "pattern": "[0-9]{13,19}",
                "maxlength": "19",
                "placeholder": "13 à 19 chiffres",
                "autocomplete": "off",
                "required": True,
                "class": "numeric-only",
            }
        ),
    )
    expiration_date = forms.RegexField(
        regex=r"^(0[1-9]|1[0-2])/[0-9]{2}$",
        max_length=5,
        min_length=5,
        label="Date d'expiration (MM/AA)",
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "pattern": "(0[1-9]|1[0-2])/[0-9]{2}",
                "maxlength": "5",
                "placeholder": "MM/AA",
                "autocomplete": "off",
                "required": True,
                "class": "expiration-date",
            }
        ),
    )
    security_code = forms.RegexField(
        regex=r"^[0-9]{3,4}$",
        max_length=4,
        min_length=3,
        label="Cryptogramme",
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "pattern": "[0-9]{3,4}",
                "maxlength": "4",
                "placeholder": "3 ou 4 chiffres",
                "autocomplete": "off",
                "required": True,
                "class": "numeric-only",
            }
        ),
    )


class ReservationForm(PaymentDetailsForm):
    starts_at = forms.DateTimeField(
        label="Date et heure prévues",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local", "required": True},
        ),
    )
    duration_minutes = forms.IntegerField(
        min_value=0,
        max_value=2147483647,
        label="Durée",
        required=False,
        widget=forms.HiddenInput(),
    )
    duration_days = forms.IntegerField(
        min_value=0,
        max_value=2147483647,
        label="Jours",
        required=False,
        widget=forms.NumberInput(attrs={"min": "0", "step": "1"}),
    )
    duration_hours = forms.IntegerField(
        min_value=0,
        max_value=2147483647,
        label="Heures",
        required=False,
        widget=forms.NumberInput(attrs={"min": "0", "step": "1"}),
    )
    duration_extra_minutes = forms.IntegerField(
        min_value=0,
        max_value=2147483647,
        label="Minutes",
        required=False,
        widget=forms.NumberInput(attrs={"min": "0", "step": "1"}),
    )
    plate = forms.CharField(
        max_length=9,
        label="Plaque d'immatriculation",
        validators=[plate_validator],
        widget=forms.TextInput(attrs={"placeholder": "AA-123-AA"}),
    )
    saved_vehicle = forms.ModelChoiceField(
        label="Véhicule enregistré",
        queryset=SavedVehicle.objects.none(),
        required=False,
        empty_label="Saisir une plaque",
    )
    payment_method = forms.ChoiceField(
        choices=(("new", "Nouveau moyen de paiement"),),
        required=False,
        initial="new",
        widget=forms.RadioSelect,
    )

    def __init__(
        self,
        *args,
        saved_payment_methods=(),
        max_duration_minutes=None,
        user=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields.pop("name")
        self.saved_method_values = {
            f"saved_{method.pk}": method for method in saved_payment_methods
        }
        self.fields["payment_method"].choices = (
            *(
                (
                    value,
                    f"Utiliser le moyen de paiement déjà enregistré : {method.name}",
                )
                for value, method in self.saved_method_values.items()
            ),
            ("new", "Nouveau moyen de paiement"),
        )
        self.max_duration_minutes = max_duration_minutes
        self.user_id = getattr(user, "pk", None)
        self.fields["saved_vehicle"].queryset = (
            SavedVehicle.objects.filter(user=user).order_by("plate")
            if user is not None
            else SavedVehicle.objects.none()
        )
        self.fields["saved_vehicle"].label_from_instance = (
            lambda vehicle: (
                f"{vehicle.plate} — {vehicle.get_vehicle_type_display()}"
            )
        )
        self.fields["plate"].required = False
        self.show_duration_days = (
            max_duration_minutes is None or max_duration_minutes >= 1440
        )
        if max_duration_minutes is not None:
            self.fields["duration_days"].widget.attrs["max"] = (
                max_duration_minutes // 1440
            )
            self.fields["duration_hours"].widget.attrs["max"] = (
                max_duration_minutes // 60
            )
            self.fields["duration_extra_minutes"].widget.attrs["max"] = (
                max_duration_minutes
            )
            if not self.show_duration_days:
                self.fields["duration_days"].widget = forms.HiddenInput()
        if not self.is_bound:
            self.initial.setdefault("duration_days", 0)
            self.initial.setdefault("duration_hours", 1)
            self.initial.setdefault("duration_extra_minutes", 0)
        if self.saved_method_values:
            self.fields["payment_method"].initial = next(
                iter(self.saved_method_values)
            )
        for field_name in ("card_number", "expiration_date", "security_code"):
            self.fields[field_name].required = False

    def clean(self):
        cleaned_data = super().clean()
        payment_method = (
            cleaned_data.get("payment_method")
            or self.data.get(self.add_prefix("payment_method"))
            or "new"
        )
        cleaned_data["payment_method"] = payment_method

        if payment_method.startswith("saved"):
            if payment_method not in self.saved_method_values:
                self.add_error(
                    "payment_method",
                    "Aucun moyen de paiement simulé n'est enregistré.",
                )
        else:
            for field_name in ("card_number", "expiration_date", "security_code"):
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, "Ce champ est obligatoire.")
        selected_vehicle = cleaned_data.get("saved_vehicle")
        plate = cleaned_data.get("plate", "").strip().upper()
        if selected_vehicle:
            if selected_vehicle.user_id != getattr(self, "user_id", None):
                self.add_error("saved_vehicle", "Choisissez un véhicule de votre compte.")
            cleaned_data["plate"] = selected_vehicle.plate
        elif not plate:
            self.add_error("plate", "Saisissez une plaque ou choisissez un véhicule enregistré.")
        else:
            cleaned_data["plate"] = plate
        starts_at = cleaned_data.get("starts_at")
        if starts_at is not None and starts_at < timezone.now():
            self.add_error(
                    "starts_at",
                    "La date prévue doit être maintenant ou dans le futur.",
            )
        components_submitted = any(
            name in self.data
            for name in (
                "duration_days",
                "duration_hours",
                "duration_extra_minutes",
            )
        )
        if components_submitted:
            days = cleaned_data.get("duration_days") or 0
            hours = cleaned_data.get("duration_hours") or 0
            minutes = cleaned_data.get("duration_extra_minutes") or 0
            duration_minutes = days * 1440 + hours * 60 + minutes
        else:
            duration_minutes = cleaned_data.get("duration_minutes") or 0

        if duration_minutes < 1:
            self.add_error(
                "duration_minutes",
                "Saisissez une durée supérieure à zéro.",
            )
        elif duration_minutes > 2147483647:
            self.add_error(
                "duration_minutes",
                "La durée saisie est trop longue.",
            )
        elif (
            self.max_duration_minutes is not None
            and duration_minutes > self.max_duration_minutes
        ):
            self.add_error(
                "duration_minutes",
                "La durée dépasse la limite de ce parking.",
            )
        else:
            cleaned_data["duration_minutes"] = duration_minutes
        return cleaned_data

    def clean_plate(self):
        return self.cleaned_data["plate"].strip().upper()


class ContraventionForm(forms.Form):
    FINE_PRESETS = {
        "no_reservation": ("Stationnement sans réservation", Decimal("50.00")),
        "pmr_abuse": ("Usage abusif d’une place PMR", Decimal("135.00")),
        "overstay": ("Dépassement de la durée réservée", Decimal("35.00")),
        "wrong_spot": ("Stationnement sur une place non autorisée", Decimal("50.00")),
        "obstructing": ("Stationnement gênant ou bloquant", Decimal("75.00")),
        "no_payment": ("Paiement ou titre de stationnement absent", Decimal("50.00")),
    }

    plate = forms.CharField(
        max_length=9,
        label="Plaque d'immatriculation",
        validators=[plate_validator],
        widget=forms.HiddenInput(),
    )
    fine_type = forms.ChoiceField(
        choices=(("", "Choisir un type"), *Contravention.FineType.choices),
        label="Type de contravention",
    )
    reason = forms.CharField(
        max_length=255,
        label="Motif",
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "Ex. stationnement sans réservation"}
        ),
    )
    parking = forms.ModelChoiceField(
        queryset=Parking.objects.order_by("name"),
        label="Parking",
        empty_label="Choisir un parking",
    )
    spot = forms.ModelChoiceField(
        queryset=Spot.objects.select_related("parking").order_by("parking__name", "number"),
        label="Place concernée",
        empty_label="Choisir d’abord un parking",
    )
    amount = forms.DecimalField(
        label="Montant (€)",
        min_value=Decimal("30.00"),
        max_value=Decimal("200.00"),
        required=False,
        decimal_places=2,
        max_digits=5,
    )
    comment = forms.CharField(
        label="Commentaire (facultatif)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    photo = forms.FileField(
        label="Photo (facultative, visible uniquement côté agent)",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": "image/jpeg,image/png,image/webp", "capture": "environment"}
        ),
    )

    def clean_plate(self):
        return self.cleaned_data["plate"].strip().upper()

    def clean_spot(self):
        spot = self.cleaned_data["spot"]
        parking = self.cleaned_data.get("parking")
        if parking and spot and spot.parking_id != parking.pk:
            raise forms.ValidationError(
                "Choisissez une place appartenant au parking sélectionné."
            )
        return spot

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo is None:
            return None
        if photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("La photo ne peut pas dépasser 5 Mo.")
        header = photo.read(12)
        photo.seek(0)
        valid_image = (
            header.startswith(b"\xff\xd8\xff")
            or header.startswith(b"\x89PNG\r\n\x1a\n")
            or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        )
        if not valid_image:
            raise forms.ValidationError(
                "Téléversez une image JPEG, PNG ou WebP valide."
            )
        return photo

    def clean(self):
        cleaned_data = super().clean()
        fine_type = cleaned_data.get("fine_type")
        if fine_type in self.FINE_PRESETS:
            reason, amount = self.FINE_PRESETS[fine_type]
            cleaned_data["reason"] = reason
            cleaned_data["amount"] = amount
        elif fine_type == Contravention.FineType.OTHER:
            reason = (cleaned_data.get("reason") or "").strip()
            amount = cleaned_data.get("amount")
            if not reason:
                self.add_error("reason", "Le motif est obligatoire pour le type « Autres ».")
            else:
                cleaned_data["reason"] = reason
            if amount is None:
                self.add_error("amount", "Le montant est obligatoire pour le type « Autres ».")
        return cleaned_data

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()
        if self.cleaned_data.get("fine_type") == Contravention.FineType.OTHER and not reason:
            raise forms.ValidationError("Le motif est obligatoire.")
        return reason

    def clean_amount(self):
        return self.cleaned_data.get("amount")


class ContraventionOppositionForm(forms.Form):
    reason = forms.CharField(
        label="Motif de l’opposition",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Le motif de l’opposition est obligatoire.")
        return reason


class ParkingReportForm(forms.ModelForm):
    title = forms.CharField(
        label="Titre du signalement",
        max_length=150,
        widget=forms.TextInput(
            attrs={"placeholder": "Ex. Borne de paiement hors service"}
        ),
    )
    reservation = forms.ModelChoiceField(
        queryset=Reservation.objects.none(),
        label="Réservation concernée",
        required=False,
    )
    priority = forms.ChoiceField(
        label="Priorité souhaitée",
        choices=ParkingReport.Priority.choices,
        initial=ParkingReport.Priority.NORMAL,
        required=False,
        help_text=(
            "L’équipe peut réévaluer la priorité après vérification. "
            "Choisissez « Urgente » seulement en cas de danger immédiat."
        ),
    )

    class Meta:
        model = ParkingReport
        fields = (
            "title",
            "parking",
            "spot",
            "reservation",
            "category",
            "description",
            "photo",
            "priority",
        )
        labels = {
            "title": "Titre du signalement",
            "parking": "Parking concerné",
            "spot": "Place concernée (facultatif)",
            "reservation": "Réservation concernée (obligatoire pour un objet oublié ou un véhicule endommagé)",
            "category": "Type de problème",
            "description": "Description",
            "photo": "Photo facultative (JPEG, PNG ou WebP, 5 Mo maximum)",
            "priority": "Priorité souhaitée",
        }
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 4, "maxlength": 1000}
            ),
            "photo": forms.ClearableFileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["parking"].queryset = Parking.objects.order_by("name")
        self.fields["spot"].queryset = Spot.objects.select_related(
            "parking"
        ).order_by("parking__name", "number")
        if user is not None:
            self.fields["reservation"].queryset = (
                Reservation.objects.filter(user=user)
                .select_related("spot__parking")
                .order_by("-created_at")
            )
        self.fields["spot"].required = False

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo is None:
            return None
        if photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("La photo ne peut pas dépasser 5 Mo.")
        header = photo.read(12)
        photo.seek(0)
        if not (
            header.startswith(b"\xff\xd8\xff")
            or header.startswith(b"\x89PNG\r\n\x1a\n")
            or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        ):
            raise forms.ValidationError(
                "Téléversez une image JPEG, PNG ou WebP valide."
            )
        return photo

    def clean(self):
        cleaned_data = super().clean()
        title = cleaned_data.get("title")
        if title:
            cleaned_data["title"] = title.strip()
        parking = cleaned_data.get("parking")
        spot = cleaned_data.get("spot")
        category = cleaned_data.get("category")
        reservation = cleaned_data.get("reservation")
        if not cleaned_data.get("priority"):
            cleaned_data["priority"] = ParkingReport.Priority.NORMAL
        if parking and spot and spot.parking_id != parking.pk:
            self.add_error("spot", "La place sélectionnée n’appartient pas à ce parking.")
        if category in (
            ParkingReport.Category.FORGOTTEN_ITEM,
            ParkingReport.Category.VEHICLE_DAMAGE,
        ):
            if reservation is None:
                self.add_error(
                    "reservation",
                    "Sélectionnez la réservation associée à ce signalement.",
                )
            elif parking and parking.pk != reservation.spot.parking_id:
                self.add_error(
                    "reservation",
                    "La réservation sélectionnée ne concerne pas ce parking.",
                )
            else:
                cleaned_data["parking"] = reservation.spot.parking
                if spot and spot.pk != reservation.spot_id:
                    self.add_error(
                        "spot",
                        "La place ne correspond pas à la réservation sélectionnée.",
                    )
        if category == ParkingReport.Category.DANGER:
            cleaned_data["priority"] = ParkingReport.Priority.URGENT
        return cleaned_data


class ParkingReportUpdateForm(forms.Form):
    status = forms.ChoiceField(
        label="État du signalement",
        choices=ParkingReport.Status.choices,
    )
    message = forms.CharField(
        label="Commentaire visible par l’usager",
        max_length=1000,
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Expliquez les vérifications ou les actions réalisées.",
            }
        ),
    )
    confirm_status_change = forms.BooleanField(
        label="Je confirme cette décision",
        required=False,
    )
    priority = forms.ChoiceField(
        label="Priorité",
        choices=ParkingReport.Priority.choices,
        required=False,
    )
    assigned_agent = forms.ModelChoiceField(
        label="Agent responsable",
        queryset=get_user_model().objects.none(),
        required=False,
        empty_label="Non attribué",
    )

    def __init__(self, *args, current_status=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_status = current_status
        self.fields["assigned_agent"].queryset = get_user_model().objects.filter(
            is_active=True,
            groups__name="Agents",
        ).distinct().order_by("username")

    def clean_message(self):
        return self.cleaned_data["message"].strip()

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("status") == ParkingReport.Status.REFUSED
            and not cleaned_data.get("message")
        ):
            self.add_error(
                "message",
                "Expliquez la raison du refus dans le commentaire.",
            )
        if (
            cleaned_data.get("status")
            in (ParkingReport.Status.RESOLVED, ParkingReport.Status.REFUSED)
            and cleaned_data.get("status") != self.current_status
            and not cleaned_data.get("confirm_status_change")
        ):
            self.add_error(
                "confirm_status_change",
                "Confirmez cette décision avant de l’enregistrer.",
            )
        return cleaned_data


class ParkingReportReplyForm(forms.Form):
    message = forms.CharField(
        label="Votre réponse",
        max_length=1000,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Ajoutez des précisions ou répondez au suivi de l’équipe.",
            }
        ),
    )

    def clean_message(self):
        message = self.cleaned_data["message"].strip()
        if not message:
            raise forms.ValidationError("Votre réponse ne peut pas être vide.")
        return message


class AgentReservationRefusalForm(forms.Form):
    reason = forms.CharField(
        label="Motif du refus",
        max_length=400,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Expliquez pourquoi cette réservation ne peut pas être honorée.",
            }
        ),
    )

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Le motif du refus est obligatoire.")
        return reason


class ParkingReportFilterForm(forms.Form):
    search = forms.CharField(
        label="Rechercher un titre",
        required=False,
        max_length=150,
    )
    status = forms.ChoiceField(
        label="État",
        choices=[("", "Tous les états"), *ParkingReport.Status.choices],
        required=False,
    )
    priority = forms.ChoiceField(
        label="Priorité",
        choices=[("", "Toutes les priorités"), *ParkingReport.Priority.choices],
        required=False,
    )
    assigned_agent = forms.ModelChoiceField(
        label="Agent responsable",
        queryset=get_user_model().objects.none(),
        required=False,
        empty_label="Tous les agents",
    )
    modified_from = forms.DateField(
        label="Modifié depuis",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    modified_to = forms.DateField(
        label="Modifié jusqu’au",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_agent"].queryset = get_user_model().objects.filter(
            is_active=True,
            groups__name="Agents",
        ).distinct().order_by("username")

    def clean_search(self):
        return self.cleaned_data["search"].strip()

    def clean(self):
        cleaned_data = super().clean()
        modified_from = cleaned_data.get("modified_from")
        modified_to = cleaned_data.get("modified_to")
        if modified_from and modified_to and modified_from > modified_to:
            self.add_error(
                "modified_to",
                "La date de fin doit être égale ou postérieure à la date de début.",
            )
        return cleaned_data
    parking = forms.ModelChoiceField(
        label="Parking",
        queryset=Parking.objects.order_by("name"),
        required=False,
        empty_label="Tous les parkings",
    )


class ParkingSpotClosureForm(forms.Form):
    parking = forms.ModelChoiceField(
        label="Parking",
        queryset=Parking.objects.order_by("name"),
        empty_label="Choisir un parking",
    )
    spot = forms.ModelChoiceField(
        label="Place",
        queryset=Spot.objects.select_related("parking").order_by(
            "parking__name", "number"
        ),
        empty_label="Choisir une place",
    )
    reason = forms.CharField(
        label="Motif de l’indisponibilité",
        max_length=250,
        widget=forms.TextInput(
            attrs={"placeholder": "Ex. Travaux de maintenance"}
        ),
    )
    starts_at = forms.DateTimeField(
        label="Début",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )
    ends_at = forms.DateTimeField(
        label="Fin prévue",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            parking_id = self.data.get(self.add_prefix("parking"))
            if parking_id:
                self.fields["spot"].queryset = self.fields["spot"].queryset.filter(
                    parking_id=parking_id
                )

    def clean_reason(self):
        return self.cleaned_data["reason"].strip()

    def clean(self):
        cleaned_data = super().clean()
        parking = cleaned_data.get("parking")
        spot = cleaned_data.get("spot")
        starts_at = cleaned_data.get("starts_at")
        ends_at = cleaned_data.get("ends_at")
        if parking and spot and spot.parking_id != parking.pk:
            self.add_error("spot", "La place ne correspond pas au parking choisi.")
        if starts_at and ends_at and starts_at >= ends_at:
            self.add_error(
                "ends_at",
                "La fin de l’indisponibilité doit suivre son début.",
            )
        if starts_at and starts_at < timezone.now():
            self.add_error(
                "starts_at",
                "Le début de l’indisponibilité ne peut pas être dans le passé.",
            )
        return cleaned_data


class AgentActionFilterForm(forms.Form):
    action_type = forms.ChoiceField(
        label="Type d’action",
        choices=[("", "Toutes les actions"), *AgentActionLog.ActionType.choices],
        required=False,
    )
    date_from = forms.DateField(
        label="Depuis le",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        label="Jusqu’au",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")
        if date_from and date_to and date_from > date_to:
            self.add_error("date_to", "La date de fin doit suivre la date de début.")
        return cleaned_data


class SavedVehicleForm(forms.ModelForm):
    model = forms.ChoiceField(
        label="Modèle (facultatif)",
        required=False,
        choices=(("", "---------"), *UserProfile.VehicleModel.choices),
        widget=VehicleModelSelect(),
    )

    class Meta:
        model = SavedVehicle
        fields = ("plate", "vehicle_type", "model")
        labels = {
            "plate": "Plaque d’immatriculation",
            "vehicle_type": "Type de véhicule",
            "model": "Modèle (facultatif)",
        }
        widgets = {
            "plate": forms.TextInput(attrs={"placeholder": "AA-123-AA"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_plate(self):
        return self.cleaned_data["plate"].strip().upper()

    def clean(self):
        cleaned_data = super().clean()
        model = cleaned_data.get("model")
        vehicle_type = cleaned_data.get("vehicle_type")
        if model and UserProfile.VEHICLE_MODEL_TYPES.get(model) != vehicle_type:
            self.add_error("model", "Ce modèle ne correspond pas au type de véhicule.")
        return cleaned_data


class ParkingWaitlistForm(forms.Form):
    starts_at = forms.DateTimeField(
        label="Début du créneau recherché",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )
    ends_at = forms.DateTimeField(
        label="Fin du créneau recherché",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get("starts_at")
        ends_at = cleaned_data.get("ends_at")
        now = timezone.now()
        if starts_at and starts_at < now:
            self.add_error("starts_at", "Le début du créneau doit être dans le futur.")
        if starts_at and ends_at and starts_at >= ends_at:
            self.add_error("ends_at", "La fin doit suivre le début du créneau.")
        return cleaned_data


class ParkingAvailabilityAlertForm(forms.Form):
    threshold = forms.IntegerField(
        label="M’avertir quand il y a au moins ce nombre de places libres",
        min_value=1,
    )


class RecurringReservationPlanForm(forms.ModelForm):
    class Meta:
        model = RecurringReservationPlan
        fields = ("parking", "vehicle", "weekday", "start_time", "duration_minutes")
        labels = {
            "parking": "Parking",
            "vehicle": "Véhicule",
            "weekday": "Jour de la semaine",
            "start_time": "Heure habituelle",
            "duration_minutes": "Durée (minutes)",
        }
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "duration_minutes": forms.NumberInput(attrs={"min": 1}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["parking"].queryset = Parking.objects.order_by("name")
        self.fields["vehicle"].queryset = (
            SavedVehicle.objects.filter(user=user).order_by("plate")
            if user is not None
            else SavedVehicle.objects.none()
        )

    def clean(self):
        cleaned_data = super().clean()
        parking = cleaned_data.get("parking")
        duration = cleaned_data.get("duration_minutes")
        vehicle = cleaned_data.get("vehicle")
        if vehicle and vehicle.user_id != getattr(self.user, "pk", None):
            self.add_error("vehicle", "Choisissez un véhicule de votre compte.")
        if parking and duration and parking.max_duration_minutes is not None:
            if duration > parking.max_duration_minutes:
                self.add_error("duration_minutes", "La durée dépasse la limite de ce parking.")
        return cleaned_data


class ParkingReviewForm(forms.ModelForm):
    class Meta:
        model = ParkingReview
        fields = ("rating", "comment")
        labels = {"rating": "Note sur 5", "comment": "Votre avis (facultatif)"}
        widgets = {"comment": forms.Textarea(attrs={"rows": 4, "maxlength": 1000})}


class AccountPasswordResetForm(PasswordResetForm):
    def clean_email(self):
        email = self.cleaned_data["email"]
        if not any(self.get_users(email)):
            raise forms.ValidationError(
                "Aucun compte n’est associé à cette adresse e-mail."
            )
        return email

class ParkingFilterForm(forms.Form):
    min_rate = forms.DecimalField(
        label="Tarif minimum",
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=5,
    )

    max_rate = forms.DecimalField(
        label="Tarif maximum",
        required=False,
        min_value=0,
        decimal_places=2,
        max_digits=5,
    )


    minimum_duration = forms.IntegerField(
        label="Durée souhaitée en heures",
        required=False,
        min_value=1,
    )

    minimum_available_spots = forms.IntegerField(
        label="Places disponibles minimum",
        required=False,
        min_value=0,
    )

    open_at = forms.TimeField(
        label="Ouvert à partir de",
        required=False,
        input_formats=["%H:%M"],
        widget=forms.TimeInput(
            format="%H:%M",
            attrs={"type": "time"},
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        min_rate = cleaned_data.get("min_rate")
        max_rate = cleaned_data.get("max_rate")

        if min_rate is not None and max_rate is not None and min_rate > max_rate:
            self.add_error(
                "max_rate",
                "Le tarif maximum doit être supérieur ou égal au tarif minimum.",
            )

        return cleaned_data
