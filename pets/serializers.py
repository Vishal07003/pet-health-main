from django.utils import timezone
from rest_framework import serializers
from .models import Pet, WeightRecord, MedicalRecord, VetAppointment


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


class WeightRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeightRecord
        fields = ["id", "pet", "weight_kg", "recorded_at", "notes", "created_at"]
        read_only_fields = ["id", "created_at"]


class MedicalRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalRecord
        fields = [
            "id",
            "pet",
            "record_type",
            "title",
            "administered_at",
            "next_due_date",
            "batch_number",
            "veterinarian",
            "clinic_name",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class VetAppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = VetAppointment
        fields = [
            "id",
            "pet",
            "title",
            "appointment_date",
            "veterinarian",
            "clinic_name",
            "reason",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
