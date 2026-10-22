from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema, OpenApiResponse
from .serializers import RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    """
    Public registration endpoint for pet owners.
    Generates and returns JWT access and refresh tokens upon successful signup.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer
    throttle_scope = "auth"

    @extend_schema(
        summary="Register a new user account",
        description="Creates a new pet owner account and returns JWT credentials.",
        responses={
            201: OpenApiResponse(description="User registered successfully", response=UserSerializer),
            400: OpenApiResponse(description="Validation error (e.g., duplicate email/username, mismatched password)"),
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Issue JWT tokens directly so the user is immediately authenticated
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "user": UserSerializer(user).data,
                "tokens": {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                },
                "message": "User registered successfully.",
            },
            status=status.HTTP_201_CREATED,
        )


class MeView(generics.RetrieveUpdateAPIView):
    """
    Protected endpoint to view or update current user profile.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    @extend_schema(
        summary="Get current user profile",
        description="Returns details of the currently authenticated user.",
        responses={200: UserSerializer},
    )
    def get_object(self):
        return self.request.user
