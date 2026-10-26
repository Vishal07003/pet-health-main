from datetime import timedelta
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from devices.models import Device
from pets.models import Pet, FoodWaterLog
from telemetry.models import TelemetryReading
from .models import ActivitySummary
from .services import ActivityInferenceEngine, PetAnalyticsService

User = get_user_model()


class InsightsAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="insights_user",
            email="iu@example.com",
            password="Password123!",
        )
        self.other_user = User.objects.create_user(
            username="other_insights_user",
            email="other_iu@example.com",
            password="Password123!",
        )
        self.pet = Pet.objects.create(
            owner=self.user,
            name="Daisy",
            species="dog",
        )
        self.other_pet = Pet.objects.create(
            owner=self.other_user,
            name="Max",
            species="dog",
        )
        self.device = Device.objects.create(
            owner=self.user,
            pet=self.pet,
            name="Daisy Collar",
            device_uid="ESP32_DAISY_01",
            status=Device.Status.PAIRED,
        )

    def test_generate_insights_from_readings(self):
        self.client.force_authenticate(user=self.user)
        now = timezone.now()
        for i in range(10):
            TelemetryReading.objects.create(
                device=self.device,
                pet=self.pet,
                accel_x=0.1,
                accel_y=1.4,
                accel_z=0.2,
                accel_magnitude=1.4177,
                timestamp=now - timedelta(minutes=i * 2),
                is_simulation=True,
            )

        gen_url = reverse("insights-generate", kwargs={"pet_id": self.pet.id})
        res = self.client.post(gen_url + "?is_simulation=true")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(str(res.data["pet"]), str(self.pet.id))
        self.assertIn("dominant_state", res.data)
        self.assertIn("confidence_score", res.data)
        self.assertIn("anomaly_detected", res.data)
        self.assertTrue(ActivitySummary.objects.filter(pet=self.pet).exists())

    def test_simulation_data_strict_partitioning(self):
        """Ensure real analytics ignore simulated telemetry by default."""
        self.client.force_authenticate(user=self.user)
        now = timezone.now()
        # Create only simulated telemetry
        for i in range(15):
            TelemetryReading.objects.create(
                device=self.device,
                pet=self.pet,
                accel_x=0.0,
                accel_y=1.0,
                accel_z=0.0,
                accel_magnitude=1.0,
                timestamp=now - timedelta(minutes=i * 2),
                is_simulation=True,
            )

        # Attempting to generate insights without is_simulation flag should find no real readings
        gen_url = reverse("insights-generate", kwargs={"pet_id": self.pet.id})
        res = self.client.post(gen_url)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pet_analytics_insufficient_baseline(self):
        """Ensure clear insufficient-data status when fewer than 3 days of real data exist."""
        self.client.force_authenticate(user=self.user)
        analytics_url = reverse("pet-analytics", kwargs={"pet_id": self.pet.id})
        res = self.client.get(analytics_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["baseline"]["status"], "insufficient_data")
        self.assertEqual(res.data["baseline"]["days_required"], 3)
        self.assertIn("insufficient", res.data["personalized_insights"][0].lower())

    def test_pet_analytics_established_baseline_and_anomaly_detection(self):
        """Create 4 days of history to establish baseline, then verify z-score anomaly detection."""
        self.client.force_authenticate(user=self.user)
        now = timezone.now()

        # Seed 4 past days of typical daily activity (around 60 mins active per day)
        for d in range(1, 5):
            day_time = now - timedelta(days=d)
            ActivitySummary.objects.create(
                pet=self.pet,
                window_start=day_time,
                window_end=day_time + timedelta(hours=1),
                total_samples=50,
                avg_acceleration=1.2,
                peak_acceleration=2.0,
                rest_minutes=40,
                active_minutes=15,
                high_intensity_minutes=5,
                dominant_state=ActivitySummary.DominantState.WALKING,
                is_simulation=False,
            )

        # Today's activity has severe reduction (0 active minutes)
        ActivitySummary.objects.create(
            pet=self.pet,
            window_start=now - timedelta(hours=1),
            window_end=now,
            total_samples=50,
            avg_acceleration=1.0,
            peak_acceleration=1.05,
            rest_minutes=60,
            active_minutes=0,
            high_intensity_minutes=0,
            dominant_state=ActivitySummary.DominantState.RESTING,
            is_simulation=False,
        )

        analytics_url = reverse("pet-analytics", kwargs={"pet_id": self.pet.id})
        res = self.client.get(analytics_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["baseline"]["status"], "established")
        self.assertTrue(res.data["baseline"]["mean_daily_active_minutes"] > 0)
        self.assertTrue(res.data["anomaly"]["detected"])
        self.assertEqual(res.data["anomaly"]["anomaly_type"], "reduced_activity")

    def test_food_water_summary_no_fabrication(self):
        """Verify food/water summary returns factual counts and empty states without estimating quantities."""
        self.client.force_authenticate(user=self.user)
        # Empty state
        fw_empty = PetAnalyticsService.get_food_water_summary(self.pet)
        self.assertFalse(fw_empty["has_data"])
        self.assertEqual(fw_empty["recorded_entries_count"], 0)

        # Add single meal entry
        FoodWaterLog.objects.create(
            pet=self.pet,
            intake_type=FoodWaterLog.IntakeType.FOOD,
            amount=150.0,
            unit=FoodWaterLog.Unit.GRAMS,
        )

        fw_with_data = PetAnalyticsService.get_food_water_summary(self.pet)
        self.assertTrue(fw_with_data["has_data"])
        self.assertEqual(fw_with_data["food_entries_count"], 1)
        self.assertEqual(fw_with_data["food_totals"]["g"], 150.0)

    def test_permission_denied_for_other_user_pet(self):
        """Ensure other users cannot access another owner's pet analytics."""
        self.client.force_authenticate(user=self.user)
        analytics_url = reverse("pet-analytics", kwargs={"pet_id": self.other_pet.id})
        res = self.client.get(analytics_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
