from django.contrib import admin

from .models import Contravention, Favorite, Parking, Reservation, Spot, UserProfile


admin.site.register(Parking)
admin.site.register(Spot)
admin.site.register(Reservation)


@admin.register(Contravention)
class ContraventionAdmin(admin.ModelAdmin):
    exclude = ("latitude", "longitude")


admin.site.register(Favorite)
admin.site.register(UserProfile)
