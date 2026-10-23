from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from .models import Pet, WeightRecord, MedicalRecord, VetAppointment
from .serializers import (
    PetSerializer,
    WeightRecordSerializer,
    MedicalRecordSerializer,
    VetAppointmentSerializer,
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
