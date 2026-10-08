from django import forms

from .models import plate_validator


class ReservationForm(forms.Form):
    plate = forms.CharField(
        max_length=9,
        label="Plaque d'immatriculation",
        validators=[plate_validator],
        widget=forms.TextInput(attrs={"placeholder": "AA-123-AA"}),
    )

    def clean_plate(self):
        return self.cleaned_data["plate"].strip().upper()
