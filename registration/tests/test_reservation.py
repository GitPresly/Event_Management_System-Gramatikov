"""
Тестове на процеса на регистрация и резервация.

Проверява критерия за оценка „коректност на регистрацията“.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from events.models import EventStatus
from registration.models import (
    PaymentMethod,
    RegistrationStatus,
    Ticket,
    TicketStatus,
)
from registration.services import (
    RegistrationError,
    TicketRequest,
    cancel_registration,
    reserve_tickets,
    simulate_payment,
)
from registration.tests.factories import (
    make_event,
    make_ticket_type,
    make_user,
    make_venue,
)


class ReserveTicketsTests(TestCase):
    """Резервиране на билети — успешни и неуспешни случаи."""

    def setUp(self):
        self.organizer = make_user("org", Role.ORGANIZER)
        self.participant = make_user("part1")
        self.venue = make_venue(capacity=1000)
        self.event = make_event(self.organizer, venue=self.venue, capacity=10)
        self.standard = make_ticket_type(self.event, "Стандартен", "50.00", quota=8)
        self.vip = make_ticket_type(self.event, "VIP", "120.00", quota=4)

    def test_successful_reservation_creates_tickets(self):
        registration = reserve_tickets(
            self.participant,
            self.event,
            [TicketRequest(self.standard.id, 2), TicketRequest(self.vip.id, 1)],
        )

        self.assertEqual(registration.status, RegistrationStatus.PENDING)
        self.assertEqual(registration.tickets.count(), 3)
        # 2 × 50.00 + 1 × 120.00 = 220.00
        self.assertEqual(registration.total_amount, Decimal("220.00"))
        self.assertTrue(
            all(t.status == TicketStatus.RESERVED for t in registration.tickets.all())
        )

    def test_price_is_frozen_at_purchase_time(self):
        """По-късна промяна на цената не променя вече издадените билети."""
        registration = reserve_tickets(
            self.participant, self.event, [TicketRequest(self.standard.id, 1)]
        )

        self.standard.price = Decimal("999.00")
        self.standard.save()

        ticket = registration.tickets.first()
        self.assertEqual(ticket.price_paid, Decimal("50.00"))

    def test_cannot_exceed_event_capacity(self):
        """Общият капацитет на събитието е твърдо ограничение."""
        with self.settings(MAX_TICKETS_PER_REGISTRATION=20):
            with self.assertRaises(RegistrationError) as ctx:
                # Капацитетът на събитието е 10 места.
                reserve_tickets(
                    self.participant, self.event, [TicketRequest(self.standard.id, 11)]
                )
        self.assertIn("свободни места", str(ctx.exception))
        # Заявката се отменя изцяло — не се създават частични билети.
        self.assertEqual(Ticket.objects.filter(event=self.event).count(), 0)

    def test_cannot_exceed_ticket_type_quota(self):
        """Квотата на билетния тип също е твърдо ограничение."""
        with self.assertRaises(RegistrationError):
            # Квотата на VIP е 4, а капацитетът на събитието — 10.
            reserve_tickets(self.participant, self.event, [TicketRequest(self.vip.id, 5)])
        self.assertEqual(Ticket.objects.filter(ticket_type=self.vip).count(), 0)

    def test_empty_request_is_rejected(self):
        with self.assertRaises(RegistrationError):
            reserve_tickets(self.participant, self.event, [])

        with self.assertRaises(RegistrationError):
            reserve_tickets(self.participant, self.event, [TicketRequest(self.standard.id, 0)])

    def test_cannot_register_for_draft_event(self):
        draft = make_event(
            self.organizer, venue=self.venue, status=EventStatus.DRAFT, title="Чернова"
        )
        ticket_type = make_ticket_type(draft)

        with self.assertRaises(RegistrationError):
            reserve_tickets(self.participant, draft, [TicketRequest(ticket_type.id, 1)])

    def test_cannot_register_after_deadline(self):
        self.event.registration_deadline = timezone.now() - timezone.timedelta(hours=1)
        self.event.save()

        with self.assertRaises(RegistrationError) as ctx:
            reserve_tickets(self.participant, self.event, [TicketRequest(self.standard.id, 1)])
        self.assertIn("срок", str(ctx.exception).lower())

    def test_cannot_use_ticket_type_from_another_event(self):
        """Билетен тип на чуждо събитие не може да бъде използван."""
        other_event = make_event(self.organizer, venue=self.venue, title="Друго събитие")
        other_type = make_ticket_type(other_event, "Чужд")

        with self.assertRaises(RegistrationError):
            reserve_tickets(self.participant, self.event, [TicketRequest(other_type.id, 1)])

    def test_max_tickets_per_registration_is_enforced(self):
        big_event = make_event(self.organizer, venue=self.venue, capacity=500, title="Голямо")
        big_type = make_ticket_type(big_event, quota=500)

        with self.settings(MAX_TICKETS_PER_REGISTRATION=5):
            with self.assertRaises(RegistrationError):
                reserve_tickets(self.participant, big_event, [TicketRequest(big_type.id, 6)])


class PaymentTests(TestCase):
    """Симулация на плащане и издаване на билети."""

    def setUp(self):
        self.organizer = make_user("org2", Role.ORGANIZER)
        self.participant = make_user("part2")
        self.event = make_event(self.organizer, capacity=50)
        self.ticket_type = make_ticket_type(self.event, price="30.00", quota=50)
        self.registration = reserve_tickets(
            self.participant, self.event, [TicketRequest(self.ticket_type.id, 2)]
        )

    def test_payment_marks_registration_paid_and_issues_tickets(self):
        payment = simulate_payment(self.registration, PaymentMethod.CARD)

        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, RegistrationStatus.PAID)
        self.assertIsNotNone(self.registration.paid_at)
        self.assertEqual(payment.amount, Decimal("60.00"))
        self.assertTrue(payment.transaction_ref.startswith("TXN-"))

        for ticket in self.registration.tickets.all():
            self.assertEqual(ticket.status, TicketStatus.VALID)
            # Всеки платен билет получава и своя QR код.
            self.assertTrue(ticket.qr_image)

    def test_cannot_pay_twice(self):
        simulate_payment(self.registration, PaymentMethod.CARD)
        with self.assertRaises(RegistrationError):
            simulate_payment(self.registration, PaymentMethod.CARD)

    def test_invalid_payment_method_is_rejected(self):
        with self.assertRaises(RegistrationError):
            simulate_payment(self.registration, "BITCOIN")

    def test_cannot_pay_cancelled_registration(self):
        cancel_registration(self.registration)
        with self.assertRaises(RegistrationError):
            simulate_payment(self.registration, PaymentMethod.CARD)


class CancellationTests(TestCase):
    """Отказ на заявка и освобождаване на местата."""

    def setUp(self):
        self.organizer = make_user("org3", Role.ORGANIZER)
        self.participant = make_user("part3")
        self.event = make_event(self.organizer, capacity=3)
        self.ticket_type = make_ticket_type(self.event, quota=3)

    def test_cancellation_frees_seats(self):
        registration = reserve_tickets(
            self.participant, self.event, [TicketRequest(self.ticket_type.id, 3)]
        )
        self.assertEqual(self.event.seats_available, 0)

        cancel_registration(registration)

        self.assertEqual(self.event.seats_available, 3)
        self.assertTrue(
            all(t.status == TicketStatus.CANCELLED for t in registration.tickets.all())
        )

        # Освободеното място може да бъде заето отново.
        other = make_user("part3b")
        new_registration = reserve_tickets(
            other, self.event, [TicketRequest(self.ticket_type.id, 3)]
        )
        self.assertEqual(new_registration.tickets.count(), 3)

    def test_cannot_cancel_twice(self):
        registration = reserve_tickets(
            self.participant, self.event, [TicketRequest(self.ticket_type.id, 1)]
        )
        cancel_registration(registration)
        with self.assertRaises(RegistrationError):
            cancel_registration(registration)

    def test_cannot_cancel_after_checkin(self):
        """Заявка с вече използван билет не се отказва — човекът е присъствал."""
        registration = reserve_tickets(
            self.participant, self.event, [TicketRequest(self.ticket_type.id, 1)]
        )
        simulate_payment(registration, PaymentMethod.CARD)

        ticket = registration.tickets.first()
        ticket.status = TicketStatus.USED
        ticket.save()

        with self.assertRaises(RegistrationError):
            cancel_registration(registration)
