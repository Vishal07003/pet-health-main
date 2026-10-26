from rest_framework import serializers
from .models import DeviceFCMToken, Notification


class DeviceFCMTokenSerializer(serializers.ModelSerializer):
    token = serializers.CharField(max_length=512)

    class Meta:
        model = DeviceFCMToken
        fields = [
            "id",
            "token",
            "platform",
            "device_name",
            "is_active",
            "last_seen_at",
            "created_at",
        ]
        read_only_fields = ["id", "is_active", "last_seen_at", "created_at"]

    def validate_token(self, value):
        val = value.strip()
        if not val or len(val) < 10:
            raise serializers.ValidationError("Invalid FCM registration token.")
        return val



class NotificationSerializer(serializers.ModelSerializer):
    pet_name = serializers.CharField(source="pet.name", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "user",
            "pet",
            "pet_name",
            "notification_type",
            "title",
            "message",
            "is_read",
            "read_at",
            "metadata",
            "delivery_status",
            "delivery_attempts",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "delivery_status",
            "delivery_attempts",
            "created_at",
        ]
