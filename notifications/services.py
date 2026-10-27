import logging
import os
from datetime import timedelta
from typing import Dict, Any, Optional

from django.conf import settings
from django.utils import timezone

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


def send_fcm_push(user, notification) -> Dict[str, Any]:
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
        # Credentials not provided - record as queued for dev without crashing
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


class NotificationDispatcher:
    """
    Centralized, duplicate-safe notification dispatcher for pet health events.
    Enforces cooldown windows and duplicate prevention.
    """

    ANOMALY_COOLDOWN_HOURS = 2

    @classmethod
    def dispatch_activity_anomaly(
        cls,
        pet,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
        is_simulation: bool = False,
    ) -> Optional[Any]:
        """
        Triggers an immediate activity anomaly alert if:
        1. Telemetry is REAL (is_simulation=False).
        2. No duplicate anomaly alert was dispatched for this pet within ANOMALY_COOLDOWN_HOURS.
        """
        from .models import Notification

        if is_simulation:
            logger.info("Skipping real push notification for simulated anomaly on %s", pet.name)
            return None

        now = timezone.now()
        cooldown_threshold = now - timedelta(hours=cls.ANOMALY_COOLDOWN_HOURS)

        # Duplicate/Cooldown check
        recent_exists = Notification.objects.filter(
            pet=pet,
            notification_type=Notification.NotificationType.ACTIVITY_ANOMALY,
            created_at__gte=cooldown_threshold,
        ).exists()

        if recent_exists:
            logger.info(
                "Anomaly notification for %s suppressed by %dh cooldown window",
                pet.name,
                cls.ANOMALY_COOLDOWN_HOURS,
            )
            return None

        notif = Notification.objects.create(
            user=pet.owner,
            pet=pet,
            notification_type=Notification.NotificationType.ACTIVITY_ANOMALY,
            title=f"Activity Alert: {pet.name}",
            message=reason,
            metadata=metadata or {},
        )
        send_fcm_push(pet.owner, notif)
        return notif

    @classmethod
    def dispatch_daily_summary(
        cls,
        pet,
        daily_metrics: Dict[str, Any],
        target_date: Optional[timezone.datetime.date] = None,
    ) -> Optional[Any]:
        """
        Dispatches daily summary notification if:
        1. Sufficient real data exists (is_sufficient=True, samples >= 30).
        2. No daily summary notification has already been sent for this pet and date.
        """
        from .models import Notification

        date = target_date or timezone.now().date()
        date_str = str(date)

        if not daily_metrics.get("is_sufficient"):
            logger.info(
                "Skipping daily summary notification for %s on %s: insufficient samples (%d)",
                pet.name,
                date_str,
                daily_metrics.get("total_samples", 0),
            )
            return None

        # Duplicate check: check if daily_summary notification already sent for this pet & date
        already_sent = Notification.objects.filter(
            pet=pet,
            notification_type=Notification.NotificationType.DAILY_SUMMARY,
            metadata__summary_date=date_str,
        ).exists()

        if already_sent:
            logger.info("Daily summary for %s on %s already dispatched", pet.name, date_str)
            return None

        active_mins = daily_metrics.get("total_moving_minutes", 0)
        rest_mins = daily_metrics.get("rest_minutes", 0)
        rest_hrs = round(rest_mins / 60.0, 1)

        title = f"Daily Summary: {pet.name}"
        message = (
            f"{pet.name} logged {active_mins} active minutes and {rest_hrs} hours of rest today."
        )

        notif = Notification.objects.create(
            user=pet.owner,
            pet=pet,
            notification_type=Notification.NotificationType.DAILY_SUMMARY,
            title=title,
            message=message,
            metadata={
                "summary_date": date_str,
                "active_minutes": active_mins,
                "rest_minutes": rest_mins,
                "samples": daily_metrics.get("total_samples", 0),
            },
        )
        send_fcm_push(pet.owner, notif)
        return notif

    @classmethod
    def dispatch_weekly_insights(
        cls,
        pet,
        analytics: Dict[str, Any],
        week_end_date: Optional[timezone.datetime.date] = None,
    ) -> Optional[Any]:
        """
        Dispatches weekly health insights notification if:
        1. Baseline is established or multi-day real data exists.
        2. No weekly notification has already been sent for this pet for this week ending date.
        """
        from .models import Notification

        end_date = week_end_date or timezone.now().date()
        end_date_str = str(end_date)

        weekly_summary = analytics.get("weekly_summary", [])
        total_samples = sum(day.get("total_samples", 0) for day in weekly_summary)
        days_with_data = sum(1 for day in weekly_summary if day.get("total_samples", 0) >= 20)

        if days_with_data < 3 or total_samples < 60:
            logger.info(
                "Skipping weekly insights for %s on %s: insufficient data (%d days with data)",
                pet.name,
                end_date_str,
                days_with_data,
            )
            return None

        # Duplicate check: check if weekly notification already sent for this pet in past 6 days
        cooldown_cutoff = timezone.now() - timedelta(days=6)
        already_sent = Notification.objects.filter(
            pet=pet,
            notification_type=Notification.NotificationType.WEEKLY_INSIGHTS,
            created_at__gte=cooldown_cutoff,
        ).exists()

        if already_sent:
            logger.info("Weekly insights for %s recently dispatched (within 6 days)", pet.name)
            return None

        avg_daily_active = round(
            sum(d.get("total_moving_minutes", 0) for d in weekly_summary) / max(len(weekly_summary), 1)
        )

        title = f"Weekly Insights: {pet.name}"
        insights = analytics.get("personalized_insights", [])
        top_insight = insights[0] if insights else f"{pet.name} averaged {avg_daily_active} mins/day active."
        message = f"Weekly wellness review: {top_insight}"

        notif = Notification.objects.create(
            user=pet.owner,
            pet=pet,
            notification_type=Notification.NotificationType.WEEKLY_INSIGHTS,
            title=title,
            message=message,
            metadata={
                "week_end_date": end_date_str,
                "days_with_data": days_with_data,
                "avg_daily_active_minutes": avg_daily_active,
            },
        )
        send_fcm_push(pet.owner, notif)
        return notif
