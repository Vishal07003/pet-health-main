import uuid
from django.db import models


class TelemetryReading(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(
        "devices.Device",
        on_delete=models.CASCADE,
        related_name="telemetry_readings",
    )
    pet = models.ForeignKey(
        "pets.Pet",
        on_delete=models.CASCADE,
        related_name="telemetry_readings",
        null=True,
        blank=True,
    )
    timestamp = models.DateTimeField(
        help_text="Sensor recording timestamp reported by device or ingestion time",
    )

    # 3-Axis Accelerometer in G (gravity units or m/s^2)
    accel_x = models.FloatField()
    accel_y = models.FloatField()
    accel_z = models.FloatField()

    # 3-Axis Gyroscope in degrees/sec or rad/sec (null if 3-DOF sensor)
    gyro_x = models.FloatField(null=True, blank=True)
    gyro_y = models.FloatField(null=True, blank=True)
    gyro_z = models.FloatField(null=True, blank=True)

    # Derived magnitude for vector analysis: sqrt(ax^2 + ay^2 + az^2)
    accel_magnitude = models.FloatField(
        help_text="Calculated Euclidean magnitude of acceleration",
    )

    battery_level = models.IntegerField(null=True, blank=True)
    rssi = models.IntegerField(null=True, blank=True, help_text="BLE / Wi-Fi Signal Strength in dBm")
    
    is_simulation = models.BooleanField(
        default=False,
        help_text="Flag explicitly separating simulated/synthetic data from physical ESP32 hardware",
    )
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["pet", "-timestamp"]),
            models.Index(fields=["device", "-timestamp"]),
            models.Index(fields=["is_simulation"]),
        ]
        # Prevent exact duplicate telemetry submissions
        constraints = [
            models.UniqueConstraint(
                fields=["device", "timestamp"],
                name="unique_device_timestamp_telemetry",
            )
        ]

    def save(self, *args, **kwargs):
        if self.accel_magnitude is None:
            self.accel_magnitude = round(
                (self.accel_x**2 + self.accel_y**2 + self.accel_z**2) ** 0.5,
                4,
            )
        super().save(*args, **kwargs)

    def __str__(self):
        source = "Sim" if self.is_simulation else "Hardware"
        return f"{self.device.device_uid} @ {self.timestamp} ({source}, mag: {self.accel_magnitude}G)"
