"""Административни изгледи за модул „Регистрация“."""
from django.contrib import admin

from registration.models import Payment, Registration, Ticket


class TicketInline(admin.TabularInline):
    """Билетите се виждат директно от страницата на заявката."""

    model = Ticket
    extra = 0
    readonly_fields = ("uuid", "issued_at", "price_paid")
    fields = ("uuid", "ticket_type", "holder_name", "price_paid", "status", "issued_at")


class PaymentInline(admin.StackedInline):
    model = Payment
    extra = 0
    readonly_fields = ("transaction_ref", "created_at")


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "event",
        "user",
        "ticket_count",
        "total_amount",
        "status",
        "created_at",
    )
    list_filter = ("status", "event", "created_at")
    search_fields = ("code", "contact_name", "contact_email", "user__username")
    date_hierarchy = "created_at"
    readonly_fields = ("code", "created_at", "paid_at", "cancelled_at", "total_amount")
    inlines = [TicketInline, PaymentInline]

    @admin.display(description="Брой билети")
    def ticket_count(self, obj):
        return obj.ticket_count


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "short_code",
        "event",
        "ticket_type",
        "holder_name",
        "price_paid",
        "status",
        "issued_at",
    )
    list_filter = ("status", "event", "ticket_type")
    search_fields = ("uuid", "holder_name", "holder_email", "registration__code")
    readonly_fields = ("uuid", "issued_at", "qr_image")

    @admin.display(description="Код")
    def short_code(self, obj):
        return obj.short_code


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("transaction_ref", "registration", "amount", "method", "status", "created_at")
    list_filter = ("method", "status", "created_at")
    search_fields = ("transaction_ref", "registration__code")
    readonly_fields = ("transaction_ref", "created_at")
