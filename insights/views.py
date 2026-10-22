from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from .models import ActivitySummary
from .serializers import ActivitySummarySerializer
from .services import ActivityInferenceEngine
from pets.models import Pet


class PetInsightsListView(generics.ListAPIView):
    """
    Returns historical activity summaries and probabilistic observations for a pet.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ActivitySummarySerializer

    def get_queryset(self):
        pet_id = self.request.query_params.get("pet_id")
        qs = ActivitySummary.objects.filter(pet__owner=self.request.user)
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs[:50]


class GenerateInsightsView(APIView):
    """
    Calculates and registers a fresh activity summary window for a pet.
    """
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Compute activity insights for a pet",
        responses={200: ActivitySummarySerializer},
    )
    def post(self, request, pet_id):
        try:
            pet = Pet.objects.get(id=pet_id, owner=request.user)
        except Pet.DoesNotExist:
            return Response({"detail": "Pet not found."}, status=status.HTTP_404_NOT_FOUND)

        summary = ActivityInferenceEngine.compute_window_insights(pet=pet)
        if not summary:
            return Response(
                {"detail": "No telemetry readings available in the current window to generate insights."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(ActivitySummarySerializer(summary).data, status=status.HTTP_200_OK)
