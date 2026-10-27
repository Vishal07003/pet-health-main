from rest_framework import generics, permissions, status
from rest_framework.response import Response
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiResponse
from .models import TelemetryReading
from .serializers import TelemetryIngestSerializer, TelemetryReadingSerializer
from devices.models import Device
from devices.authentication import DeviceAPIKeyAuthentication


class TelemetryIngestView(generics.CreateAPIView):
    """
    High-throughput ingestion endpoint for ESP32 collars or test simulators.
    Requires device authentication (X-Device-UID + X-Device-Key or DeviceKey header).
    """
    authentication_classes = [DeviceAPIKeyAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TelemetryIngestSerializer
    throttle_scope = "telemetry"

    @extend_schema(
        summary="Ingest sensor telemetry batch",
        description="Receives timestamped accelerometer and gyroscope readings from authenticated ESP32 or simulator.",
        responses={201: OpenApiResponse(description="Readings ingested successfully")},
    )
    def post(self, request, *args, **kwargs):
        device = request.auth  # Populated by DeviceAPIKeyAuthentication
        if not isinstance(device, Device):
            return Response(
                {"detail": "A valid device credential must be used for telemetry ingestion."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        readings_data = data["readings"]
        is_simulation = data.get("is_simulation", False)

        created_records = []
        latest_battery = None
        now = timezone.now()

        for item in readings_data:
            ts = item.get("timestamp", now)
            # Duplicate prevention check (ignore duplicate timestamps for the same device)
            if TelemetryReading.objects.filter(device=device, timestamp=ts).exists():
                continue

            accel_x = item["accel_x"]
            accel_y = item["accel_y"]
            accel_z = item["accel_z"]
            magnitude = round((accel_x**2 + accel_y**2 + accel_z**2) ** 0.5, 4)

            reading = TelemetryReading(
                device=device,
                pet=device.pet,
                timestamp=ts,
                accel_x=accel_x,
                accel_y=accel_y,
                accel_z=accel_z,
                gyro_x=item.get("gyro_x"),
                gyro_y=item.get("gyro_y"),
                gyro_z=item.get("gyro_z"),
                accel_magnitude=magnitude,
                battery_level=item.get("battery_level"),
                rssi=item.get("rssi"),
                is_simulation=is_simulation,
            )
            created_records.append(reading)
            if item.get("battery_level") is not None:
                latest_battery = item["battery_level"]

        if created_records:
            TelemetryReading.objects.bulk_create(created_records)

        # Update device last_seen and battery state
        device.last_seen_at = now
        if latest_battery is not None:
            device.battery_level = latest_battery
        device.save(update_fields=["last_seen_at", "battery_level", "updated_at"])

        # When real or simulated readings are ingested for an assigned pet, compute window insights
        if created_records and device.pet:
            try:
                from insights.services import ActivityInferenceEngine
                ActivityInferenceEngine.compute_window_insights(
                    pet=device.pet,
                    is_simulation=is_simulation,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Automatic insight computation on ingestion failed: %s", e)

        return Response(
            {
                "status": "success",
                "ingested_count": len(created_records),
                "device_uid": device.device_uid,
                "pet_id": str(device.pet.id) if device.pet else None,
                "is_simulation": is_simulation,
            },
            status=status.HTTP_201_CREATED,
        )


class TelemetryListView(generics.ListAPIView):
    """
    Protected endpoint for mobile app to view recent sensor readings for a pet.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TelemetryReadingSerializer

    def get_queryset(self):
        pet_id = self.request.query_params.get("pet_id")
        qs = TelemetryReading.objects.filter(device__owner=self.request.user)
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs[:100]  # Most recent 100 entries
