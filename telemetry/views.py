import logging
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiResponse
from .models import TelemetryReading
from .serializers import TelemetryIngestSerializer, TelemetryReadingSerializer
from devices.models import Device
from devices.authentication import DeviceAPIKeyAuthentication
from pets.models import Pet

logger = logging.getLogger(__name__)


class TelemetryIngestView(generics.CreateAPIView):
    """
    High-throughput ingestion endpoint for ESP32 collars or test simulators.
    Requires device authentication (X-Device-UID + X-Device-Key or DeviceKey header)
    OR user JWT authentication where the user owns the pet/device.
    """
    authentication_classes = [DeviceAPIKeyAuthentication, JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TelemetryIngestSerializer
    throttle_scope = "telemetry"

    @extend_schema(
        summary="Ingest sensor telemetry batch",
        description="Receives timestamped accelerometer and gyroscope readings from authenticated ESP32 or simulator.",
        responses={201: OpenApiResponse(description="Readings ingested successfully")},
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        readings_data = data["readings"]
        is_simulation = data.get("is_simulation", False)
        payload_device_uid = data.get("device_uid") or request.headers.get("X-Device-UID", "").strip()
        payload_pet_id = data.get("pet_id")

        device = None

        # Mode A: Authenticated via DeviceAPIKeyAuthentication (ESP32 hardware or standalone device client)
        if isinstance(request.auth, Device):
            device = request.auth
            logger.info("Telemetry ingestion authenticated via DeviceAPIKey for device_uid=%s", device.device_uid)

        # Mode B: Authenticated via JWT (mobile app user / simulation)
        elif request.user and request.user.is_authenticated:
            # Resolve target pet and device owned by request.user
            target_pet = None
            if payload_pet_id:
                try:
                    target_pet = Pet.objects.get(id=payload_pet_id, owner=request.user)
                except Pet.DoesNotExist:
                    logger.warning("Telemetry ingestion rejected: user %s does not own pet %s", request.user.id, payload_pet_id)
                    return Response(
                        {"detail": "You do not have permission for the specified pet."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

            if payload_device_uid:
                # Find device by UID
                dev_qs = Device.objects.filter(device_uid=payload_device_uid)
                if dev_qs.exists():
                    existing_device = dev_qs.first()
                    if existing_device.owner != request.user:
                        logger.warning(
                            "Telemetry ingestion rejected: user %s does not own device %s",
                            request.user.id,
                            payload_device_uid,
                        )
                        return Response(
                            {"detail": "You do not own the device referenced by the payload."},
                            status=status.HTTP_403_FORBIDDEN,
                        )
                    device = existing_device
                else:
                    # If this is simulated telemetry, auto-provision a virtual simulator device for the user
                    if is_simulation:
                        device = Device.objects.create(
                            owner=request.user,
                            pet=target_pet,
                            name=f"Simulator ({payload_device_uid})",
                            device_uid=payload_device_uid,
                            hardware_type=Device.HardwareType.SIMULATOR,
                            status=Device.Status.PAIRED if target_pet else Device.Status.REGISTERED,
                        )
                        logger.info("Auto-registered simulation device %s for user %s", payload_device_uid, request.user.id)
                    else:
                        logger.warning("Telemetry ingestion: unknown device_uid %s", payload_device_uid)
                        return Response(
                            {"detail": "Unknown device UID."},
                            status=status.HTTP_404_NOT_FOUND,
                        )

            # If no device_uid provided or device still not found, check target_pet's paired device
            if not device and target_pet and hasattr(target_pet, "device") and target_pet.device:
                device = target_pet.device

            # If still no device and this is a simulation for a pet, get or create virtual simulator device for the pet
            if not device and target_pet and is_simulation:
                sim_uid = f"SIM-{str(target_pet.id)[:8]}"
                device, created = Device.objects.get_or_create(
                    device_uid=sim_uid,
                    defaults={
                        "owner": request.user,
                        "pet": target_pet,
                        "name": f"Simulator ({target_pet.name})",
                        "hardware_type": Device.HardwareType.SIMULATOR,
                        "status": Device.Status.PAIRED,
                    },
                )
                if not device.pet:
                    device.pet = target_pet
                    device.save(update_fields=["pet"])

            if not device:
                logger.warning("Telemetry ingestion rejected: no valid device could be resolved for user %s", request.user.id)
                return Response(
                    {"detail": "A valid device or pet owned by your account must be provided."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Link pet if not linked
            if target_pet and not device.pet:
                device.pet = target_pet
                device.save(update_fields=["pet"])

            logger.info("Telemetry ingestion authenticated via JWT for user=%s, device_uid=%s", request.user.id, device.device_uid)
        else:
            return Response(
                {"detail": "A valid device credential or JWT authentication must be used for telemetry ingestion."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if device.status == Device.Status.REVOKED:
            return Response(
                {"detail": "Device credentials have been revoked."},
                status=status.HTTP_403_FORBIDDEN,
            )

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
                logger.warning("Automatic insight computation on ingestion failed: %s", e)

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
