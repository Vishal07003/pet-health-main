from rest_framework.routers import DefaultRouter
from .views import (
    PetViewSet,
    WeightRecordViewSet,
    MedicalRecordViewSet,
    VetAppointmentViewSet,
    BodyConditionScoreViewSet,
    ClinicalObservationViewSet,
    FoodWaterLogViewSet,
)

router = DefaultRouter()
router.register(r"weights", WeightRecordViewSet, basename="pet-weight")
router.register(r"bcs", BodyConditionScoreViewSet, basename="pet-bcs")
router.register(r"observations", ClinicalObservationViewSet, basename="pet-observation")
router.register(r"food-water", FoodWaterLogViewSet, basename="pet-food-water")
router.register(r"medical-records", MedicalRecordViewSet, basename="pet-medical")
router.register(r"appointments", VetAppointmentViewSet, basename="pet-appointment")
router.register(r"", PetViewSet, basename="pet")

urlpatterns = router.urls

