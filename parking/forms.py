from django import forms

from .models import plate_validator


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
                "autocomplete": "off",
                "required": True,
                "class": "numeric-only",
            }
        ),
    )


class ReservationForm(PaymentDetailsForm):
    duration_hours = forms.IntegerField(
        min_value=1,
        max_value=32767,
        label="Nombre d'heures",
        widget=forms.NumberInput(attrs={"min": "1", "step": "1", "required": True}),
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
        duration = cleaned_data.get("duration_hours")
        if self.max_duration_minutes is not None and duration and duration * 60 > self.max_duration_minutes:
            self.add_error("duration_hours", "La durée dépasse la limite de ce parking.")
        return cleaned_data

    def clean_plate(self):
        return self.cleaned_data["plate"].strip().upper()


class ContraventionForm(forms.Form):
    plate = forms.CharField(
        max_length=9,
        label="Plaque d'immatriculation",
        validators=[plate_validator],
        widget=forms.HiddenInput(),
    )
    reason = forms.CharField(
        max_length=255,
        label="Motif",
        widget=forms.TextInput(
            attrs={"placeholder": "Ex. stationnement sans réservation"}
        ),
    )

    def clean_plate(self):
        return self.cleaned_data["plate"].strip().upper()

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Le motif est obligatoire.")
        return reason


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