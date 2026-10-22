from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class AuthenticationAPITests(APITestCase):
    def setUp(self):
        self.register_url = reverse("auth-register")
        self.login_url = reverse("auth-login")
        self.refresh_url = reverse("auth-refresh")
        self.me_url = reverse("auth-me")
        self.valid_user_data = {
            "username": "petowner1",
            "email": "owner1@example.com",
            "first_name": "Jane",
            "last_name": "Doe",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
        }

    def test_user_registration_success(self):
        response = self.client.post(self.register_url, self.valid_user_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("tokens", response.data)
        self.assertIn("access", response.data["tokens"])
        self.assertIn("refresh", response.data["tokens"])
        self.assertEqual(response.data["user"]["username"], "petowner1")
        self.assertEqual(response.data["user"]["email"], "owner1@example.com")
        self.assertTrue(User.objects.filter(username="petowner1").exists())

    def test_registration_duplicate_username_fails(self):
        self.client.post(self.register_url, self.valid_user_data, format="json")
        duplicate_data = self.valid_user_data.copy()
        duplicate_data["email"] = "other@example.com"
        response = self.client.post(self.register_url, duplicate_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.data)

    def test_registration_duplicate_email_fails(self):
        self.client.post(self.register_url, self.valid_user_data, format="json")
        duplicate_data = self.valid_user_data.copy()
        duplicate_data["username"] = "different_user"
        duplicate_data["email"] = "OWNER1@example.com"  # Case-insensitive duplicate
        response = self.client.post(self.register_url, duplicate_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_registration_password_mismatch_fails(self):
        data = self.valid_user_data.copy()
        data["password_confirm"] = "DifferentPass123!"
        response = self.client.post(self.register_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password_confirm", response.data)

    def test_registration_weak_password_fails(self):
        data = self.valid_user_data.copy()
        data["password"] = "123"
        data["password_confirm"] = "123"
        response = self.client.post(self.register_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_successful_jwt(self):
        User.objects.create_user(
            username="petowner2",
            email="owner2@example.com",
            password="StrongPassword123!",
        )
        login_data = {
            "username": "petowner2",
            "password": "StrongPassword123!",
        }
        response = self.client.post(self.login_url, login_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_invalid_credentials_fails(self):
        User.objects.create_user(
            username="petowner2",
            email="owner2@example.com",
            password="StrongPassword123!",
        )
        login_data = {
            "username": "petowner2",
            "password": "WrongPassword999!",
        }
        response = self.client.post(self.login_url, login_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_refresh(self):
        user = User.objects.create_user(
            username="petowner3",
            email="owner3@example.com",
            password="StrongPassword123!",
        )
        login_res = self.client.post(
            self.login_url,
            {"username": "petowner3", "password": "StrongPassword123!"},
            format="json",
        )
        refresh_token = login_res.data["refresh"]

        refresh_res = self.client.post(
            self.refresh_url,
            {"refresh": refresh_token},
            format="json",
        )
        self.assertEqual(refresh_res.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_res.data)

    def test_authenticated_me_endpoint(self):
        user = User.objects.create_user(
            username="petowner4",
            email="owner4@example.com",
            first_name="Max",
            last_name="Payne",
            password="StrongPassword123!",
        )
        # Unauthenticated request fails
        unauth_res = self.client.get(self.me_url)
        self.assertEqual(unauth_res.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticated request succeeds
        self.client.force_authenticate(user=user)
        auth_res = self.client.get(self.me_url)
        self.assertEqual(auth_res.status_code, status.HTTP_200_OK)
        self.assertEqual(auth_res.data["username"], "petowner4")
        self.assertEqual(auth_res.data["first_name"], "Max")
