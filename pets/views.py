from django.utils import timezone
from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from .models import (
    Pet,
    WeightRecord,
    MedicalRecord,
    VetAppointment,
    BodyConditionScore,
    ClinicalObservation,
    FoodWaterLog,
)
from .serializers import (
    PetSerializer,
    WeightRecordSerializer,
    MedicalRecordSerializer,
    VetAppointmentSerializer,
    BodyConditionScoreSerializer,
    ClinicalObservationSerializer,
    FoodWaterLogSerializer,
)
from .permissions import IsOwner


@extend_schema_view(
    list=extend_schema(summary="List all pets owned by the authenticated user"),
    create=extend_schema(summary="Create a new pet profile for the authenticated user"),
    retrieve=extend_schema(summary="Retrieve pet details by ID"),
    update=extend_schema(summary="Update all details of a pet"),
    partial_update=extend_schema(summary="Partially update details of a pet"),
    destroy=extend_schema(summary="Delete a pet profile"),
)
class PetViewSet(viewsets.ModelViewSet):
    """
    CRUD API for pet management.
    Restricts access strictly to pets owned by the authenticated user.
    """
    queryset = Pet.objects.all()
    serializer_class = PetSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["species", "sex", "is_neutered"]
    search_fields = ["name", "breed", "microchip_number"]
    ordering_fields = ["created_at", "name", "weight_kg"]
    ordering = ["-created_at"]

    def get_queryset(self):
        # Prevent AnonymousUser crashes during swagger schema generation
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return Pet.objects.none()
        # Strict owner isolation at the queryset level
        return Pet.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        # The authenticated user is strictly assigned as the owner
        serializer.save(owner=self.request.user)


class WeightRecordViewSet(viewsets.ModelViewSet):
    serializer_class = WeightRecordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return WeightRecord.objects.none()
        qs = WeightRecord.objects.filter(pet__owner=self.request.user)
        pet_id = self.request.query_params.get("pet") or self.request.query_params.get("pet_id")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs

    def perform_create(self, serializer):
        # Ensure pet belongs to authenticated user
        pet = serializer.validated_data.get("pet")
        if pet.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this pet.")
        record = serializer.save()
        # Optionally update latest weight on pet
        pet.weight_kg = record.weight_kg
        pet.save(update_fields=["weight_kg"])


class MedicalRecordViewSet(viewsets.ModelViewSet):
    serializer_class = MedicalRecordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return MedicalRecord.objects.none()
        qs = MedicalRecord.objects.filter(pet__owner=self.request.user)
        pet_id = self.request.query_params.get("pet") or self.request.query_params.get("pet_id")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs

    def perform_create(self, serializer):
        pet = serializer.validated_data.get("pet")
        if pet.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this pet.")
        serializer.save()


class VetAppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = VetAppointmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return VetAppointment.objects.none()
        qs = VetAppointment.objects.filter(pet__owner=self.request.user)
        pet_id = self.request.query_params.get("pet") or self.request.query_params.get("pet_id")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs

    def perform_create(self, serializer):
        pet = serializer.validated_data.get("pet")
        if pet.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this pet.")
        serializer.save()


class BodyConditionScoreViewSet(viewsets.ModelViewSet):
    serializer_class = BodyConditionScoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return BodyConditionScore.objects.none()
        qs = BodyConditionScore.objects.filter(pet__owner=self.request.user)
        pet_id = self.request.query_params.get("pet") or self.request.query_params.get("pet_id")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return qs

    def perform_create(self, serializer):
        pet = serializer.validated_data.get("pet")
        if pet.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this pet.")
        serializer.save()


class ClinicalObservationViewSet(viewsets.ModelViewSet):
    serializer_class = ClinicalObservationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return ClinicalObservation.objects.none()
        qs = ClinicalObservation.objects.filter(pet__owner=self.request.user)
        pet_id = self.request.query_params.get("pet") or self.request.query_params.get("pet_id")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        return qs

    def perform_create(self, serializer):
        pet = serializer.validated_data.get("pet")
        if pet.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this pet.")
        serializer.save(is_manual_entry=True)


class FoodWaterLogViewSet(viewsets.ModelViewSet):
    serializer_class = FoodWaterLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return FoodWaterLog.objects.none()
        qs = FoodWaterLog.objects.filter(pet__owner=self.request.user)
        pet_id = self.request.query_params.get("pet") or self.request.query_params.get("pet_id")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        intake_type = self.request.query_params.get("intake_type")
        if intake_type:
            qs = qs.filter(intake_type=intake_type)
        return qs

    def perform_create(self, serializer):
        pet = serializer.validated_data.get("pet")
        if pet.owner != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not own this pet.")
        serializer.save(is_manual_entry=True)

    @action(detail=False, methods=["get"], url_path="daily-totals")
    def daily_totals(self, request):
        from django.db.models import Sum
        pet_id = request.query_params.get("pet") or request.query_params.get("pet_id")
        date_str = request.query_params.get("date")  # YYYY-MM-DD
        qs = self.get_queryset()
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        if date_str:
            qs = qs.filter(logged_at__date=date_str)
        else:
            qs = qs.filter(logged_at__date=timezone.now().date())

        # Group by intake_type and unit
        totals = []
        for intake in [FoodWaterLog.IntakeType.FOOD, FoodWaterLog.IntakeType.WATER]:
            subset = qs.filter(intake_type=intake)
            units = subset.values_list("unit", flat=True).distinct()
            for u in units:
                sub_unit = subset.filter(unit=u)
                total_qty = sub_unit.aggregate(total=Sum("amount"))["total"] or 0
                count = sub_unit.count()
                totals.append({
                    "intake_type": intake,
                    "unit": u,
                    "total_amount": float(total_qty),
                    "entry_count": count,
                })

        return Response({
            "pet_id": pet_id,
            "date": date_str or str(timezone.now().date()),
            "totals": totals,
            "has_data": len(totals) > 0,
        })

