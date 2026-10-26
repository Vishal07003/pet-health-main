from abc import ABC, abstractmethod
from datetime import timedelta
import logging
from typing import Dict, Any, List, Optional
import numpy as np

from django.utils import timezone
from django.db.models import Sum, Avg, Count

from .models import ActivitySummary
from telemetry.models import TelemetryReading
from pets.models import Pet, FoodWaterLog

logger = logging.getLogger(__name__)


class BaseActivityClassifier(ABC):
    """
    Abstract Base Class for collar IMU motion classification.
    Provides a pluggable interface for future trained scikit-learn / ONNX / TFLite models
    while maintaining a transparent, verifiable statistical baseline.
    """

    @abstractmethod
    def extract_features(self, readings: List[Dict[str, Any]]) -> Dict[str, float]:
        """Extract multi-axis temporal and frequency features from IMU readings."""
        pass

    @abstractmethod
    def classify_window(self, features: Dict[str, float], window_minutes: int) -> Dict[str, Any]:
        """Classify readings into rest, walking, and running time distributions."""
        pass


class StatisticalBaselineClassifier(BaseActivityClassifier):
    """
    Transparent, empirical baseline classifier using 3-axis accelerometer and gyroscope statistics.
    Ground-truth physics baseline:
    - Earth gravity static resting baseline is ~1.0G with low variance.
    - Low acceleration & low variance (< 0.12) -> Resting / Sleeping.
    - Moderate cyclic acceleration (1.1G - 1.8G) & moderate variance -> Walking / Mild Movement.
    - Elevated acceleration (> 1.8G) & high jerk/variance -> Active / Running / Playing.
    """

    def extract_features(self, readings: List[Dict[str, Any]]) -> Dict[str, float]:
        if not readings:
            return {}

        magnitudes = np.array([r["accel_magnitude"] for r in readings], dtype=np.float64)
        ax = np.array([r.get("accel_x", 0.0) for r in readings], dtype=np.float64)
        ay = np.array([r.get("accel_y", 0.0) for r in readings], dtype=np.float64)
        az = np.array([r.get("accel_z", 0.0) for r in readings], dtype=np.float64)

        # Gyroscope magnitudes if available
        gx = np.array([r.get("gyro_x") or 0.0 for r in readings], dtype=np.float64)
        gy = np.array([r.get("gyro_y") or 0.0 for r in readings], dtype=np.float64)
        gz = np.array([r.get("gyro_z") or 0.0 for r in readings], dtype=np.float64)
        gyro_mag = np.sqrt(gx**2 + gy**2 + gz**2)

        # Signal Magnitude Area (SMA) normalized by window size
        sma = float(np.sum(np.abs(ax) + np.abs(ay) + np.abs(az)) / len(readings))

        # Approximate jerk (temporal difference of magnitude)
        if len(magnitudes) > 1:
            jerk = float(np.mean(np.abs(np.diff(magnitudes))))
        else:
            jerk = 0.0

        return {
            "total_samples": len(readings),
            "mean_mag": float(np.mean(magnitudes)),
            "std_mag": float(np.std(magnitudes)),
            "var_mag": float(np.var(magnitudes)),
            "min_mag": float(np.min(magnitudes)),
            "max_mag": float(np.max(magnitudes)),
            "sma": round(sma, 4),
            "mean_jerk": round(jerk, 4),
            "mean_gyro_mag": float(np.mean(gyro_mag)),
            "raw_magnitudes": magnitudes,
        }

    def classify_window(self, features: Dict[str, float], window_minutes: int) -> Dict[str, Any]:
        total_samples = int(features.get("total_samples", 0))
        if total_samples == 0:
            return {
                "rest_minutes": 0,
                "walk_minutes": 0,
                "run_minutes": 0,
                "dominant_state": ActivitySummary.DominantState.UNKNOWN,
                "confidence_score": 0.0,
            }

        magnitudes = features["raw_magnitudes"]
        var_mag = features.get("var_mag", 0.0)

        # Partition individual samples
        # Resting: static baseline around 1.0G (0.85 - 1.15G) with minimal movement variance
        is_resting = (magnitudes >= 0.85) & (magnitudes <= 1.15) & (var_mag < 0.15)
        rest_samples = int(np.sum(is_resting))

        # Running / High intensity: strong excursions > 1.8G
        is_running = magnitudes > 1.8
        run_samples = int(np.sum(is_running))

        # Walking / Mild movement: remaining samples
        walk_samples = max(0, total_samples - rest_samples - run_samples)

        # Calculate time distribution in minutes
        rest_mins = int((rest_samples / total_samples) * window_minutes)
        run_mins = int((run_samples / total_samples) * window_minutes)
        walk_mins = max(0, window_minutes - rest_mins - run_mins)

        # Determine dominant state
        if run_mins >= max(walk_mins, rest_mins):
            dominant_state = ActivitySummary.DominantState.RUNNING
        elif walk_mins >= max(run_mins, rest_mins):
            dominant_state = ActivitySummary.DominantState.WALKING
        else:
            dominant_state = ActivitySummary.DominantState.RESTING

        # Statistical confidence proportional to sample density (saturates at 60 samples/hr)
        confidence = min(0.95, round(0.50 + (total_samples / 60.0) * 0.45, 2))

        return {
            "rest_minutes": rest_mins,
            "walk_minutes": walk_mins,
            "run_minutes": run_mins,
            "dominant_state": dominant_state,
            "confidence_score": confidence,
        }


