from django.contrib import admin

from .models import Parking, Reservation, Spot


admin.site.register(Parking)
admin.site.register(Spot)
admin.site.register(Reservation)
