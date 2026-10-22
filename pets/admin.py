from django.contrib import admin
from .models import Pet


@admin.register(Pet)
class PetAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "species", "breed", "owner", "weight_kg", "created_at")
    list_filter = ("species", "sex", "is_neutered", "created_at")
    search_fields = ("name", "breed", "owner__username", "owner__email", "microchip_number")
    readonly_fields = ("id", "created_at", "updated_at")
