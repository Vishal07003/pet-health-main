from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from devices.models import Device
from pets.models import Pet
from telemetry.models import TelemetryReading
from .models import ActivitySummary

User = get_user_model()


class InsightsAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="insights_user",
            email="iu@example.com",
            password="Password123!",
        )
        self.pet = Pet.objects.create(
            owner=self.user,
            name="Daisy",
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
        from django.utils import timezone
        self.client.force_authenticate(user=self.user)
        now = timezone.now()
        # Create a series of normal walking and active readings within the window
        for i in range(10):
            TelemetryReading.objects.create(
                device=self.device,
                pet=self.pet,
                accel_x=0.1,
                accel_y=1.4,
                accel_z=0.2,
                accel_magnitude=1.4177,
                timestamp=now - timezone.timedelta(minutes=i * 2),
                is_simulation=True,
            )

        gen_url = reverse("insights-generate", kwargs={"pet_id": self.pet.id})
        res = self.client.post(gen_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(str(res.data["pet"]), str(self.pet.id))
        self.assertIn("dominant_state", res.data)
        self.assertIn("confidence_score", res.data)
        self.assertIn("anomaly_detected", res.data)

        # Ensure summary is stored in database
        self.assertTrue(ActivitySummary.objects.filter(pet=self.pet).exists())
