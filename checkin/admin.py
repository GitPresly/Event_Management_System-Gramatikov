"""Административни изгледи за модул „На място“."""
from django.contrib import admin

from checkin.models import CheckIn, ScanLog


@admin.register(CheckIn)
class CheckInAdmin(admin.ModelAdmin):
    list_display = ("ticket", "event", "operator", "checked_in_at")
    list_filter = ("event", "checked_in_at")
    search_fields = ("ticket__uuid", "ticket__holder_name")
    date_hierarchy = "checked_in_at"
    readonly_fields = ("checked_in_at",)


@admin.register(ScanLog)
class ScanLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event", "result", "ticket", "operator", "ip_address")
    list_filter = ("result", "event", "created_at")
    search_fields = ("payload_preview", "ticket__uuid")
    date_hierarchy = "created_at"
    readonly_fields = (
        "event",
        "ticket",
        "operator",
        "result",
        "payload_preview",
        "ip_address",
        "created_at",
    )

    def has_add_permission(self, request):
        # Дневникът се попълва само от системата, не се редактира ръчно.
        return False
