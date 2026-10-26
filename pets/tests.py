from decimal import Decimal
import datetime
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Pet

User = get_user_model()


class PetAPITests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="owner_alice",
            email="alice@example.com",
            password="AlicePassword123!",
        )
        self.user2 = User.objects.create_user(
            username="owner_bob",
            email="bob@example.com",
            password="BobPassword123!",
        )

        self.pet1 = Pet.objects.create(
            name="Bella",
            species=Pet.Species.DOG,
            breed="Golden Retriever",
            sex=Pet.Sex.FEMALE,
            weight_kg=Decimal("28.50"),
            owner=self.user1,
        )

        self.list_create_url = reverse("pet-list")
        self.detail_url_pet1 = reverse("pet-detail", kwargs={"pk": self.pet1.id})

    def test_unauthenticated_requests_are_rejected(self):
        res = self.client.get(self.list_create_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_user_can_create_pet(self):
        self.client.force_authenticate(user=self.user1)
        payload = {
            "name": "Max",
            "species": "dog",
            "breed": "German Shepherd",
            "sex": "male",
            "date_of_birth": "2022-01-15",
            "weight_kg": "32.00",
            "is_neutered": True,
            "microchip_number": "985141001234567",
            # Attempt to set owner explicitly (must be ignored or overridden)
            "owner": "owner_bob",
            "owner_id": 9999,
        }
        res = self.client.post(self.list_create_url, payload, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["name"], "Max")
        self.assertEqual(res.data["owner"], "owner_alice")
        self.assertEqual(res.data["owner_id"], self.user1.id)

        created_pet = Pet.objects.get(id=res.data["id"])
        self.assertEqual(created_pet.owner, self.user1)

    def test_pet_validation_rules(self):
        self.client.force_authenticate(user=self.user1)

        # Future date of birth
        future_date = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        res_future_dob = self.client.post(
            self.list_create_url,
            {"name": "Milo", "species": "dog", "date_of_birth": future_date},
            format="json",
        )
        self.assertEqual(res_future_dob.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_of_birth", res_future_dob.data)

        # Negative or zero weight
        res_zero_weight = self.client.post(
            self.list_create_url,
            {"name": "Milo", "species": "dog", "weight_kg": "0.00"},
            format="json",
        )
        self.assertEqual(res_zero_weight.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("weight_kg", res_zero_weight.data)

        # Unrealistic weight > 200kg
        res_heavy_weight = self.client.post(
            self.list_create_url,
            {"name": "Milo", "species": "dog", "weight_kg": "250.00"},
            format="json",
        )
        self.assertEqual(res_heavy_weight.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("weight_kg", res_heavy_weight.data)

        # Blank name
        res_blank_name = self.client.post(
            self.list_create_url,
            {"name": "   ", "species": "dog"},
            format="json",
        )
        self.assertEqual(res_blank_name.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", res_blank_name.data)

    def test_owner_isolation_in_listing(self):
        # Alice owns pet1
        # Bob creates pet2
        Pet.objects.create(
            name="Whiskers",
            species=Pet.Species.CAT,
            breed="Siamese",
            owner=self.user2,
        )

        # Alice listing should only return pet1
        self.client.force_authenticate(user=self.user1)
        res_alice = self.client.get(self.list_create_url)
        self.assertEqual(res_alice.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_alice.data), 1)
        self.assertEqual(res_alice.data[0]["id"], str(self.pet1.id))

        # Bob listing should only return pet2
        self.client.force_authenticate(user=self.user2)
        res_bob = self.client.get(self.list_create_url)
        self.assertEqual(res_bob.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_bob.data), 1)
        self.assertEqual(res_bob.data[0]["name"], "Whiskers")

    def test_owner_cannot_retrieve_another_users_pet(self):
        # Bob tries to view Alice's pet
        self.client.force_authenticate(user=self.user2)
        res = self.client.get(self.detail_url_pet1)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_cannot_update_another_users_pet(self):
        # Bob tries to patch Alice's pet
        self.client.force_authenticate(user=self.user2)
        res = self.client.patch(self.detail_url_pet1, {"name": "Hacked Name"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.pet1.refresh_from_db()
        self.assertEqual(self.pet1.name, "Bella")

    def test_owner_cannot_delete_another_users_pet(self):
        # Bob tries to delete Alice's pet
        self.client.force_authenticate(user=self.user2)
        res = self.client.delete(self.detail_url_pet1)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Pet.objects.filter(id=self.pet1.id).exists())

    def test_owner_can_update_and_delete_own_pet(self):
        self.client.force_authenticate(user=self.user1)

        # Update
        patch_res = self.client.patch(
            self.detail_url_pet1,
            {"weight_kg": "29.20", "notes": "Gaining healthy weight"},
            format="json",
        )
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_res.data["weight_kg"], "29.20")

        # Delete
        delete_res = self.client.delete(self.detail_url_pet1)
        self.assertEqual(delete_res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Pet.objects.filter(id=self.pet1.id).exists())


class FoodWaterLogAPITests(APITestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(
            username="owner_alice",
            email="alice@example.com",
            password="AlicePassword123!",
        )
        self.user2 = User.objects.create_user(
            username="owner_bob",
            email="bob@example.com",
            password="BobPassword123!",
        )
        self.pet1 = Pet.objects.create(
            name="Bella",
            species=Pet.Species.DOG,
            breed="Golden Retriever",
            sex=Pet.Sex.FEMALE,
            weight_kg=Decimal("28.50"),
            owner=self.user1,
        )
        self.pet2 = Pet.objects.create(
            name="Milo",
            species=Pet.Species.CAT,
            breed="Persian",
            sex=Pet.Sex.MALE,
            weight_kg=Decimal("4.50"),
            owner=self.user2,
        )
        self.list_url = reverse("pet-food-water-list")
        self.daily_totals_url = reverse("pet-food-water-daily-totals")

    def test_unauthenticated_requests_rejected(self):
        res = self.client.get(self.list_url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_owner_can_log_food_and_water(self):
        self.client.force_authenticate(user=self.user1)

        # Log food
        food_res = self.client.post(
            self.list_url,
            {
                "pet": str(self.pet1.id),
                "intake_type": "food",
                "amount": "250.00",
                "unit": "g",
                "notes": "Morning dry kibble portion",
            },
            format="json",
        )
        self.assertEqual(food_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(food_res.data["is_manual_entry"], True)
        self.assertEqual(food_res.data["amount"], "250.00")
        self.assertEqual(food_res.data["unit"], "g")

        # Log water
        water_res = self.client.post(
            self.list_url,
            {
                "pet": str(self.pet1.id),
                "intake_type": "water",
                "amount": "450.00",
                "unit": "ml",
                "notes": "Clean bowl refilled",
            },
            format="json",
        )
        self.assertEqual(water_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(water_res.data["is_manual_entry"], True)
        self.assertEqual(water_res.data["amount"], "450.00")
        self.assertEqual(water_res.data["unit"], "ml")

    def test_validation_rejects_negative_or_zero_or_excessive_amount(self):
        self.client.force_authenticate(user=self.user1)

        # Zero amount
        res_zero = self.client.post(
            self.list_url,
            {
                "pet": str(self.pet1.id),
                "intake_type": "food",
                "amount": "0.00",
                "unit": "g",
            },
            format="json",
        )
        self.assertEqual(res_zero.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("amount", res_zero.data)

        # Excessive amount > 10000
        res_huge = self.client.post(
            self.list_url,
            {
                "pet": str(self.pet1.id),
                "intake_type": "water",
                "amount": "12000.00",
                "unit": "ml",
            },
            format="json",
        )
        self.assertEqual(res_huge.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("amount", res_huge.data)

    def test_validation_rejects_incompatible_unit(self):
        self.client.force_authenticate(user=self.user1)

        # Incompatible unit: e.g. liquid unit for food or grams for water
        res = self.client.post(
            self.list_url,
            {
                "pet": str(self.pet1.id),
                "intake_type": "water",
                "amount": "500.00",
                "unit": "g",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unit", res.data)

    def test_owner_cannot_log_or_view_another_owners_pet_records(self):
        # Alice tries to log consumption for Bob's pet
        self.client.force_authenticate(user=self.user1)
        res_cross = self.client.post(
            self.list_url,
            {
                "pet": str(self.pet2.id),
                "intake_type": "food",
                "amount": "100.00",
                "unit": "g",
            },
            format="json",
        )
        self.assertEqual(res_cross.status_code, status.HTTP_403_FORBIDDEN)

        # Bob logs for his own pet
        self.client.force_authenticate(user=self.user2)
        res_bob = self.client.post(
            self.list_url,
            {
                "pet": str(self.pet2.id),
                "intake_type": "food",
                "amount": "80.00",
                "unit": "g",
            },
            format="json",
        )
        self.assertEqual(res_bob.status_code, status.HTTP_201_CREATED)
        bob_record_id = res_bob.data["id"]

        # Alice cannot see Bob's record in listing
        self.client.force_authenticate(user=self.user1)
        res_alice_list = self.client.get(self.list_url)
        self.assertEqual(res_alice_list.status_code, status.HTTP_200_OK)
        alice_ids = [r["id"] for r in res_alice_list.data]
        self.assertNotIn(bob_record_id, alice_ids)

        # Alice cannot retrieve Bob's record directly
        detail_url = reverse("pet-food-water-detail", kwargs={"pk": bob_record_id})
        res_alice_get = self.client.get(detail_url)
        self.assertEqual(res_alice_get.status_code, status.HTTP_404_NOT_FOUND)

    def test_daily_totals_aggregation_and_missing_data_handling(self):
        self.client.force_authenticate(user=self.user1)

        # Prior to any logging, daily-totals returns has_data=False and empty totals (NOT treating missing as zero)
        res_empty = self.client.get(self.daily_totals_url, {"pet_id": str(self.pet1.id)})
        self.assertEqual(res_empty.status_code, status.HTTP_200_OK)
        self.assertFalse(res_empty.data["has_data"])
        self.assertEqual(res_empty.data["totals"], [])

        # Add two food meals (200g, 150g) and one water intake (350ml)
        self.client.post(
            self.list_url,
            {"pet": str(self.pet1.id), "intake_type": "food", "amount": "200.00", "unit": "g"},
            format="json",
        )
        self.client.post(
            self.list_url,
            {"pet": str(self.pet1.id), "intake_type": "food", "amount": "150.00", "unit": "g"},
            format="json",
        )
        self.client.post(
            self.list_url,
            {"pet": str(self.pet1.id), "intake_type": "water", "amount": "350.00", "unit": "ml"},
            format="json",
        )

        res_totals = self.client.get(self.daily_totals_url, {"pet_id": str(self.pet1.id)})
        self.assertEqual(res_totals.status_code, status.HTTP_200_OK)
        self.assertTrue(res_totals.data["has_data"])
        totals_map = {f"{t['intake_type']}_{t['unit']}": t for t in res_totals.data["totals"]}

        self.assertIn("food_g", totals_map)
        self.assertEqual(totals_map["food_g"]["total_amount"], 350.0)
        self.assertEqual(totals_map["food_g"]["entry_count"], 2)

        self.assertIn("water_ml", totals_map)
        self.assertEqual(totals_map["water_ml"]["total_amount"], 350.0)
        self.assertEqual(totals_map["water_ml"]["entry_count"], 1)

