from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from devices.models import Device
from pets.models import Pet
from .models import TelemetryReading

User = get_user_model()


class TelemetryAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="telem_user",
            email="tu@example.com",
            password="Password123!",
        )
        self.pet = Pet.objects.create(
            owner=self.user,
            name="Rocky",
            species="dog",
        )
        self.raw_token = Device.generate_raw_token()
        self.device = Device.objects.create(
            owner=self.user,
            pet=self.pet,
            name="ESP32 Collar",
            device_uid="ESP32_TEST_01",
            status=Device.Status.PAIRED,
        )
        self.device.set_api_key(self.raw_token)
        self.device.save()
        self.ingest_url = reverse("telemetry-ingest")

    def test_telemetry_ingest_with_device_credentials(self):
        payload = {
            "is_simulation": False,
            "readings": [
                {
                    "accel_x": 0.05,
                    "accel_y": 0.98,
                    "accel_z": 0.12,
                    "gyro_x": 1.2,
                    "gyro_y": -0.5,
                    "gyro_z": 0.0,
                    "battery_level": 92,
                    "rssi": -65,
                }
            ],
        }
        res = self.client.post(
            self.ingest_url,
            payload,
            format="json",
            HTTP_X_DEVICE_UID=self.device.device_uid,
            HTTP_X_DEVICE_KEY=self.raw_token,
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["ingested_count"], 1)

        reading = TelemetryReading.objects.filter(device=self.device).first()
        self.assertIsNotNone(reading)
        self.assertEqual(reading.pet, self.pet)
        self.assertFalse(reading.is_simulation)
        self.assertAlmostEqual(reading.accel_magnitude, 0.988, places=2)

    def test_telemetry_simulation_flag_separation(self):
        payload = {
            "is_simulation": True,
            "readings": [
                {
                    "accel_x": 1.10,
                    "accel_y": 0.20,
                    "accel_z": 0.30,
                    "battery_level": 100,
                }
            ],
        }
        res = self.client.post(
            self.ingest_url,
            payload,
            format="json",
            HTTP_X_DEVICE_UID=self.device.device_uid,
            HTTP_X_DEVICE_KEY=self.raw_token,
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        reading = TelemetryReading.objects.filter(device=self.device).first()
        self.assertTrue(reading.is_simulation)

    def test_invalid_device_key_rejected(self):
        payload = {
            "readings": [{"accel_x": 0.1, "accel_y": 1.0, "accel_z": 0.1}],
        }
        res = self.client.post(
            self.ingest_url,
            payload,
            format="json",
            HTTP_X_DEVICE_UID=self.device.device_uid,
            HTTP_X_DEVICE_KEY="wrong_token",
        )
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
