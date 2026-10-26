import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class DeviceFCMToken(models.Model):
    """Stores FCM registration tokens associated with an authenticated owner's device."""

    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        WEB = "web", "Web"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fcm_device_tokens",
    )
    token = models.CharField(max_length=512, unique=True, db_index=True)
    platform = models.CharField(
        max_length=20,
        choices=Platform.choices,
        default=Platform.ANDROID,
    )
    device_name = models.CharField(max_length=150, blank=True, default="")
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"{self.user.username} - {self.platform} ({self.device_name or 'device'})"


class Notification(models.Model):
    """Stores in-app notification records and push delivery states."""

    class NotificationType(models.TextChoices):
        ACTIVITY_ANOMALY = "activity_anomaly", "Activity Anomaly"
        REST_CHANGE = "rest_change", "Rest Pattern Change"
        VITALS_ALERT = "vitals_alert", "Vitals Out of Range"
        INTAKE_ALERT = "intake_alert", "Intake Pattern Alert"
        VACCINE_REMINDER = "vaccine_reminder", "Vaccination / Deworming Due"
        BATTERY_LOW = "battery_low", "Collar Battery Low"
        SYSTEM = "system", "System Notice"

    class DeliveryStatus(models.TextChoices):
        QUEUED = "queued", "Queued"
        ACCEPTED = "accepted", "Accepted by FCM"
        FAILED = "failed", "FCM Delivery Failed"
        NO_DEVICE = "no_device", "No Active Device Tokens"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    pet = models.ForeignKey(
        "pets.Pet",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    notification_type = models.CharField(
        max_length=30,
        choices=NotificationType.choices,
        default=NotificationType.SYSTEM,
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    delivery_status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.QUEUED,
    )
    delivery_attempts = models.PositiveSmallIntegerField(default=0)
    delivery_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.notification_type}] {self.title} for {self.user.username}"
