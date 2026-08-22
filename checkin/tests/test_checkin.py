"""
Тестове на процеса на check-in.

Проверява критерия за оценка „коректност на check-in процеса“ и втората
половина от защитата от дублиране на билети.
"""
from django.test import TestCase

from accounts.models import Role
from checkin.models import CheckIn, ScanLog, ScanResult
from checkin.services import event_live_stats, process_scan
from events.models import EventStatus
from registration.models import PaymentMethod, TicketStatus
from registration.qr import build_payload
from registration.services import TicketRequest, reserve_tickets, simulate_payment
from registration.tests.factories import (
    make_event,
    make_ticket_type,
    make_user,
    make_venue,
)


class CheckInTests(TestCase):
    """Сценарии при проверка на билет на входа."""

    def setUp(self):
        self.organizer = make_user("org_ci", Role.ORGANIZER)
        self.participant = make_user("part_ci")
        self.venue = make_venue(capacity=500)
        self.event = make_event(self.organizer, venue=self.venue, capacity=50)
        self.ticket_type = make_ticket_type(self.event)

        self.registration = reserve_tickets(
            self.participant, self.event, [TicketRequest(self.ticket_type.id, 1)]
        )
        simulate_payment(self.registration, PaymentMethod.CARD)
        self.ticket = self.registration.tickets.first()

    def _scan(self, payload=None, event=None):
        return process_scan(
            payload if payload is not None else build_payload(self.ticket),
            event or self.event,
            self.organizer,
            ip="127.0.0.1",
        )

    # -- Успешен вход --------------------------------------------------------

    def test_valid_ticket_is_accepted(self):
        outcome = self._scan()

        self.assertTrue(outcome.is_success)
        self.assertEqual(outcome.result, ScanResult.OK)
        self.assertIn(self.ticket.holder_name, outcome.message)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.USED)
        self.assertTrue(CheckIn.objects.filter(ticket=self.ticket).exists())

    def test_successful_scan_is_logged(self):
        self._scan()
        log = ScanLog.objects.filter(event=self.event).latest("created_at")
        self.assertEqual(log.result, ScanResult.OK)
        self.assertEqual(log.ticket, self.ticket)
        self.assertEqual(log.ip_address, "127.0.0.1")

    # -- Защита от дублиране -------------------------------------------------

    def test_duplicate_scan_is_rejected(self):
        """Един билет може да бъде използван само веднъж."""
        first = self._scan()
        self.assertTrue(first.is_success)

        second = self._scan()
        self.assertFalse(second.is_success)
        self.assertEqual(second.result, ScanResult.DUPLICATE)

        # Записът за вход остава един-единствен.
        self.assertEqual(CheckIn.objects.filter(ticket=self.ticket).count(), 1)

    def test_duplicate_attempt_is_logged(self):
        self._scan()
        self._scan()
        self.assertEqual(
            ScanLog.objects.filter(event=self.event, result=ScanResult.DUPLICATE).count(), 1
        )

    def test_database_prevents_second_checkin_record(self):
        """
        Уникалната връзка CheckIn ↔ Ticket е последната преграда.

        Дори логиката да бъде заобиколена, базата не позволява втори запис.
        """
        from django.db import IntegrityError, transaction

        self._scan()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CheckIn.objects.create(
                    ticket=self.ticket, event=self.event, operator=self.organizer
                )

    # -- Отхвърляни билети ---------------------------------------------------

    def test_forged_ticket_is_rejected(self):
        payload = build_payload(self.ticket)
        forged = payload[:-4] + "XXXX"

        outcome = self._scan(forged)
        self.assertFalse(outcome.is_success)
        self.assertEqual(outcome.result, ScanResult.INVALID_SIGNATURE)
        self.assertFalse(CheckIn.objects.filter(ticket=self.ticket).exists())

    def test_ticket_for_another_event_is_rejected(self):
        other_event = make_event(
            self.organizer, venue=self.venue, capacity=20, title="Друго събитие"
        )
        outcome = self._scan(event=other_event)

        self.assertFalse(outcome.is_success)
        self.assertEqual(outcome.result, ScanResult.WRONG_EVENT)

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.VALID)

    def test_unpaid_ticket_is_rejected(self):
        other = make_user("part_unpaid")
        unpaid = reserve_tickets(
            other, self.event, [TicketRequest(self.ticket_type.id, 1)]
        )
        ticket = unpaid.tickets.first()

        outcome = self._scan(build_payload(ticket))
        self.assertFalse(outcome.is_success)
        self.assertEqual(outcome.result, ScanResult.NOT_PAID)

    def test_cancelled_ticket_is_rejected(self):
        self.ticket.status = TicketStatus.CANCELLED
        self.ticket.save()

        outcome = self._scan()
        self.assertFalse(outcome.is_success)
        self.assertEqual(outcome.result, ScanResult.CANCELLED)

    def test_unknown_ticket_is_rejected(self):
        """Правилно подписан код за несъществуващ билет."""
        import uuid as uuid_module

        from django.core import signing

        from registration.qr import PAYLOAD_PREFIX, SIGNING_SALT

        signed = signing.Signer(salt=SIGNING_SALT).sign(str(uuid_module.uuid4()))
        outcome = self._scan(f"{PAYLOAD_PREFIX}:{signed}")

        self.assertFalse(outcome.is_success)
        self.assertEqual(outcome.result, ScanResult.NOT_FOUND)

    def test_scan_for_draft_event_is_rejected(self):
        draft = make_event(
            self.organizer, venue=self.venue, status=EventStatus.DRAFT, title="Чернова CI"
        )
        outcome = self._scan(event=draft)
        self.assertEqual(outcome.result, ScanResult.EVENT_NOT_ACTIVE)

    # -- Ръчно въвеждане -----------------------------------------------------

    def test_manual_short_code_is_accepted(self):
        """Резервният вариант при повредена камера или скъсан QR код."""
        outcome = self._scan(self.ticket.short_code)

        self.assertTrue(outcome.is_success)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.USED)

    def test_manual_short_code_is_case_insensitive(self):
        outcome = self._scan(self.ticket.short_code.lower())
        self.assertTrue(outcome.is_success)

    def test_invalid_manual_code_is_rejected(self):
        for value in ["ZZZZZZZZ", "123", "не е код"]:
            with self.subTest(value=value):
                outcome = self._scan(value)
                self.assertFalse(outcome.is_success)

    def test_short_code_from_another_event_is_not_found(self):
        """Ръчният код се търси само в рамките на текущото събитие."""
        other_event = make_event(
            self.organizer, venue=self.venue, capacity=20, title="Чуждо за код"
        )
        outcome = self._scan(self.ticket.short_code, event=other_event)
        self.assertFalse(outcome.is_success)


