from unittest.mock import patch, MagicMock
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from pets.models import Pet
from devices.models import Device
from telemetry.models import TelemetryReading
from insights.models import ActivitySummary
from .models import DeviceFCMToken, Notification
from .services import NotificationDispatcher, send_fcm_push
from .management.commands.dispatch_scheduled_notifications import (
    process_daily_summaries,
    process_weekly_insights,
)

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
        self.device1 = Device.objects.create(
            owner=self.user1,
            pet=self.pet1,
            name="Bella Collar",
            device_uid="ESP32_BELLA_01",
            status=Device.Status.PAIRED,
        )

        self.register_token_url = reverse("notification-device-register-token")
        self.unregister_token_url = reverse("notification-device-unregister-token")
        self.notifications_list_url = reverse("notification-list")

    def test_unauthenticated_requests_are_rejected(self):
        res = self.client.get(self.notifications_list_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_register_fcm_token_success_and_refresh(self):
        self.client.force_authenticate(user=self.user1)

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
        notif_alice = Notification.objects.create(
            user=self.user1,
            pet=self.pet1,
            notification_type=Notification.NotificationType.ACTIVITY_ANOMALY,
            title="Alice Notification",
            message="Bella was running fast",
        )
        notif_bob = Notification.objects.create(
            user=self.user2,
            notification_type=Notification.NotificationType.SYSTEM,
            title="Bob Notification",
            message="System notice for Bob",
        )

        self.client.force_authenticate(user=self.user1)
        res_alice = self.client.get(self.notifications_list_url)
        self.assertEqual(res_alice.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_alice.data), 1)
        self.assertEqual(res_alice.data[0]["id"], str(notif_alice.id))

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
        mark_read_url = reverse("notification-mark-read", kwargs={"pk": notif1.id})
        res_single = self.client.post(mark_read_url)
        self.assertEqual(res_single.status_code, status.HTTP_200_OK)
        notif1.refresh_from_db()
        self.assertTrue(notif1.is_read)

        mark_all_url = reverse("notification-mark-all-read")
        res_all = self.client.post(mark_all_url)
        self.assertEqual(res_all.status_code, status.HTTP_200_OK)
        self.assertEqual(res_all.data["marked_read_count"], 1)
        notif2.refresh_from_db()
        self.assertTrue(notif2.is_read)

    @patch("notifications.services.get_firebase_app")
    def test_delivery_status_tracking(self, mock_get_app):
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

    # --- REQUIREMENT 1: Immediate real anomaly alert with cooldown & duplicate prevention ---
    @patch("notifications.services.send_fcm_push")
    def test_immediate_real_anomaly_alert_and_cooldown(self, mock_send_push):
        mock_send_push.return_value = {"status": "completed", "sent_count": 1}

        # First alert fires
        notif1 = NotificationDispatcher.dispatch_activity_anomaly(
            pet=self.pet1,
            reason="High acceleration spike of 4.2G detected.",
            is_simulation=False,
        )
        self.assertIsNotNone(notif1)
        self.assertEqual(notif1.notification_type, Notification.NotificationType.ACTIVITY_ANOMALY)
        self.assertEqual(mock_send_push.call_count, 1)

        # Immediate duplicate alert within cooldown window (2h) must be suppressed
        notif2 = NotificationDispatcher.dispatch_activity_anomaly(
            pet=self.pet1,
            reason="High acceleration spike of 4.5G detected.",
            is_simulation=False,
        )
        self.assertIsNone(notif2)
        # Call count remains 1 (no duplicate sent)
        self.assertEqual(mock_send_push.call_count, 1)

    # --- REQUIREMENT 5: Simulated telemetry never creates real health push ---
    @patch("notifications.services.send_fcm_push")
    def test_simulated_anomaly_creates_no_real_health_push(self, mock_send_push):
        notif = NotificationDispatcher.dispatch_activity_anomaly(
            pet=self.pet1,
            reason="Simulated spike of 5.0G",
            is_simulation=True,  # SIMULATED
        )
        self.assertIsNone(notif)
        mock_send_push.assert_not_called()
        self.assertFalse(
            Notification.objects.filter(pet=self.pet1, notification_type=Notification.NotificationType.ACTIVITY_ANOMALY).exists()
        )

    # --- REQUIREMENT 2 & 4: Daily summary requires sufficient data & prevents duplicates ---
    @patch("notifications.services.send_fcm_push")
    def test_daily_summary_requires_sufficient_data_and_prevents_duplicate(self, mock_send_push):
        today = timezone.now().date()

        # 1. Insufficient data: < 30 samples creates NO notification
        insufficient_metrics = {
            "date": str(today),
            "total_samples": 10,
            "total_moving_minutes": 5,
            "rest_minutes": 20,
            "is_sufficient": False,
        }
        res_insufficient = NotificationDispatcher.dispatch_daily_summary(
            pet=self.pet1,
            daily_metrics=insufficient_metrics,
            target_date=today,
        )
        self.assertIsNone(res_insufficient)
        mock_send_push.assert_not_called()

        # 2. Sufficient data: >= 30 samples creates daily summary
        sufficient_metrics = {
            "date": str(today),
            "total_samples": 45,
            "total_moving_minutes": 35,
            "rest_minutes": 400,
            "is_sufficient": True,
        }
        res_sufficient = NotificationDispatcher.dispatch_daily_summary(
            pet=self.pet1,
            daily_metrics=sufficient_metrics,
            target_date=today,
        )
        self.assertIsNotNone(res_sufficient)
        self.assertEqual(res_sufficient.notification_type, Notification.NotificationType.DAILY_SUMMARY)
        self.assertEqual(mock_send_push.call_count, 1)

        # 3. Duplicate prevention: running again for the same pet & date skips
        res_dup = NotificationDispatcher.dispatch_daily_summary(
            pet=self.pet1,
            daily_metrics=sufficient_metrics,
            target_date=today,
        )
        self.assertIsNone(res_dup)
        self.assertEqual(mock_send_push.call_count, 1)

    # --- REQUIREMENT 3 & 4: Weekly insights requires sufficient data & prevents duplicates ---
    @patch("notifications.services.send_fcm_push")
    def test_weekly_insights_requires_sufficient_data_and_prevents_duplicate(self, mock_send_push):
        today = timezone.now().date()

        # 1. Insufficient weekly history: < 3 days of data
        insufficient_analytics = {
            "weekly_summary": [
                {"total_samples": 5, "total_moving_minutes": 2},
                {"total_samples": 0, "total_moving_minutes": 0},
            ],
            "personalized_insights": ["Insufficient data: need more days"],
        }
        res_insufficient = NotificationDispatcher.dispatch_weekly_insights(
            pet=self.pet1,
            analytics=insufficient_analytics,
            week_end_date=today,
        )
        self.assertIsNone(res_insufficient)
        mock_send_push.assert_not_called()

        # 2. Sufficient weekly history: >= 3 days with >= 20 samples each
        sufficient_analytics = {
            "weekly_summary": [
                {"total_samples": 30, "total_moving_minutes": 40},
                {"total_samples": 25, "total_moving_minutes": 45},
                {"total_samples": 35, "total_moving_minutes": 50},
                {"total_samples": 20, "total_moving_minutes": 30},
            ],
            "personalized_insights": [f"{self.pet1.name} maintained steady daily activity."],
        }
        res_sufficient = NotificationDispatcher.dispatch_weekly_insights(
            pet=self.pet1,
            analytics=sufficient_analytics,
            week_end_date=today,
        )
        self.assertIsNotNone(res_sufficient)
        self.assertEqual(res_sufficient.notification_type, Notification.NotificationType.WEEKLY_INSIGHTS)
        self.assertEqual(mock_send_push.call_count, 1)

        # 3. Duplicate prevention: running again skips within 6-day window
        res_dup = NotificationDispatcher.dispatch_weekly_insights(
            pet=self.pet1,
            analytics=sufficient_analytics,
            week_end_date=today,
        )
        self.assertIsNone(res_dup)
        self.assertEqual(mock_send_push.call_count, 1)

    # --- REQUIREMENT 6: Missing FCM token handled gracefully ---
    def test_send_fcm_push_without_device_tokens(self):
        notif = Notification.objects.create(
            user=self.user1,
            title="No Device Notification",
            message="Testing when user has no active tokens",
        )
        result = send_fcm_push(self.user1, notif)
        notif.refresh_from_db()
        self.assertEqual(result["status"], "no_device")
        self.assertEqual(notif.delivery_status, Notification.DeliveryStatus.NO_DEVICE)
        self.assertEqual(notif.delivery_attempts, 1)
