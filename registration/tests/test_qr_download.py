"""Тестове на изтеглянето на QR кода от страницата на билета."""
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from registration.models import PaymentMethod, TicketStatus
from registration.services import TicketRequest, reserve_tickets, simulate_payment
from registration.tests.factories import make_event, make_ticket_type, make_user


class TicketQRDownloadTests(TestCase):
    """Отдаване на QR изображението — за показване и за изтегляне."""

    @classmethod
    def setUpTestData(cls):
        cls.organizer = make_user("org_dl", Role.ORGANIZER)
        cls.buyer = make_user("buyer_dl")
        cls.stranger = make_user("stranger_dl")

        cls.event = make_event(cls.organizer, capacity=20, title="Изтегляне на QR")
        ticket_type = make_ticket_type(cls.event, price="10.00", quota=20)
        registration = reserve_tickets(
            cls.buyer, cls.event, [TicketRequest(ticket_type.id, 1)]
        )
        simulate_payment(registration, PaymentMethod.CARD)
        cls.ticket = registration.tickets.first()

    def _url(self, download=False):
        url = reverse("registration:ticket_qr", kwargs={"uuid": self.ticket.uuid})
        return f"{url}?download=1" if download else url

    def test_inline_response_has_no_attachment_header(self):
        self.client.force_login(self.buyer)
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertNotIn("attachment", response.get("Content-Disposition", ""))

    def test_download_returns_attachment_with_ticket_code_filename(self):
        self.client.force_login(self.buyer)
        response = self.client.get(self._url(download=True))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        disposition = response["Content-Disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn(f"bilet-{self.ticket.short_code}.png", disposition)

    def test_downloaded_file_is_a_valid_png(self):
        self.client.force_login(self.buyer)
        response = self.client.get(self._url(download=True))

        content = b"".join(response.streaming_content) if response.streaming else response.content
        self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_stranger_cannot_download_foreign_qr(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self._url(download=True)).status_code, 404)

    def test_anonymous_is_redirected(self):
        self.assertEqual(self.client.get(self._url(download=True)).status_code, 302)

    def test_cancelled_ticket_qr_is_not_served(self):
        self.ticket.status = TicketStatus.CANCELLED
        self.ticket.save(update_fields=["status"])

        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(self._url(download=True)).status_code, 404)

        self.ticket.status = TicketStatus.VALID
        self.ticket.save(update_fields=["status"])

    def test_ticket_page_shows_download_button(self):
        self.client.force_login(self.buyer)
        response = self.client.get(
            reverse("registration:ticket_detail", kwargs={"uuid": self.ticket.uuid})
        )
        self.assertContains(response, "Изтегли QR кода")
        self.assertContains(response, "download=1")
