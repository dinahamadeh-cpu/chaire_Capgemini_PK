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

    def __init__(self, *args, has_saved_payment_method=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_saved_payment_method = has_saved_payment_method
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
        return cleaned_data

    def clean_plate(self):
        return self.cleaned_data["plate"].strip().upper()
