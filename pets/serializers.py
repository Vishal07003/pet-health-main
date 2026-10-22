from django.utils import timezone
from rest_framework import serializers
from .models import Pet


class PetSerializer(serializers.ModelSerializer):
    owner = serializers.ReadOnlyField(source="owner.username")
    owner_id = serializers.ReadOnlyField(source="owner.id")

    class Meta:
        model = Pet
        fields = [
            "id",
            "name",
            "species",
            "breed",
            "sex",
            "date_of_birth",
            "weight_kg",
            "is_neutered",
            "microchip_number",
            "notes",
            "owner",
            "owner_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "owner", "owner_id", "created_at", "updated_at"]

    def validate_name(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Pet name cannot be blank.")
        return cleaned

    def validate_date_of_birth(self, value):
        if value is not None and value > timezone.now().date():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        return value

    def validate_weight_kg(self, value):
        if value is not None:
            if value <= 0:
                raise serializers.ValidationError("Weight must be greater than 0 kg.")
            if value > 200:
                raise serializers.ValidationError("Weight cannot exceed 200 kg.")
        return value
