import uuid
from django.db import models


class ActivitySummary(models.Model):
    """
    Summarized activity windows (hourly / daily) computed from raw sensor telemetry.
    Treats predictions strictly as probabilistic movement observations, not veterinary diagnoses.
    """
    class DominantState(models.TextChoices):
        RESTING = "resting", "Resting / Sleeping"
        WALKING = "walking", "Walking / Mild Movement"
        RUNNING = "running", "Active / Running / Playing"
        UNKNOWN = "unknown", "Insufficient Data"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pet = models.ForeignKey(
        "pets.Pet",
        on_delete=models.CASCADE,
        related_name="activity_summaries",
    )
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    
    # Statistical aggregates
    total_samples = models.PositiveIntegerField(default=0)
    avg_acceleration = models.FloatField(default=1.0)
    peak_acceleration = models.FloatField(default=1.0)
    
    # Estimated time breakdown in minutes
    rest_minutes = models.PositiveIntegerField(default=0)
    active_minutes = models.PositiveIntegerField(default=0)
    high_intensity_minutes = models.PositiveIntegerField(default=0)
    
    dominant_state = models.CharField(
        max_length=20,
        choices=DominantState.choices,
        default=DominantState.UNKNOWN,
    )
    
    # Probabilistic observation metrics
    anomaly_detected = models.BooleanField(
        default=False,
        help_text="Flagged when movement pattern departs significantly from baseline",
    )
    anomaly_reason = models.CharField(max_length=255, blank=True, default="")
    confidence_score = models.FloatField(
        default=0.85,
        help_text="Statistical confidence of classification (0.0 to 1.0)",
    )
    
    is_simulation = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-window_start"]
        indexes = [
            models.Index(fields=["pet", "-window_start"]),
            models.Index(fields=["anomaly_detected"]),
        ]

    def __str__(self):
        return f"{self.pet.name} Summary [{self.window_start} - {self.window_end}]: {self.dominant_state}"
