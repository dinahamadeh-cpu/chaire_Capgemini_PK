from .models import UserNotification, UserProfile


def user_roles(request):
    color_vision_mode = False
    unread_notification_count = 0
    if request.user.is_authenticated:
        color_vision_mode = (
            UserProfile.objects.filter(user=request.user)
            .values_list("color_vision_mode", flat=True)
            .first()
            or False
        )
        unread_notification_count = UserNotification.objects.filter(
            user=request.user,
            read_at__isnull=True,
        ).count()
    return {
        "is_agent": request.user.is_authenticated
        and request.user.groups.filter(name="Agents").exists(),
        "color_vision_mode": color_vision_mode,
        "unread_notification_count": unread_notification_count,
    }