class ActivityInferenceEngine:
    """
    Probabilistic Activity & Anomaly Detection Pipeline.
    Treats predictions strictly as motion/activity observations.
    Does NOT produce veterinary diagnoses.
    """

    classifier: BaseActivityClassifier = StatisticalBaselineClassifier()

    @classmethod
    def compute_window_insights(
        cls,
        pet: Pet,
        window_minutes: int = 60,
        is_simulation: bool = False,
        target_time: Optional[timezone.datetime] = None,
    ) -> Optional[ActivitySummary]:
        """
        Computes an activity summary window for a pet.
        Strictly partitions simulated data based on is_simulation flag.
        """
        end_time = target_time or timezone.now()
        start_time = end_time - timedelta(minutes=window_minutes)

        readings_qs = TelemetryReading.objects.filter(
            pet=pet,
            timestamp__gte=start_time,
            timestamp__lte=end_time,
            is_simulation=is_simulation,
        ).values("accel_magnitude", "accel_x", "accel_y", "accel_z", "gyro_x", "gyro_y", "gyro_z", "timestamp")

        readings = list(readings_qs)
        if not readings:
            return None

        features = cls.classifier.extract_features(readings)
        classification = cls.classifier.classify_window(features, window_minutes)

        peak_accel = features["max_mag"]
        avg_accel = features["mean_mag"]
        rest_mins = classification["rest_minutes"]

        # Anomaly detection in window
        anomaly_detected = False
        anomaly_reason = ""

        # Check for physical spikes or prolonged sustained agitation
        if peak_accel > 3.8:
            anomaly_detected = True
            anomaly_reason = f"High acceleration spike of {peak_accel:.2f}G detected."
        elif avg_accel > 2.2 and rest_mins < 5:
            anomaly_detected = True
            anomaly_reason = "Unusually sustained high-energy agitation observed."

        summary = ActivitySummary.objects.create(
            pet=pet,
            window_start=start_time,
            window_end=end_time,
            total_samples=features["total_samples"],
            avg_acceleration=round(avg_accel, 3),
            peak_acceleration=round(peak_accel, 3),
            rest_minutes=rest_mins,
            active_minutes=classification["walk_minutes"],
            high_intensity_minutes=classification["run_minutes"],
            dominant_state=classification["dominant_state"],
            anomaly_detected=anomaly_detected,
            anomaly_reason=anomaly_reason,
            confidence_score=classification["confidence_score"],
            is_simulation=is_simulation,
        )

        # Trigger push notification on real anomalies only (never for simulations)
        if anomaly_detected and not is_simulation:
            try:
                from notifications.models import Notification
                from notifications.services import send_fcm_push
                notif = Notification.objects.create(
                    user=pet.owner,
                    pet=pet,
                    notification_type=Notification.NotificationType.ACTIVITY_ANOMALY,
                    title=f"Activity Alert: {pet.name}",
                    message=anomaly_reason,
                    metadata={"summary_id": str(summary.id), "pet_id": str(pet.id)},
                )
                send_fcm_push(pet.owner, notif)
            except Exception as e:
                logger.warning("Failed to dispatch anomaly notification: %s", e)

        return summary


