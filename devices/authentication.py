from rest_framework import authentication, exceptions
from .models import Device


class DeviceAPIKeyAuthentication(authentication.BaseAuthentication):
    """
    Dedicated authentication for ESP32 and telemetry clients.
    Authenticates via HTTP headers:
      X-Device-UID: <device_uid>
      X-Device-Key: <raw_secret_token>
    Or via Authorization: DeviceKey <raw_token> combined with X-Device-UID
    """

    def authenticate(self, request):
        device_uid = request.headers.get("X-Device-UID")
        raw_key = request.headers.get("X-Device-Key")

        if not device_uid or not raw_key:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("DeviceKey "):
                raw_key = auth_header.split(" ", 1)[1].strip()

        if not device_uid or not raw_key:
            return None  # Pass to subsequent authentication classes or fail permissions

        try:
            device = Device.objects.select_related("owner", "pet").get(device_uid=device_uid)
        except Device.DoesNotExist:
            raise exceptions.AuthenticationFailed("Unknown device UID.")

        if device.status == Device.Status.REVOKED:
            raise exceptions.AuthenticationFailed("Device credentials have been revoked.")

        if not device.check_api_key(raw_key):
            raise exceptions.AuthenticationFailed("Invalid device API credentials.")

        # In DRF, request.user becomes device.owner and request.auth is the device instance
        return (device.owner, device)
