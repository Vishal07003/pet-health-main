from django.urls import path
from .views import PetInsightsListView, GenerateInsightsView, PetAnalyticsView

urlpatterns = [
    path("", PetInsightsListView.as_view(), name="insights-list"),
    path("generate/<uuid:pet_id>/", GenerateInsightsView.as_view(), name="insights-generate"),
    path("pet/<uuid:pet_id>/analytics/", PetAnalyticsView.as_view(), name="pet-analytics"),
]