class PetAnalyticsService:
    """
    Comprehensive Analytics Engine:
    - Calculates per-pet historical baselines from >= 3 days of real telemetry
    - Detects activity anomalies against personalized baseline (Z-Score)
    - Generates evidence-based daily & weekly summaries
    - Summarizes factual food/water intake observations without guesswork
    """

    MIN_BASELINE_DAYS = 3

    @classmethod
    def get_pet_baseline(cls, pet: Pet, days: int = 14) -> Dict[str, Any]:
        """
        Calculates personal baseline (mean and std of daily active minutes)
        using strictly real (non-simulated) telemetry from the past N days.
        """
        cutoff = timezone.now() - timedelta(days=days)

        # Aggregate daily non-simulated summaries
        daily_records = (
            ActivitySummary.objects.filter(
                pet=pet,
                is_simulation=False,
                window_start__gte=cutoff,
            )
            .values("window_start__date")
            .annotate(
                daily_active=Sum("active_minutes") + Sum("high_intensity_minutes"),
                daily_rest=Sum("rest_minutes"),
                daily_samples=Sum("total_samples"),
            )
            .filter(daily_samples__gte=20)  # Exclude days with near-zero data
        )

        day_count = len(daily_records)
        if day_count < cls.MIN_BASELINE_DAYS:
            return {
                "status": "insufficient_data",
                "days_available": day_count,
                "days_required": cls.MIN_BASELINE_DAYS,
                "message": (
                    f"Insufficient data: At least {cls.MIN_BASELINE_DAYS} days of collar activity are needed "
                    f"to establish a personalized baseline for {pet.name}. "
                    f"Currently {day_count} day(s) recorded."
                ),
            }

        active_vals = np.array([d["daily_active"] for d in daily_records], dtype=np.float64)
        rest_vals = np.array([d["daily_rest"] for d in daily_records], dtype=np.float64)

        mean_active = float(np.mean(active_vals))
        std_active = float(np.std(active_vals)) if len(active_vals) > 1 else 10.0
        # Prevent division by zero
        if std_active < 5.0:
            std_active = 5.0

        mean_rest = float(np.mean(rest_vals))

        return {
            "status": "established",
            "days_analyzed": day_count,
            "mean_daily_active_minutes": round(mean_active, 1),
            "std_daily_active_minutes": round(std_active, 1),
            "mean_daily_rest_minutes": round(mean_rest, 1),
        }

    @classmethod
    def get_daily_summary(cls, pet: Pet, target_date: Optional[timezone.datetime.date] = None, include_simulation: bool = False) -> Dict[str, Any]:
        """
        Returns structured daily activity totals for a pet on target_date.
        """
        date = target_date or timezone.now().date()
        qs = ActivitySummary.objects.filter(
            pet=pet,
            window_start__date=date,
        )
        if not include_simulation:
            qs = qs.filter(is_simulation=False)

        totals = qs.aggregate(
            total_active=Sum("active_minutes"),
            total_intense=Sum("high_intensity_minutes"),
            total_rest=Sum("rest_minutes"),
            total_samples=Sum("total_samples"),
            avg_accel=Avg("avg_acceleration"),
        )

        active = totals["total_active"] or 0
        intense = totals["total_intense"] or 0
        rest = totals["total_rest"] or 0
        samples = totals["total_samples"] or 0

        total_movement_minutes = active + intense

        return {
            "date": str(date),
            "total_samples": samples,
            "active_minutes": active,
            "high_intensity_minutes": intense,
            "total_moving_minutes": total_movement_minutes,
            "rest_minutes": rest,
            "avg_acceleration": round(totals["avg_accel"] or 1.0, 3),
            "is_sufficient": samples >= 30,
        }

    @classmethod
    def get_weekly_summary(cls, pet: Pet, include_simulation: bool = False) -> List[Dict[str, Any]]:
        """
        Returns rolling 7-day daily activity breakdown.
        """
        today = timezone.now().date()
        week_days = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            week_days.append(cls.get_daily_summary(pet, target_date=day, include_simulation=include_simulation))
        return week_days

    @classmethod
    def detect_anomalies(cls, pet: Pet, daily_summary: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates current day against personalized baseline.
        Identifies activity deviations (e.g., lethargy or sudden hyperactivity) without clinical diagnosis.
        """
        if baseline.get("status") != "established":
            return {
                "detected": False,
                "reason": "Insufficient historical data to establish personal activity baseline.",
                "z_score": 0.0,
                "confidence": "low",
            }

        if not daily_summary.get("is_sufficient"):
            return {
                "detected": False,
                "reason": "Current day does not yet have enough collar readings to detect deviations.",
                "z_score": 0.0,
                "confidence": "low",
            }

        mean_active = baseline["mean_daily_active_minutes"]
        std_active = baseline["std_daily_active_minutes"]
        today_active = daily_summary["total_moving_minutes"]

        z_score = (today_active - mean_active) / std_active

        # Deviation threshold: |z| >= 2.0 (approximately 95% threshold)
        if z_score <= -2.0:
            pct_drop = round(((mean_active - today_active) / max(mean_active, 1.0)) * 100)
            return {
                "detected": True,
                "anomaly_type": "reduced_activity",
                "z_score": round(float(z_score), 2),
                "reason": (
                    f"Noticeably lower movement today: {today_active} mins vs "
                    f"{pet.name}'s normal {mean_active:.0f} mins (-{pct_drop}%). "
                    "Observe for signs of fatigue or stiffness."
                ),
                "confidence": "high" if abs(z_score) >= 2.5 else "moderate",
            }
        elif z_score >= 2.5:
            pct_rise = round(((today_active - mean_active) / max(mean_active, 1.0)) * 100)
            return {
                "detected": True,
                "anomaly_type": "elevated_activity",
                "z_score": round(float(z_score), 2),
                "reason": (
                    f"Elevated activity today: {today_active} mins vs "
                    f"{pet.name}'s normal {mean_active:.0f} mins (+{pct_rise}%). "
                    "Ensure adequate hydration and post-exercise rest."
                ),
                "confidence": "high",
            }

        return {
            "detected": False,
            "reason": f"Activity is within expected normal baseline for {pet.name}.",
            "z_score": round(float(z_score), 2),
            "confidence": "high",
        }

    @classmethod
    def get_food_water_summary(cls, pet: Pet, target_date: Optional[timezone.datetime.date] = None) -> Dict[str, Any]:
        """
        Factual food and water intake summary based solely on recorded observations.
        Does NOT estimate or fabricate amounts when sensors or logs are missing.
        """
        date = target_date or timezone.now().date()
        logs = FoodWaterLog.objects.filter(pet=pet, logged_at__date=date)

        food_logs = [log for log in logs if log.intake_type == FoodWaterLog.IntakeType.FOOD]
        water_logs = [log for log in logs if log.intake_type == FoodWaterLog.IntakeType.WATER]

        food_count = len(food_logs)
        water_count = len(water_logs)

        # Group by unit for factual reporting
        food_by_unit = {}
        for fl in food_logs:
            food_by_unit[fl.unit] = round(food_by_unit.get(fl.unit, 0.0) + float(fl.amount), 2)

        water_by_unit = {}
        for wl in water_logs:
            water_by_unit[wl.unit] = round(water_by_unit.get(wl.unit, 0.0) + float(wl.amount), 2)

        has_data = (food_count + water_count) > 0

        return {
            "date": str(date),
            "recorded_entries_count": food_count + water_count,
            "food_entries_count": food_count,
            "water_entries_count": water_count,
            "food_totals": food_by_unit,
            "water_totals": water_by_unit,
            "has_data": has_data,
            "observation_note": (
                f"{food_count} meal entry(ies) and {water_count} water entry(ies) recorded."
                if has_data
                else f"No food or water logs recorded for {pet.name} on this date. Record meals to track nutrition patterns."
            ),
        }

    @classmethod
    def generate_pet_analytics(cls, pet: Pet, include_simulation: bool = False) -> Dict[str, Any]:
        """
        Main entry point: Generates comprehensive, fact-grounded analytics package for a pet.
        """
        baseline = cls.get_pet_baseline(pet)
        daily = cls.get_daily_summary(pet, include_simulation=include_simulation)
        weekly = cls.get_weekly_summary(pet, include_simulation=include_simulation)
        anomaly = cls.detect_anomalies(pet, daily, baseline)
        food_water = cls.get_food_water_summary(pet)

        # Personalized actionable insights
        insights_list: List[str] = []
        if anomaly.get("detected"):
            insights_list.append(anomaly["reason"])
        elif baseline.get("status") == "established":
            insights_list.append(
                f"{pet.name} is tracking within their typical daily activity range "
                f"({baseline['mean_daily_active_minutes']:.0f} mins/day average)."
            )
        else:
            insights_list.append(baseline["message"])

        if food_water["has_data"]:
            if anomaly.get("detected") and anomaly.get("anomaly_type") == "elevated_activity" and food_water["water_entries_count"] == 0:
                insights_list.append("High activity logged today with no water entries recorded. Please verify water bowl availability.")
        else:
            insights_list.append("Tip: Log meals and hydration to see activity vs nutrition correlation.")

        return {
            "pet_id": str(pet.id),
            "pet_name": pet.name,
            "species": pet.species,
            "include_simulation": include_simulation,
            "baseline": baseline,
            "today_summary": daily,
            "weekly_summary": weekly,
            "anomaly": anomaly,
            "food_water_summary": food_water,
            "personalized_insights": insights_list,
            "disclaimer": (
                "Activity and motion patterns are probabilistic observational metrics "
                "intended for wellness tracking. They do not constitute a veterinary diagnosis."
            ),
        }