class LiveStatsTests(TestCase):
    """Показателите за реалния брой присъстващи."""

    def setUp(self):
        self.organizer = make_user("org_stats", Role.ORGANIZER)
        self.event = make_event(self.organizer, capacity=100)
        self.ticket_type = make_ticket_type(self.event, quota=100)

        # Пет платени билета за пет различни участника.
        self.tickets = []
        for index in range(5):
            user = make_user(f"stat{index}")
            registration = reserve_tickets(
                user, self.event, [TicketRequest(self.ticket_type.id, 1)]
            )
            simulate_payment(registration, PaymentMethod.CARD)
            self.tickets.append(registration.tickets.first())

    def test_counter_starts_at_zero(self):
        stats = event_live_stats(self.event)
        self.assertEqual(stats["checked_in"], 0)
        self.assertEqual(stats["total_tickets"], 5)
        self.assertEqual(stats["remaining"], 5)
        self.assertEqual(stats["percent"], 0.0)

    def test_counter_increases_with_each_checkin(self):
        for index, ticket in enumerate(self.tickets[:3], start=1):
            process_scan(build_payload(ticket), self.event, self.organizer)
            stats = event_live_stats(self.event)
            self.assertEqual(stats["checked_in"], index)

        stats = event_live_stats(self.event)
        self.assertEqual(stats["checked_in"], 3)
        self.assertEqual(stats["remaining"], 2)
        self.assertEqual(stats["percent"], 60.0)

    def test_recent_list_shows_latest_entries(self):
        process_scan(build_payload(self.tickets[0]), self.event, self.organizer)
        stats = event_live_stats(self.event)

        self.assertEqual(len(stats["recent"]), 1)
        self.assertEqual(stats["recent"][0]["code"], self.tickets[0].short_code)

    def test_duplicate_scan_does_not_increase_counter(self):
        process_scan(build_payload(self.tickets[0]), self.event, self.organizer)
        process_scan(build_payload(self.tickets[0]), self.event, self.organizer)

        self.assertEqual(event_live_stats(self.event)["checked_in"], 1)
