import json
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from notifications.models import DeviceFCMToken, Notification
from notifications.services import send_fcm_push
from pets.models import Pet

User = get_user_model()


class Command(BaseCommand):
    help = "Sends a real test push notification to an authenticated user's registered device (DEV ONLY)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            type=str,
            required=True,
            help="Username of the device owner to receive the test push",
        )
        parser.add_argument(
            "--title",
            type=str,
            default="Pet Health Test Alert",
            help="Notification title",
        )
        parser.add_argument(
            "--message",
            type=str,
            default="This is a test notification confirming FCM configuration is working end-to-end.",
            help="Notification message body",
        )
        parser.add_argument(
            "--type",
            type=str,
            default=Notification.NotificationType.SYSTEM,
            choices=[c[0] for c in Notification.NotificationType.choices],
            help="Notification type",
        )

    def handle(self, *args, **options):
        username = options["username"]
        title = options["title"]
        message = options["message"]
        notif_type = options["type"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User '{username}' does not exist."))
            return

        tokens_qs = DeviceFCMToken.objects.filter(user=user, is_active=True)
        token_count = tokens_qs.count()

        if token_count == 0:
            self.stdout.write(
                self.style.WARNING(
                    f"User '{username}' has NO active device FCM tokens registered. "
                    "Open the Pet Health mobile app on your Android device while logged in as this user to register a token."
                )
            )

        # Associate with first pet if any
        pet = Pet.objects.filter(owner=user).first()

        notif = Notification.objects.create(
            user=user,
            pet=pet,
            notification_type=notif_type,
            title=title,
            message=message,
            metadata={"is_test": True, "pet_id": str(pet.id) if pet else ""},
        )

        self.stdout.write(f"Created Notification [ID: {notif.id}] in database. Dispatching via FCM...")
        result = send_fcm_push(user, notif)
        notif.refresh_from_db()

        self.stdout.write(
            self.style.SUCCESS(
                f"Result: {result} | Delivery Status: {notif.delivery_status} | Error: {notif.delivery_error or 'None'}"
            )
        )
