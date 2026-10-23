from rest_framework.routers import DefaultRouter
from .views import (
    PetViewSet,
    WeightRecordViewSet,
    MedicalRecordViewSet,
    VetAppointmentViewSet,
)

router = DefaultRouter()
router.register(r"weights", WeightRecordViewSet, basename="pet-weight")
router.register(r"medical-records", MedicalRecordViewSet, basename="pet-medical")
router.register(r"appointments", VetAppointmentViewSet, basename="pet-appointment")
router.register(r"", PetViewSet, basename="pet")

urlpatterns = router.urls
