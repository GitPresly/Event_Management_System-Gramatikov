"""Конфигурация на приложението."""
from django.apps import AppConfig


class CheckinConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "checkin"
    verbose_name = "Check-in на място"
