from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Device
from pets.models import Pet

User = get_user_model()


class DeviceAPITests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="device_user1",
            email="d1@example.com",
            password="Password123!",
        )
        self.user2 = User.objects.create_user(
            username="device_user2",
            email="d2@example.com",
            password="Password123!",
        )
        self.pet1 = Pet.objects.create(
            owner=self.user1,
            name="Charlie",
            species="dog",
        )
        self.pet2 = Pet.objects.create(
            owner=self.user2,
            name="Luna",
            species="cat",
        )
        self.list_url = reverse("device-list")

    def test_device_registration_returns_one_time_token(self):
        self.client.force_authenticate(user=self.user1)
        payload = {
            "name": "ESP32 Collar Charlie",
            "device_uid": "24:6F:28:AA:BB:CC",
            "hardware_type": "esp32_imu_collar",
            "firmware_version": "1.0.0",
        }
        res = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("token", res.data)
        self.assertEqual(res.data["device_uid"], "24:6F:28:AA:BB:CC")

        device = Device.objects.get(device_uid="24:6F:28:AA:BB:CC")
        self.assertEqual(device.owner, self.user1)
        self.assertTrue(device.check_api_key(res.data["token"]))
        # Verify secret token is NOT stored in plain text
        self.assertNotEqual(device.api_key_hash, res.data["token"])

    def test_device_pairing_with_pet(self):
        self.client.force_authenticate(user=self.user1)
        # Register device
        reg_res = self.client.post(
            self.list_url,
            {"name": "Collar 1", "device_uid": "AA:BB:CC:DD:EE:01"},
            format="json",
        )
        device_id = reg_res.data["id"]

        pair_url = reverse("device-pair", kwargs={"pk": device_id})
        pair_res = self.client.post(pair_url, {"pet_id": str(self.pet1.id)}, format="json")
        self.assertEqual(pair_res.status_code, status.HTTP_200_OK)
        self.assertEqual(pair_res.data["status"], "paired")
        self.assertEqual(str(pair_res.data["pet"]), str(self.pet1.id))

    def test_cannot_pair_another_users_pet(self):
        self.client.force_authenticate(user=self.user1)
        reg_res = self.client.post(
            self.list_url,
            {"name": "Collar 1", "device_uid": "AA:BB:CC:DD:EE:02"},
            format="json",
        )
        device_id = reg_res.data["id"]

        pair_url = reverse("device-pair", kwargs={"pk": device_id})
        # Attempt to pair pet2 which belongs to user2
        pair_res = self.client.post(pair_url, {"pet_id": str(self.pet2.id)}, format="json")
        self.assertEqual(pair_res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_cannot_access_or_pair_another_users_device(self):
        self.client.force_authenticate(user=self.user1)
        reg_res = self.client.post(
            self.list_url,
            {"name": "User1 Collar", "device_uid": "AA:BB:CC:DD:EE:03"},
            format="json",
        )
        device_id = reg_res.data["id"]

        # Switch to user2
        self.client.force_authenticate(user=self.user2)
        detail_url = reverse("device-detail", kwargs={"pk": device_id})
        res = self.client.get(detail_url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_unpair_and_revoke_device(self):
        self.client.force_authenticate(user=self.user1)
        reg_res = self.client.post(
            self.list_url,
            {"name": "Collar Revoke", "device_uid": "AA:BB:CC:DD:EE:04"},
            format="json",
        )
        device_id = reg_res.data["id"]

        # Pair
        pair_url = reverse("device-pair", kwargs={"pk": device_id})
        self.client.post(pair_url, {"pet_id": str(self.pet1.id)}, format="json")

        # Unpair
        unpair_url = reverse("device-unpair", kwargs={"pk": device_id})
        unpair_res = self.client.post(unpair_url)
        self.assertEqual(unpair_res.status_code, status.HTTP_200_OK)
        self.assertEqual(unpair_res.data["status"], "unpaired")
        self.assertIsNone(unpair_res.data["pet"])

        # Revoke
        revoke_url = reverse("device-revoke", kwargs={"pk": device_id})
        revoke_res = self.client.post(revoke_url)
        self.assertEqual(revoke_res.status_code, status.HTTP_200_OK)
        self.assertEqual(revoke_res.data["device"]["status"], "revoked")
