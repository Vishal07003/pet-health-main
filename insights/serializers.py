from rest_framework import serializers
from .models import ActivitySummary


class ActivitySummarySerializer(serializers.ModelSerializer):
    pet_name = serializers.ReadOnlyField(source="pet.name")

    class Meta:
        model = ActivitySummary
        fields = [
            "id",
            "pet",
            "pet_name",
            "window_start",
            "window_end",
            "total_samples",
            "avg_acceleration",
            "peak_acceleration",
            "rest_minutes",
            "active_minutes",
            "high_intensity_minutes",
            "dominant_state",
            "anomaly_detected",
            "anomaly_reason",
            "confidence_score",
            "is_simulation",
            "created_at",
        ]
        read_only_fields = fields
