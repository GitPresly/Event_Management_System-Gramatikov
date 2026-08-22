"""Адреси на модул „Регистрация“."""
from django.urls import path

from registration import views

app_name = "registration"

# Конкретните адреси се описват преди тези с параметър <str:code>, за да не
# бъдат прихванати от него.
urlpatterns = [
    path("event/<slug:slug>/register/", views.register_for_event, name="register"),
    path("my/registrations/", views.my_registrations, name="my_registrations"),
    path("my/tickets/", views.my_tickets, name="my_tickets"),
    path("ticket/<uuid:uuid>/", views.ticket_detail, name="ticket_detail"),
    path("ticket/<uuid:uuid>/qr.png", views.ticket_qr, name="ticket_qr"),
    path("<str:code>/payment/", views.payment, name="payment"),
    path("<str:code>/cancel/", views.cancel, name="cancel"),
    path("<str:code>/", views.registration_detail, name="registration_detail"),
]
