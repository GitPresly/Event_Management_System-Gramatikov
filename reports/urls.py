"""Адреси на модул „Отчети“."""
from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("export/", views.overview_export, name="overview_export"),
    path("event/<slug:slug>/", views.event_detail, name="event_report"),
    path("event/<slug:slug>/export/", views.event_export, name="event_export"),
]
