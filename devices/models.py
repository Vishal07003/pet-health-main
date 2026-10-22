import uuid
import secrets
import hashlib
from django.db import models
from django.conf import settings
from django.utils import timezone


class Device(models.Model):
    class Status(models.TextChoices):
        REGISTERED = "registered", "Registered"
        PAIRED = "paired", "Paired"
        UNPAIRED = "unpaired", "Unpaired"
        REVOKED = "revoked", "Revoked"

    class HardwareType(models.TextChoices):
        ESP32_IMU_COLLAR = "esp32_imu_collar", "ESP32 IMU Collar"
        SIMULATOR = "simulator", "Virtual Simulator"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="devices",
    )
    pet = models.OneToOneField(
        "pets.Pet",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device",
        help_text="The pet this wearable device is currently assigned/paired to.",
    )
    name = models.CharField(max_length=100, default="Smart Collar")
    device_uid = models.CharField(
        max_length=64,
        unique=True,
        help_text="Hardware MAC / Unique Hardware identifier (e.g., 24:6F:28:XX:XX:XX)",
    )
    hardware_type = models.CharField(
        max_length=32,
        choices=HardwareType.choices,
        default=HardwareType.ESP32_IMU_COLLAR,
    )
    firmware_version = models.CharField(max_length=32, default="1.0.0")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REGISTERED,
    )
    
    # Secure device-specific API authentication token (hashed in database)
    api_key_hash = models.CharField(
        max_length=128,
        blank=True,
        help_text="SHA-256 hash of device secret token for authenticating ingestion calls",
    )

    last_seen_at = models.DateTimeField(null=True, blank=True)
    battery_level = models.IntegerField(null=True, blank=True, help_text="Battery percent (0-100)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["device_uid"]),
        ]

    def __str__(self):
        paired_str = f"paired with {self.pet.name}" if self.pet else "unpaired"
        return f"{self.name} ({self.device_uid}) - {paired_str}"

    @staticmethod
    def generate_raw_token():
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def set_api_key(self, raw_token: str):
        self.api_key_hash = self.hash_token(raw_token)

    def check_api_key(self, raw_token: str) -> bool:
        if not self.api_key_hash or not raw_token:
            return False
        return secrets.compare_digest(self.api_key_hash, self.hash_token(raw_token))

    @property
    def is_connected(self) -> bool:
        """
        Device is only considered actively connected if it transmitted data within 2 minutes.
        Does not falsely report connected when idle or absent.
        """
        if not self.last_seen_at:
            return False
        return (timezone.now() - self.last_seen_at).total_seconds() < 120
