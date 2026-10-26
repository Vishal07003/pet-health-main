from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from pets.models import Pet
from .models import DeviceFCMToken, Notification

User = get_user_model()


class NotificationAPITests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="owner_alice",
            email="alice@example.com",
            password="AlicePassword123!",
        )
        self.user2 = User.objects.create_user(
            username="owner_bob",
            email="bob@example.com",
            password="BobPassword123!",
        )
        self.pet1 = Pet.objects.create(
            name="Bella",
            species=Pet.Species.DOG,
            owner=self.user1,
        )

        self.register_token_url = reverse("notification-device-register-token")
        self.unregister_token_url = reverse("notification-device-unregister-token")
        self.notifications_list_url = reverse("notification-list")

    def test_unauthenticated_requests_are_rejected(self):
        res = self.client.get(self.notifications_list_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_register_fcm_token_success_and_refresh(self):
        self.client.force_authenticate(user=self.user1)

        # 1. Register new token
        payload = {
            "token": "fcm_test_token_alice_device_001",
            "platform": "android",
            "device_name": "Pixel 8 Pro",
        }
        res = self.client.post(self.register_token_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "registered")

        self.assertTrue(
            DeviceFCMToken.objects.filter(
                user=self.user1,
                token="fcm_test_token_alice_device_001",
                is_active=True,
            ).exists()
        )

        # 2. Refresh same token (idempotent / last_seen updated)
        res_refresh = self.client.post(self.register_token_url, payload, format="json")
        self.assertEqual(res_refresh.status_code, status.HTTP_200_OK)
        self.assertFalse(res_refresh.data["created"])
        self.assertEqual(DeviceFCMToken.objects.filter(user=self.user1).count(), 1)

    def test_multi_device_support_for_same_owner(self):
        self.client.force_authenticate(user=self.user1)

        self.client.post(
            self.register_token_url,
            {"token": "fcm_token_phone", "platform": "android", "device_name": "Galaxy S24"},
            format="json",
        )
        self.client.post(
            self.register_token_url,
            {"token": "fcm_token_tablet", "platform": "android", "device_name": "Galaxy Tab S9"},
            format="json",
        )

        active_tokens = DeviceFCMToken.objects.filter(user=self.user1, is_active=True)
        self.assertEqual(active_tokens.count(), 2)

    def test_unregister_fcm_token_on_logout(self):
        self.client.force_authenticate(user=self.user1)

        token = "fcm_test_token_to_unregister"
        DeviceFCMToken.objects.create(
            user=self.user1,
            token=token,
            platform=DeviceFCMToken.Platform.ANDROID,
            is_active=True,
        )

        res = self.client.post(self.unregister_token_url, {"token": token}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        device_record = DeviceFCMToken.objects.get(token=token)
        self.assertFalse(device_record.is_active)

    def test_owner_level_notification_isolation(self):
        # Alice notification
        notif_alice = Notification.objects.create(
            user=self.user1,
            pet=self.pet1,
            notification_type=Notification.NotificationType.ACTIVITY_ANOMALY,
            title="Alice Notification",
            message="Bella was running fast",
        )
        # Bob notification
        notif_bob = Notification.objects.create(
            user=self.user2,
            notification_type=Notification.NotificationType.SYSTEM,
            title="Bob Notification",
            message="System notice for Bob",
        )

        # Alice listing should only return her own notification
        self.client.force_authenticate(user=self.user1)
        res_alice = self.client.get(self.notifications_list_url)
        self.assertEqual(res_alice.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_alice.data), 1)
        self.assertEqual(res_alice.data[0]["id"], str(notif_alice.id))

        # Alice cannot retrieve Bob's notification
        detail_url_bob = reverse("notification-detail", kwargs={"pk": notif_bob.id})
        res_bob_detail = self.client.get(detail_url_bob)
        self.assertEqual(res_bob_detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_mark_single_and_all_read(self):
        notif1 = Notification.objects.create(
            user=self.user1,
            title="Alert 1",
            message="Message 1",
            is_read=False,
        )
        notif2 = Notification.objects.create(
            user=self.user1,
            title="Alert 2",
            message="Message 2",
            is_read=False,
        )

        self.client.force_authenticate(user=self.user1)

        # 1. Mark single notification as read
        mark_read_url = reverse("notification-mark-read", kwargs={"pk": notif1.id})
        res_single = self.client.post(mark_read_url)
        self.assertEqual(res_single.status_code, status.HTTP_200_OK)
        notif1.refresh_from_db()
        self.assertTrue(notif1.is_read)
        self.assertIsNotNone(notif1.read_at)

        # 2. Mark all as read
        mark_all_url = reverse("notification-mark-all-read")
        res_all = self.client.post(mark_all_url)
        self.assertEqual(res_all.status_code, status.HTTP_200_OK)
        self.assertEqual(res_all.data["marked_read_count"], 1)

        notif2.refresh_from_db()
        self.assertTrue(notif2.is_read)

    @patch("notifications.services.get_firebase_app")
    def test_delivery_status_tracking(self, mock_get_app):
        # When Firebase app is None (unconfigured dev), record delivery_status as QUEUED
        mock_get_app.return_value = None

        DeviceFCMToken.objects.create(
            user=self.user1,
            token="fcm_valid_token_test",
            platform="android",
            is_active=True,
        )

        self.client.force_authenticate(user=self.user1)
        res = self.client.post(
            self.notifications_list_url,
            {
                "notification_type": "vitals_alert",
                "title": "Resting Pulse Check",
                "message": "Manual observation needed",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        created_notif = Notification.objects.get(id=res.data["id"])
        self.assertEqual(created_notif.delivery_status, Notification.DeliveryStatus.QUEUED)
        self.assertEqual(created_notif.delivery_attempts, 1)
