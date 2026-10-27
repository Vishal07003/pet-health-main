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

    def test_jwt_authenticated_telemetry_ingest_owner_success(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "is_simulation": True,
            "pet_id": str(self.pet.id),
            "device_uid": self.device.device_uid,
            "readings": [
                {
                    "accel_x": 0.25,
                    "accel_y": 1.05,
                    "accel_z": 0.15,
                    "battery_level": 85,
                }
            ],
        }
        res = self.client.post(self.ingest_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "success")
        self.assertEqual(res.data["ingested_count"], 1)

    def test_jwt_authenticated_telemetry_ingest_unowned_pet_rejected(self):
        other_user = User.objects.create_user(
            username="unauthorized_owner",
            email="uo@example.com",
            password="Password123!",
        )
        self.client.force_authenticate(user=other_user)
        payload = {
            "is_simulation": True,
            "pet_id": str(self.pet.id),
            "readings": [
                {"accel_x": 0.1, "accel_y": 1.0, "accel_z": 0.1}
            ],
        }
        res = self.client.post(self.ingest_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_jwt_authenticated_telemetry_ingest_unowned_device_rejected(self):
        other_user = User.objects.create_user(
            username="unowned_dev_user",
            email="odu@example.com",
            password="Password123!",
        )
        other_pet = Pet.objects.create(owner=other_user, name="Bella", species="cat")
        self.client.force_authenticate(user=other_user)
        # Trying to ingest using self.device (which belongs to self.user)
        payload = {
            "is_simulation": True,
            "pet_id": str(other_pet.id),
            "device_uid": self.device.device_uid,
            "readings": [
                {"accel_x": 0.1, "accel_y": 1.0, "accel_z": 0.1}
            ],
        }
        res = self.client.post(self.ingest_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_intra_batch_duplicate_timestamps_handled_gracefully(self):
        """Verify that identical timestamps submitted in the same payload do not cause integrity crashes."""
        now_ts = "2026-10-27T10:00:00Z"
        payload = {
            "is_simulation": False,
            "readings": [
                {"accel_x": 0.1, "accel_y": 1.0, "accel_z": 0.1, "timestamp": now_ts},
                {"accel_x": 0.2, "accel_y": 1.1, "accel_z": 0.2, "timestamp": now_ts},  # duplicate in batch
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
        self.assertEqual(TelemetryReading.objects.filter(device=self.device, timestamp=now_ts).count(), 1)

    def test_mixed_existing_and_new_readings_batch(self):
        """Verify that a batch with some pre-existing and some new readings ingests only the new records."""
        existing_ts = "2026-10-27T10:05:00Z"
        new_ts_1 = "2026-10-27T10:06:00Z"
        new_ts_2 = "2026-10-27T10:07:00Z"

        # Pre-seed one reading
        TelemetryReading.objects.create(
            device=self.device,
            pet=self.pet,
            accel_x=0.05,
            accel_y=0.98,
            accel_z=0.12,
            accel_magnitude=0.988,
            timestamp=existing_ts,
            is_simulation=False,
        )

        payload = {
            "is_simulation": False,
            "readings": [
                {"accel_x": 0.05, "accel_y": 0.98, "accel_z": 0.12, "timestamp": existing_ts},  # duplicate
                {"accel_x": 0.15, "accel_y": 1.05, "accel_z": 0.18, "timestamp": new_ts_1},     # new
                {"accel_x": 0.20, "accel_y": 1.10, "accel_z": 0.22, "timestamp": new_ts_2},     # new
                {"accel_x": 0.20, "accel_y": 1.10, "accel_z": 0.22, "timestamp": new_ts_2},     # intra-batch dup
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
        self.assertEqual(res.data["ingested_count"], 2)
        self.assertEqual(TelemetryReading.objects.filter(device=self.device).count(), 3)

    def test_ingestion_query_efficiency(self):
        """Assert that a batch of 20 readings uses bounded, minimal SQL queries rather than 20+ queries."""
        batch = [
            {
                "accel_x": 0.1,
                "accel_y": 1.0,
                "accel_z": 0.2,
                "timestamp": f"2026-10-27T11:{i:02d}:00Z",
            }
            for i in range(20)
        ]
        with self.assertNumQueries(5):  # 1 auth, 1 batch timestamps check, 1 bulk create, 1 device update, 1 window query
            res = self.client.post(
                self.ingest_url,
                {"is_simulation": True, "readings": batch},
                format="json",
                HTTP_X_DEVICE_UID=self.device.device_uid,
                HTTP_X_DEVICE_KEY=self.raw_token,
            )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["ingested_count"], 20)
