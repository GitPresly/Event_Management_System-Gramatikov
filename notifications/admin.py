"""Административен изглед за дневника на писмата."""
from django.contrib import admin

from notifications.models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "kind", "recipient", "subject", "status")
    list_filter = ("kind", "status", "sent_at")
    search_fields = ("recipient", "subject", "registration__code")
    date_hierarchy = "sent_at"
    readonly_fields = (
        "kind",
        "recipient",
        "subject",
        "registration",
        "event",
        "status",
        "error",
        "sent_at",
    )

    def has_add_permission(self, request):
        # Дневникът се попълва само от системата.
        return False
