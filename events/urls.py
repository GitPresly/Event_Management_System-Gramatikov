"""Адреси на модул „Събития“."""
from django.urls import path

from events import views

app_name = "events"

urlpatterns = [
    # Публична част
    path("", views.event_list, name="event_list"),
    path("event/<slug:slug>/", views.event_detail, name="event_detail"),
    # Служебна част (организатор / администратор)
    path("manage/events/", views.event_manage_list, name="event_manage_list"),
    path("manage/events/create/", views.event_create, name="event_create"),
    path("manage/events/<slug:slug>/", views.event_manage, name="event_manage"),
    path("manage/events/<slug:slug>/edit/", views.event_edit, name="event_edit"),
    path(
        "manage/events/<slug:slug>/status/",
        views.event_change_status,
        name="event_change_status",
    ),
    path("manage/venues/", views.venue_list, name="venue_list"),
    path("manage/venues/create/", views.venue_create, name="venue_create"),
    path("manage/venues/<int:pk>/edit/", views.venue_edit, name="venue_edit"),
]
