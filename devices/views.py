from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse
from .models import Device
from .serializers import DeviceSerializer, DeviceRegisterSerializer, PairDeviceSerializer
from pets.permissions import IsOwner


@extend_schema_view(
    list=extend_schema(summary="List all devices owned by the authenticated user"),
    create=extend_schema(
        summary="Register a new device",
        description="Registers an ESP32 collar or simulator and returns the one-time secret API token.",
    ),
    retrieve=extend_schema(summary="Retrieve device details"),
)
class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return Device.objects.none()
        return Device.objects.filter(owner=self.request.user).select_related("pet")

    def get_serializer_class(self):
        if self.action == "create":
            return DeviceRegisterSerializer
        return DeviceSerializer

    @extend_schema(
        summary="Pair device with a pet",
        request=PairDeviceSerializer,
        responses={200: DeviceSerializer},
    )
    @action(detail=True, methods=["post"], url_path="pair")
    def pair(self, request, pk=None):
        device = self.get_object()

        if device.status == Device.Status.REVOKED:
            return Response(
                {"detail": "Cannot pair a revoked device."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PairDeviceSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        pet = serializer.validated_data["pet_id"]

        # If pet is already paired to another device, unpair old device first
        if hasattr(pet, "device") and pet.device and pet.device != device:
            old_device = pet.device
            old_device.pet = None
            old_device.status = Device.Status.UNPAIRED
            old_device.save()

        device.pet = pet
        device.status = Device.Status.PAIRED
        device.save()

        return Response(DeviceSerializer(device).data)

    @extend_schema(
        summary="Unpair device from pet",
        responses={200: DeviceSerializer},
    )
    @action(detail=True, methods=["post"], url_path="unpair")
    def unpair(self, request, pk=None):
        device = self.get_object()
        device.pet = None
        device.status = Device.Status.UNPAIRED
        device.save()
        return Response(DeviceSerializer(device).data)

    @extend_schema(
        summary="Revoke device credentials",
        responses={200: DeviceSerializer},
    )
    @action(detail=True, methods=["post"], url_path="revoke")
    def revoke(self, request, pk=None):
        device = self.get_object()
        device.status = Device.Status.REVOKED
        device.pet = None
        device.api_key_hash = ""  # Erase hashed token to block all subsequent telemetry
        device.save()
        return Response(
            {"detail": "Device credentials revoked.", "device": DeviceSerializer(device).data}
        )
