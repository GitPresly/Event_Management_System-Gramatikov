"""
Тест за едновременно сканиране на един и същ билет.

Сценарият е реален: на входа работят няколко устройства и един и същ билет
(например снимка, изпратена на приятел) се показва на две от тях в един и същи
момент. Системата трябва да допусне точно един вход.
"""
from concurrent.futures import ThreadPoolExecutor

from django.db import connections
from django.test import TransactionTestCase

from accounts.models import Role
from checkin.models import CheckIn, ScanResult
from checkin.services import process_scan
from registration.models import PaymentMethod, TicketStatus
from registration.qr import build_payload
from registration.services import TicketRequest, reserve_tickets, simulate_payment
from registration.tests.factories import (
    make_event,
    make_ticket_type,
    make_user,
    make_venue,
)


class ConcurrentCheckInTests(TransactionTestCase):
    """Паралелни сканирания на един билет."""

    reset_sequences = True

    def _scan_in_thread(self, payload, event, operator):
        try:
            outcome = process_scan(payload, event, operator)
            return outcome.result
        finally:
            connections.close_all()

    def test_simultaneous_scans_allow_exactly_one_entry(self):
        organizer = make_user("org_cc", Role.ORGANIZER)
        participant = make_user("part_cc")
        venue = make_venue(capacity=500)
        event = make_event(organizer, venue=venue, capacity=50, title="Едновременен вход")
        ticket_type = make_ticket_type(event)

        registration = reserve_tickets(
            participant, event, [TicketRequest(ticket_type.id, 1)]
        )
        simulate_payment(registration, PaymentMethod.CARD)
        ticket = registration.tickets.first()
        payload = build_payload(ticket)

        # Осем устройства сканират един и същ билет едновременно.
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(self._scan_in_thread, payload, event, organizer)
                for _ in range(8)
            ]
            results = [future.result() for future in futures]

        successes = results.count(ScanResult.OK)

        self.assertEqual(successes, 1, f"Допуснати са {successes} влизания вместо едно.")
        self.assertEqual(CheckIn.objects.filter(ticket=ticket).count(), 1)

        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.USED)

        # Всички останали опити са отчетени като дублиране.
        self.assertEqual(results.count(ScanResult.DUPLICATE), 7)

    def test_parallel_scans_of_different_tickets_all_succeed(self):
        """Различни билети се обработват едновременно без взаимно блокиране."""
        organizer = make_user("org_cc2", Role.ORGANIZER)
        venue = make_venue(name="Зала за паралелни", capacity=500)
        event = make_event(organizer, venue=venue, capacity=50, title="Паралелен вход")
        ticket_type = make_ticket_type(event, quota=50)

        payloads = []
        for index in range(15):
            user = make_user(f"parallel{index:02d}")
            registration = reserve_tickets(
                user, event, [TicketRequest(ticket_type.id, 1)]
            )
            simulate_payment(registration, PaymentMethod.CARD)
            payloads.append(build_payload(registration.tickets.first()))

        with ThreadPoolExecutor(max_workers=15) as pool:
            futures = [
                pool.submit(self._scan_in_thread, payload, event, organizer)
                for payload in payloads
            ]
            results = [future.result() for future in futures]

        self.assertEqual(results.count(ScanResult.OK), 15)
        self.assertEqual(CheckIn.objects.filter(event=event).count(), 15)
