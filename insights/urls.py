from django.urls import path
from .views import PetInsightsListView, GenerateInsightsView

urlpatterns = [
    path("", PetInsightsListView.as_view(), name="insights-list"),
    path("generate/<uuid:pet_id>/", GenerateInsightsView.as_view(), name="insights-generate"),
]
