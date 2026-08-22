"""
Тестове на сигурността на QR кодовете.

Проверява нефункционалното изискване „сигурност на билетите (защита от
дублиране)“ в частта му, отнасяща се до фалшифициране.
"""
import uuid

from django.test import TestCase

from accounts.models import Role
from registration.models import PaymentMethod
from registration.qr import (
    InvalidTicketError,
    build_payload,
    render_qr_png,
    verify_payload,
)
from registration.services import TicketRequest, reserve_tickets, simulate_payment
from registration.tests.factories import make_event, make_ticket_type, make_user


class QRSignatureTests(TestCase):
    """Подписване и проверка на съдържанието на QR кода."""

    def setUp(self):
        organizer = make_user("org_qr", Role.ORGANIZER)
        participant = make_user("part_qr")
        event = make_event(organizer, capacity=20)
        ticket_type = make_ticket_type(event)
        registration = reserve_tickets(
            participant, event, [TicketRequest(ticket_type.id, 1)]
        )
        simulate_payment(registration, PaymentMethod.CARD)
        self.ticket = registration.tickets.first()

    def test_valid_payload_returns_ticket_uuid(self):
        payload = build_payload(self.ticket)
        self.assertEqual(verify_payload(payload), str(self.ticket.uuid))

    def test_payload_starts_with_system_prefix(self):
        """Префиксът позволява чужди QR кодове да се отхвърлят веднага."""
        self.assertTrue(build_payload(self.ticket).startswith("EMS1:"))

    def test_tampered_uuid_is_rejected(self):
        """
        Подмяна на идентификатора в кода прави подписа невалиден.

        Това е същината на защитата: без тайния ключ не може да се съчини
        валиден билет за друг идентификатор.
        """
        payload = build_payload(self.ticket)
        forged = payload.replace(str(self.ticket.uuid), str(uuid.uuid4()))

        with self.assertRaises(InvalidTicketError):
            verify_payload(forged)

    def test_tampered_signature_is_rejected(self):
        payload = build_payload(self.ticket)
        forged = payload[:-3] + "abc"

        with self.assertRaises(InvalidTicketError):
            verify_payload(forged)

    def test_unsigned_uuid_is_rejected(self):
        """Гол идентификатор без подпис не е валиден билет."""
        with self.assertRaises(InvalidTicketError):
            verify_payload(str(self.ticket.uuid))

    def test_foreign_qr_code_is_rejected(self):
        for value in ["", "   ", "https://example.com", "EMS2:нещо:друго"]:
            with self.subTest(value=value):
                with self.assertRaises(InvalidTicketError):
                    verify_payload(value)

    def test_each_ticket_gets_a_unique_payload(self):
        """Изискването „уникален QR код за всеки билет“."""
        organizer = make_user("org_qr2", Role.ORGANIZER)
        participant = make_user("part_qr2")
        event = make_event(organizer, capacity=20, title="Уникалност")
        ticket_type = make_ticket_type(event)
        registration = reserve_tickets(
            participant, event, [TicketRequest(ticket_type.id, 5)]
        )
        simulate_payment(registration, PaymentMethod.CARD)

        payloads = {build_payload(t) for t in registration.tickets.all()}
        self.assertEqual(len(payloads), 5)

    def test_qr_image_is_a_valid_png(self):
        png = render_qr_png(build_payload(self.ticket))
        # Сигнатурата в началото на всеки PNG файл.
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 100)

    def test_qr_image_file_is_saved_on_payment(self):
        self.assertTrue(self.ticket.qr_image)
        self.assertIn("tickets/qr/", self.ticket.qr_image.name)
