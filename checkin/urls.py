"""Адреси на модул „На място“."""
from django.urls import path

from checkin import views

app_name = "checkin"

urlpatterns = [
    path("", views.checkin_event_list, name="event_list"),
    path("<slug:slug>/", views.scan_console, name="scan_console"),
    path("<slug:slug>/scan/", views.scan, name="scan"),
    path("<slug:slug>/stats/", views.live_stats, name="live_stats"),
    path("<slug:slug>/attendees/", views.attendee_list, name="attendee_list"),
]
