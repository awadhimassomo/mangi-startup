from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from workspace.models import PushSubscription
from workspace.push_service import send_web_push


class Command(BaseCommand):
    help = "Diagnose phone notifications: list a user's devices and send each a test push."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Username or email of the person to test.")

    def handle(self, *args, **options):
        User = get_user_model()
        ident = options["username"]
        user = User.objects.filter(username__iexact=ident).first() or User.objects.filter(email__iexact=ident).first()
        if not user:
            raise CommandError(f"No user '{ident}'.")
        subs = PushSubscription.objects.filter(user=user)
        self.stdout.write(f"{user}: {subs.count()} subscribed device(s).")
        if not subs:
            self.stdout.write(self.style.WARNING(
                "No devices. On the phone, open the app and tap 'Turn on' in the notifications bar "
                "(or Settings → Enable Mobile Push), and allow notifications."))
            return
        for sub in subs:
            ok, info = send_web_push(sub, {
                "title": "Test notification", "body": "If you can see this, push works.",
                "url": "/notifications/", "badge_count": 1,
            })
            self.stdout.write(f"- {sub.user_agent[:60] or 'device'}: {'SENT' if ok else 'FAILED'} ({info})")
