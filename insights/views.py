from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from .models import ActivitySummary
from .serializers import ActivitySummarySerializer
from .services import ActivityInferenceEngine, PetAnalyticsService
from pets.models import Pet


class PetInsightsListView(generics.ListAPIView):
    """
    Returns historical activity summaries and probabilistic observations for a pet.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ActivitySummarySerializer

    def get_queryset(self):
        pet_id = self.request.query_params.get("pet_id")
        include_sim = self.request.query_params.get("include_simulation", "true").lower() == "true"
        qs = ActivitySummary.objects.filter(pet__owner=self.request.user)
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        if not include_sim:
            qs = qs.filter(is_simulation=False)
        return qs[:50]


class GenerateInsightsView(APIView):
    """
    Calculates and registers a fresh activity summary window for a pet.
    Supports is_simulation query parameter to keep simulated telemetry cleanly partitioned.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Compute activity insights for a pet",
        parameters=[
            OpenApiParameter(
                name="is_simulation",
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Whether to process simulated or physical telemetry",
            ),
        ],
        responses={200: ActivitySummarySerializer},
    )
    def post(self, request, pet_id):
        try:
            pet = Pet.objects.get(id=pet_id, owner=request.user)
        except Pet.DoesNotExist:
            return Response({"detail": "Pet not found."}, status=status.HTTP_404_NOT_FOUND)

        is_simulation = request.query_params.get("is_simulation", "false").lower() == "true"
        summary = ActivityInferenceEngine.compute_window_insights(pet=pet, is_simulation=is_simulation)
        if not summary:
            return Response(
                {"detail": "No telemetry readings available in the current window to generate insights."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(ActivitySummarySerializer(summary).data, status=status.HTTP_200_OK)


class PetAnalyticsView(APIView):
    """
    Returns comprehensive, factual health and activity analytics for a pet:
    - Personalized historical baseline (mean/std of active & rest minutes)
    - Today's summary and 7-day rolling daily trends
    - Statistical Z-Score activity anomaly assessment
    - Factual food and water intake summaries
    - Transparent actionable insights with clinical disclaimer
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get comprehensive activity & health analytics for a pet",
        parameters=[
            OpenApiParameter(
                name="include_simulation",
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Include simulated telemetry in calculations (default false)",
            ),
        ],
    )
    def get(self, request, pet_id):
        try:
            pet = Pet.objects.get(id=pet_id, owner=request.user)
        except Pet.DoesNotExist:
            return Response({"detail": "Pet not found."}, status=status.HTTP_404_NOT_FOUND)

        include_sim = request.query_params.get("include_simulation", "false").lower() == "true"
        analytics = PetAnalyticsService.generate_pet_analytics(pet=pet, include_simulation=include_sim)
        return Response(analytics, status=status.HTTP_200_OK)
