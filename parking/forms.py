import re

from decimal import Decimal

from django import forms
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm

from .models import (
    Contravention,
    Parking,
    UserProfile,
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
        choices=(("", "Choisir un modèle"), *UserProfile.VehicleModel.choices),
    )
    class Meta(UserCreationForm.Meta):
        fields = ("username", "email")

    def clean_phone_number(self):
        return clean_phone_number(self.cleaned_data["phone_number"])


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
    )
    pmr_justification_registered = forms.BooleanField(
        label="J’ai un justificatif PMR à présenter en cas de contrôle",
        required=False,
    )
    notifications_enabled = forms.BooleanField(
        label="Recevoir les rappels de fin de stationnement",
        required=False,
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
    payment_method = forms.ChoiceField(
        choices=(
            ("saved", "Utiliser le moyen de paiement déjà enregistré"),
            ("new", "Nouveau moyen de paiement"),
        ),
        required=False,
        initial="new",
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, has_saved_payment_method=False, max_duration_minutes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_saved_payment_method = has_saved_payment_method
        self.max_duration_minutes = max_duration_minutes
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
        if has_saved_payment_method:
            self.fields["payment_method"].initial = "saved"
        for field_name in ("card_number", "expiration_date", "security_code"):
            self.fields[field_name].required = False

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get("payment_method") or "new"
        cleaned_data["payment_method"] = payment_method

        if payment_method == "saved":
            if not self.has_saved_payment_method:
                self.add_error(
                    "payment_method",
                    "Aucun moyen de paiement simulé n'est enregistré.",
                )
        else:
            for field_name in ("card_number", "expiration_date", "security_code"):
                if not cleaned_data.get(field_name):
                    self.add_error(field_name, "Ce champ est obligatoire.")
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

    def clean_plate(self):
        return self.cleaned_data["plate"].strip().upper()

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
