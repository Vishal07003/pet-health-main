from django.urls import path
from .views import TelemetryIngestView, TelemetryListView

urlpatterns = [
    path("ingest/", TelemetryIngestView.as_view(), name="telemetry-ingest"),
    path("", TelemetryListView.as_view(), name="telemetry-list"),
]
