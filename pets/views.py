from rest_framework import viewsets, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from .models import Pet
from .serializers import PetSerializer
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
