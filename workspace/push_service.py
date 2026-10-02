import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.conf import settings
from py_vapid import Vapid, b64urlencode
from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

VAPID_PEM_PATH = Path(settings.BASE_DIR) / "vapid_private.pem"
VAPID_CLAIMS_EMAIL = getattr(settings, "DEFAULT_FROM_EMAIL", "admin@fundos.app")


def get_or_create_vapid():
    """Load or generate persistent VAPID keypair for Web Push."""
    vapid = Vapid()
    if VAPID_PEM_PATH.exists():
        try:
            vapid = Vapid.from_file(str(VAPID_PEM_PATH))
            return vapid
        except Exception as e:
            logger.warning("Could not read existing VAPID key: %s. Generating new key.", e)

    vapid.generate_keys()
    with open(VAPID_PEM_PATH, "wb") as f:
        f.write(vapid.private_pem())
    return vapid


def get_vapid_public_key():
    """Returns base64url-encoded uncompressed public key for browser push subscription."""
    vapid = get_or_create_vapid()
    raw_point = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    encoded = b64urlencode(raw_point)
    if isinstance(encoded, bytes):
        return encoded.decode("utf-8")
    return str(encoded)


def send_web_push(subscription, payload_dict, ttl=86400):
    """
    Sends a web push notification to a single PushSubscription instance.
    Deletes the subscription if expired (410 Gone / 404 Not Found).
    """
    vapid = get_or_create_vapid()
    sub_info = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth,
        },
    }
    
    claims = {
        "sub": f"mailto:{VAPID_CLAIMS_EMAIL.split()[-1].strip('<>')}"
    }

    try:
        response = webpush(
            subscription_info=sub_info,
            data=json.dumps(payload_dict),
            vapid_private_key=str(VAPID_PEM_PATH),
            vapid_claims=claims,
            ttl=ttl,
        )
        return True, response.status_code
    except WebPushException as ex:
        logger.warning("WebPush failed: %s", ex)
        # 404 or 410 indicates endpoint expired / unsubscribed
        if ex.response is not None and ex.response.status_code in (404, 410):
            subscription.delete()
        return False, str(ex)
    except Exception as ex:
        logger.error("Unexpected error sending web push: %s", ex)
        return False, str(ex)


def send_push_to_user(user, title, body, link=None, tag=None, icon=None, badge=None):
    """Dispatches a push notification to all active browser subscriptions for a user."""
    from .models import PushSubscription

    subscriptions = PushSubscription.objects.filter(user=user)
    if not subscriptions.exists():
        return 0

    payload = {
        "title": title,
        "body": body,
        "url": link or "/notifications/",
        "tag": tag or "fundos-notif",
        "icon": icon or "/static/workspace/icon-192.png",
        "badge": badge or "/static/workspace/badge-72.png",
    }

    success_count = 0
    for sub in subscriptions:
        success, _ = send_web_push(sub, payload)
        if success:
            success_count += 1

    return success_count
