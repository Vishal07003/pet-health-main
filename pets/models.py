from decimal import Decimal
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator


class Pet(models.Model):
    class Species(models.TextChoices):
        DOG = "dog", "Dog"
        CAT = "cat", "Cat"
        OTHER = "other", "Other"

    class Sex(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pets",
    )
    name = models.CharField(max_length=100)
    species = models.CharField(max_length=20, choices=Species.choices, default=Species.DOG)
    breed = models.CharField(max_length=100, blank=True, default="")
    sex = models.CharField(max_length=10, choices=Sex.choices, default=Sex.UNKNOWN)
    date_of_birth = models.DateField(null=True, blank=True)
    weight_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.05")), MaxValueValidator(Decimal("200.00"))],
        help_text="Weight in kilograms (0.05 to 200.00 kg)",
    )
    is_neutered = models.BooleanField(default=False)
    microchip_number = models.CharField(max_length=50, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["species"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.species}) - {self.owner.username}"


class WeightRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pet = models.ForeignKey(Pet, on_delete=models.CASCADE, related_name="weight_records")
    weight_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.05")), MaxValueValidator(Decimal("200.00"))],
    )
    recorded_at = models.DateField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"{self.pet.name} - {self.weight_kg}kg on {self.recorded_at}"


class MedicalRecord(models.Model):
    class RecordType(models.TextChoices):
        VACCINATION = "vaccination", "Vaccination"
        DEWORMING = "deworming", "Deworming"
        MEDICATION = "medication", "Medication"
        LAB_TEST = "lab_test", "Lab Test"
        CHECKUP = "checkup", "General Checkup"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pet = models.ForeignKey(Pet, on_delete=models.CASCADE, related_name="medical_records")
    record_type = models.CharField(max_length=30, choices=RecordType.choices, default=RecordType.VACCINATION)
    title = models.CharField(max_length=150)
    administered_at = models.DateField()
    next_due_date = models.DateField(null=True, blank=True)
    batch_number = models.CharField(max_length=100, blank=True, default="")
    veterinarian = models.CharField(max_length=150, blank=True, default="")
    clinic_name = models.CharField(max_length=150, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-administered_at"]

    def __str__(self):
        return f"{self.pet.name} - {self.title} ({self.record_type})"


class VetAppointment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pet = models.ForeignKey(Pet, on_delete=models.CASCADE, related_name="vet_appointments")
    title = models.CharField(max_length=150)
    appointment_date = models.DateTimeField()
    veterinarian = models.CharField(max_length=150, blank=True, default="")
    clinic_name = models.CharField(max_length=150, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["appointment_date"]

    def __str__(self):
        return f"{self.pet.name} - {self.title} on {self.appointment_date}"
