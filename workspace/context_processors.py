from .models import Notification
from .utils import get_current_membership, get_current_startup


def workspace_context(request):
    if not request.user.is_authenticated:
        return {}

    unread = Notification.objects.filter(user=request.user, is_read=False).count()
    return {
        "current_startup": get_current_startup(request.user),
        "current_membership": get_current_membership(request.user),
        "unread_notifications": unread,
    }
