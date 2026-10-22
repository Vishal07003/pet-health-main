from rest_framework import serializers
from .models import Device
from pets.models import Pet


class DeviceSerializer(serializers.ModelSerializer):
    pet_name = serializers.ReadOnlyField(source="pet.name")
    is_connected = serializers.ReadOnlyField()

    class Meta:
        model = Device
        fields = [
            "id",
            "name",
            "device_uid",
            "hardware_type",
            "firmware_version",
            "status",
            "pet",
            "pet_name",
            "is_connected",
            "last_seen_at",
            "battery_level",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "pet_name",
            "is_connected",
            "last_seen_at",
            "battery_level",
            "created_at",
            "updated_at",
        ]


class DeviceRegisterSerializer(serializers.ModelSerializer):
    """
    Used when registering a new physical device or simulator.
    Returns the one-time raw secret token for hardware provisioning.
    """
    token = serializers.CharField(read_only=True)

    class Meta:
        model = Device
        fields = [
            "id",
            "name",
            "device_uid",
            "hardware_type",
            "firmware_version",
            "token",
        ]
        read_only_fields = ["id", "token"]

    def validate_device_uid(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Device UID is required.")
        if Device.objects.filter(device_uid__iexact=cleaned).exists():
            raise serializers.ValidationError("A device with this UID is already registered.")
        return cleaned

    def create(self, validated_data):
        owner = self.context["request"].user
        raw_token = Device.generate_raw_token()
        device = Device(
            owner=owner,
            status=Device.Status.REGISTERED,
            **validated_data,
        )
        device.set_api_key(raw_token)
        device.save()
        device.token = raw_token  # Set ephemeral attribute for response
        return device


class PairDeviceSerializer(serializers.Serializer):
    pet_id = serializers.UUIDField(required=True)

    def validate_pet_id(self, value):
        user = self.context["request"].user
        try:
            pet = Pet.objects.get(id=value, owner=user)
        except Pet.DoesNotExist:
            raise serializers.ValidationError("Pet not found or does not belong to you.")
        return pet
