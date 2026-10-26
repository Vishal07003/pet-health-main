from rest_framework.routers import DefaultRouter
from .views import DeviceFCMTokenViewSet, NotificationViewSet

router = DefaultRouter()
router.register(r"devices", DeviceFCMTokenViewSet, basename="notification-device")
router.register(r"", NotificationViewSet, basename="notification")

urlpatterns = router.urls
