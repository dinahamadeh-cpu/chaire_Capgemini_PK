def user_roles(request):
    return {
        "is_agent": request.user.is_authenticated
        and request.user.groups.filter(name="Agents").exists(),
    }
