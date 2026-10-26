import logging
import os
from django.conf import settings

logger = logging.getLogger(__name__)

_firebase_app = None


def get_firebase_app():
    """Initializes and returns the singleton Firebase Admin app."""
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    import firebase_admin
    from firebase_admin import credentials

    # 1. Check if default app is already initialized
    try:
        _firebase_app = firebase_admin.get_app()
        return _firebase_app
    except ValueError:
        pass

    # 2. Check for explicit service account credential path
    cred_path = getattr(settings, "FIREBASE_CREDENTIALS_PATH", None) or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin initialized with certificate from %s", cred_path)
        return _firebase_app

    # 3. Check for application default credentials
    try:
        cred = credentials.ApplicationDefault()
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin initialized with ApplicationDefault credentials")
        return _firebase_app
    except Exception as e:
        logger.warning(
            "Firebase Admin credentials not configured (%s). FCM push will be skipped/mocked in dev.",
            e,
        )
        return None


def send_fcm_push(user, notification):
    """
    Sends FCM HTTP v1 push notification to all active devices registered for user.
    Updates notification delivery_status and delivery_attempts.
    """
    from .models import DeviceFCMToken, Notification

    tokens_qs = DeviceFCMToken.objects.filter(user=user, is_active=True)
    if not tokens_qs.exists():
        notification.delivery_status = Notification.DeliveryStatus.NO_DEVICE
        notification.delivery_attempts += 1
        notification.save(update_fields=["delivery_status", "delivery_attempts"])
        return {"status": "no_device", "sent_count": 0}

    app = get_firebase_app()
    if app is None:
        # Credentials not provided - record as queued/accepted for dev without crash
        notification.delivery_status = Notification.DeliveryStatus.QUEUED
        notification.delivery_attempts += 1
        notification.delivery_error = "Firebase credentials not configured on backend."
        notification.save(update_fields=["delivery_status", "delivery_attempts", "delivery_error"])
        return {"status": "unconfigured", "sent_count": 0}

    from firebase_admin import messaging

    tokens = list(tokens_qs.values_list("token", flat=True))
    data_payload = {
        "notification_id": str(notification.id),
        "notification_type": str(notification.notification_type),
        "pet_id": str(notification.pet_id) if notification.pet_id else "",
    }
    # Stringify any custom metadata
    for k, v in notification.metadata.items():
        if k not in data_payload:
            data_payload[str(k)] = str(v)

    multicast_message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=notification.title,
            body=notification.message,
        ),
        data=data_payload,
        tokens=tokens,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="pet_health_alerts",
                sound="default",
                click_action="OPEN_ALERT",
            ),
        ),
    )

    try:
        response = messaging.send_each_for_multicast(multicast_message)
        success_count = response.success_count
        failure_count = response.failure_count

        # Deactivate expired/invalid tokens
        for idx, resp in enumerate(response.responses):
            if not resp.success and resp.exception:
                err_code = getattr(resp.exception, "code", "")
                if "UNREGISTERED" in str(err_code) or "INVALID_ARGUMENT" in str(err_code):
                    bad_token = tokens[idx]
                    DeviceFCMToken.objects.filter(token=bad_token).update(is_active=False)

        notification.delivery_attempts += 1
        if success_count > 0:
            notification.delivery_status = Notification.DeliveryStatus.ACCEPTED
            notification.delivery_error = f"Sent to {success_count} device(s). {failure_count} failed." if failure_count > 0 else ""
        else:
            notification.delivery_status = Notification.DeliveryStatus.FAILED
            notification.delivery_error = f"All {failure_count} devices failed."

        notification.save(update_fields=["delivery_status", "delivery_attempts", "delivery_error"])
        return {"status": "completed", "sent_count": success_count, "failed_count": failure_count}
    except Exception as exc:
        logger.error("Error sending FCM multicast: %s", exc)
        notification.delivery_attempts += 1
        notification.delivery_status = Notification.DeliveryStatus.FAILED
        notification.delivery_error = str(exc)[:500]
        notification.save(update_fields=["delivery_status", "delivery_attempts", "delivery_error"])
        return {"status": "error", "error": str(exc)}
