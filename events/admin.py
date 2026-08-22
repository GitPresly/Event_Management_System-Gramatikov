"""Административни изгледи за модул „Събития“."""
from django.contrib import admin

from events.models import Event, ProgramItem, TicketType, Venue


class TicketTypeInline(admin.TabularInline):
    """Билетните типове се редактират директно от страницата на събитието."""

    model = TicketType
    extra = 1


class ProgramItemInline(admin.TabularInline):
    """Програмата се редактира директно от страницата на събитието."""

    model = ProgramItem
    extra = 1


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "capacity")
    list_filter = ("city",)
    search_fields = ("name", "city", "address")


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "organizer",
        "venue",
        "starts_at",
        "capacity",
        "tickets_sold",
        "status",
    )
    list_filter = ("status", "venue__city", "starts_at")
    search_fields = ("title", "description")
    date_hierarchy = "starts_at"
    prepopulated_fields = {"slug": ("title",)}
    inlines = [TicketTypeInline, ProgramItemInline]
    autocomplete_fields = ("venue",)

    @admin.display(description="Продадени билети")
    def tickets_sold(self, obj):
        return obj.tickets_sold


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "event", "price", "quota", "sold_count", "is_active")
    list_filter = ("is_active", "event")
    search_fields = ("name", "event__title")

    @admin.display(description="Продадени")
    def sold_count(self, obj):
        return obj.sold_count
