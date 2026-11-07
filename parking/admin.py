from django.contrib import admin

from .models import (
    Contravention,
    AgentActionLog,
    Favorite,
    Parking,
    ParkingHoursException,
    ParkingReport,
    ParkingReview,
    ParkingSpotClosure,
    ParkingWaitlist,
    PaymentTransaction,
    Reservation,
    ReservationHistoryEntry,
    RecurringReservationPlan,
    SavedVehicle,
    Spot,
    UserNotification,
    UserProfile,
)


admin.site.register(Parking)
admin.site.register(Spot)
admin.site.register(Reservation)


@admin.register(Contravention)
class ContraventionAdmin(admin.ModelAdmin):
    exclude = ("latitude", "longitude")


admin.site.register(Favorite)
admin.site.register(UserProfile)
admin.site.register(ParkingWaitlist)
admin.site.register(UserNotification)
admin.site.register(PaymentTransaction)
admin.site.register(ParkingSpotClosure)
admin.site.register(AgentActionLog)
admin.site.register(ParkingHoursException)
admin.site.register(ParkingReview)
admin.site.register(ReservationHistoryEntry)
admin.site.register(RecurringReservationPlan)
admin.site.register(SavedVehicle)


@admin.register(ParkingReport)
class ParkingReportAdmin(admin.ModelAdmin):
    list_display = (
        "category",
        "parking",
        "spot",
        "reservation",
        "user",
        "status",
        "priority",
        "assigned_agent",
        "created_at",
    )
    list_filter = ("status", "category", "priority", "parking", "assigned_agent")
    search_fields = ("description", "user__username", "parking__name")
    readonly_fields = ("created_at", "updated_at")
