from rest_framework import serializers
from django.utils import timezone
from .models import TelemetryReading
from devices.models import Device


class TelemetryItemSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField(required=False, default=timezone.now)
    accel_x = serializers.FloatField(required=True)
    accel_y = serializers.FloatField(required=True)
    accel_z = serializers.FloatField(required=True)
    gyro_x = serializers.FloatField(required=False, allow_null=True, default=None)
    gyro_y = serializers.FloatField(required=False, allow_null=True, default=None)
    gyro_z = serializers.FloatField(required=False, allow_null=True, default=None)
    battery_level = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=100, default=None
    )
    rssi = serializers.IntegerField(required=False, allow_null=True, default=None)


class TelemetryIngestSerializer(serializers.Serializer):
    """
    Accepts single or batched sensor readings from an ESP32 or simulator.
    """
    readings = TelemetryItemSerializer(many=True, required=True)
    is_simulation = serializers.BooleanField(required=False, default=False)
    device_uid = serializers.CharField(required=False, allow_blank=True, default="")
    pet_id = serializers.UUIDField(required=False, allow_null=True, default=None)


class TelemetryReadingSerializer(serializers.ModelSerializer):
    device_uid = serializers.ReadOnlyField(source="device.device_uid")
    pet_name = serializers.ReadOnlyField(source="pet.name")

    class Meta:
        model = TelemetryReading
        fields = [
            "id",
            "device",
            "device_uid",
            "pet",
            "pet_name",
            "timestamp",
            "accel_x",
            "accel_y",
            "accel_z",
            "gyro_x",
            "gyro_y",
            "gyro_z",
            "accel_magnitude",
            "battery_level",
            "rssi",
            "is_simulation",
            "received_at",
        ]
        read_only_fields = fields
