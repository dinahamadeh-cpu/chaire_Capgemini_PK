from django.contrib import admin

from .models import Contravention, Favorite, Parking, Reservation, Spot


admin.site.register(Parking)
admin.site.register(Spot)
admin.site.register(Reservation)
admin.site.register(Contravention)
admin.site.register(Favorite)
