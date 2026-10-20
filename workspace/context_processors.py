from .models import Notification
from .utils import get_current_membership, get_current_startup


def workspace_context(request):
    if not request.user.is_authenticated:
        return {}

    unread = Notification.objects.filter(user=request.user, is_read=False).count()
    startup = get_current_startup(request.user)
    pending_review = 0
    if request.user.is_staff:
        from .models import PostedOpportunity

        pending_review = PostedOpportunity.objects.filter(
            review_status=PostedOpportunity.ReviewStatus.PENDING
        ).count()
    return {
        "pending_review_count": pending_review,
        "profile_completion": startup.profile_completion if startup else 100,
        "current_startup": startup,
        "current_membership": get_current_membership(request.user),
        "unread_notifications": unread,
    }
