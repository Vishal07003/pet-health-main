import numpy as np
from datetime import timedelta
from django.utils import timezone
from .models import ActivitySummary
from telemetry.models import TelemetryReading
from pets.models import Pet


class ActivityInferenceEngine:
    """
    Probabilistic Activity & Anomaly Detection Pipeline.
    Treats predictions strictly as motion/activity observations.
    Does NOT produce veterinary diagnoses (e.g. disease, hunger, thirst).
    """

    @classmethod
    def compute_window_insights(cls, pet: Pet, window_minutes: int = 60, is_simulation: bool = False):
        end_time = timezone.now()
        start_time = end_time - timedelta(minutes=window_minutes)

        readings = list(
            TelemetryReading.objects.filter(
                pet=pet,
                timestamp__gte=start_time,
                timestamp__lte=end_time,
            ).values("accel_magnitude", "timestamp")
        )

        if not readings:
            return None

        magnitudes = np.array([r["accel_magnitude"] for r in readings], dtype=np.float64)
        total_samples = len(magnitudes)
        avg_accel = float(np.mean(magnitudes))
        peak_accel = float(np.max(magnitudes))
        variance = float(np.var(magnitudes))

        # Movement classification heuristics (derived from typical collar IMU motion)
        # Resting: ~1.0G (earth gravity static baseline, low variance < 0.05)
        # Walking: 1.1G - 1.8G (moderate variance)
        # Running / Intense: > 1.8G (high variance)
        rest_samples = int(np.sum((magnitudes >= 0.85) & (magnitudes <= 1.15) & (variance < 0.15)))
        run_samples = int(np.sum(magnitudes > 1.8))
        walk_samples = max(0, total_samples - rest_samples - run_samples)

        rest_mins = int((rest_samples / total_samples) * window_minutes)
        run_mins = int((run_samples / total_samples) * window_minutes)
        walk_mins = max(0, window_minutes - rest_mins - run_mins)

        # Dominant state
        if run_mins >= max(walk_mins, rest_mins):
            dominant_state = ActivitySummary.DominantState.RUNNING
        elif walk_mins >= max(run_mins, rest_mins):
            dominant_state = ActivitySummary.DominantState.WALKING
        else:
            dominant_state = ActivitySummary.DominantState.RESTING

        # Statistical anomaly detection (e.g. abrupt spike > 3.5G or prolonged agitation)
        anomaly_detected = False
        anomaly_reason = ""
        if peak_accel > 3.8:
            anomaly_detected = True
            anomaly_reason = f"High acceleration spike of {peak_accel:.2f}G detected."
        elif avg_accel > 2.2 and rest_mins < 5:
            anomaly_detected = True
            anomaly_reason = "Unusually sustained high-energy agitation observed."

        # Confidence metric scales with sample volume (min 30 samples for full confidence)
        confidence = min(0.95, round(0.50 + (total_samples / 60.0) * 0.45, 2))

        summary = ActivitySummary.objects.create(
            pet=pet,
            window_start=start_time,
            window_end=end_time,
            total_samples=total_samples,
            avg_acceleration=round(avg_accel, 3),
            peak_acceleration=round(peak_accel, 3),
            rest_minutes=rest_mins,
            active_minutes=walk_mins,
            high_intensity_minutes=run_mins,
            dominant_state=dominant_state,
            anomaly_detected=anomaly_detected,
            anomaly_reason=anomaly_reason,
            confidence_score=confidence,
            is_simulation=is_simulation,
        )
        return summary
