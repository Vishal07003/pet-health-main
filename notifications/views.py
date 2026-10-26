from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import DeviceFCMToken, Notification
from .serializers import DeviceFCMTokenSerializer, NotificationSerializer


class DeviceFCMTokenViewSet(viewsets.GenericViewSet):
    """Endpoints for registering, refreshing, and unregistering owner device FCM tokens."""
    serializer_class = DeviceFCMTokenSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return DeviceFCMToken.objects.none()
        return DeviceFCMToken.objects.filter(user=self.request.user)

    @action(detail=False, methods=["post"], url_path="register")
    def register_token(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_str = serializer.validated_data["token"].strip()
        platform = serializer.validated_data.get("platform", DeviceFCMToken.Platform.ANDROID)
        device_name = serializer.validated_data.get("device_name", "").strip()

        # Update or create: re-assign token to current user if device was handed over/re-logged
        device_token, created = DeviceFCMToken.objects.update_or_create(
            token=token_str,
            defaults={
                "user": request.user,
                "platform": platform,
                "device_name": device_name,
                "is_active": True,
                "last_seen_at": timezone.now(),
            },
        )
        return Response(
            {
                "status": "registered",
                "id": str(device_token.id),
                "platform": device_token.platform,
                "created": created,
            },
            status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["post"], url_path="unregister")
    def unregister_token(self, request):
        token_str = request.data.get("token", "").strip()
        if not token_str:
            return Response({"error": "Token is required to unregister."}, status=status.HTTP_400_BAD_REQUEST)

        # Deactivate token for this user
        updated = DeviceFCMToken.objects.filter(user=request.user, token=token_str).update(is_active=False)
        return Response({"status": "unregistered", "updated": updated > 0})


class NotificationViewSet(viewsets.ModelViewSet):
    """Endpoints for listing, retrieving, and updating read status of user notifications."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return Notification.objects.none()
        qs = Notification.objects.filter(user=self.request.user)
        pet_id = self.request.query_params.get("pet") or self.request.query_params.get("pet_id")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        is_read = self.request.query_params.get("is_read")
        if is_read is not None:
            qs = qs.filter(is_read=is_read.lower() in ["true", "1"])
        return qs

    def perform_create(self, serializer):
        # Auto-assign authenticated owner and trigger push dispatch
        pet = serializer.validated_data.get("pet")
        if pet and pet.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this pet.")
        notif = serializer.save(user=self.request.user)
        from .services import send_fcm_push
        send_fcm_push(self.request.user, notif)

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        notif = self.get_object()
        notif.is_read = True
        notif.read_at = timezone.now()
        notif.save(update_fields=["is_read", "read_at"])
        return Response(self.get_serializer(notif).data)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        qs = self.get_queryset().filter(is_read=False)
        count = qs.update(is_read=True, read_at=timezone.now())
        return Response({"status": "ok", "marked_read_count": count})
