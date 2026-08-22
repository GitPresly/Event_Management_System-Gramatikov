"""Регистрация на потребителския модел във вградения административен панел."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Административен изглед за потребителите с добавено поле „роля“."""

    list_display = ("username", "email", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("username",)

    fieldsets = BaseUserAdmin.fieldsets + (
        ("Данни за системата", {"fields": ("role", "phone", "organization")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Данни за системата", {"fields": ("email", "role", "phone", "organization")}),
    )
