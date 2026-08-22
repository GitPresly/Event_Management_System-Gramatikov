"""Тестове на модул „Събития“ — модел, валидации и работен процес."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from events.models import Event, EventStatus, ProgramItem, TicketType
from registration.models import PaymentMethod
from registration.services import TicketRequest, reserve_tickets, simulate_payment
from registration.tests.factories import (
    make_event,
    make_ticket_type,
    make_user,
    make_venue,
)


class EventModelTests(TestCase):
    """Изчислими показатели и валидации на събитието."""

    def setUp(self):
        self.organizer = make_user("org_ev", Role.ORGANIZER)
        self.venue = make_venue(capacity=500)
        self.event = make_event(self.organizer, venue=self.venue, capacity=10)
        self.ticket_type = make_ticket_type(self.event, quota=10)

    def test_slug_is_generated_from_title(self):
        self.assertTrue(self.event.slug)
        self.assertEqual(Event.objects.get(slug=self.event.slug), self.event)

    def test_slug_is_unique_for_duplicate_titles(self):
        second = make_event(
            self.organizer, venue=self.venue, capacity=10, title=self.event.title
        )
        self.assertNotEqual(second.slug, self.event.slug)

    def test_seat_counters(self):
        self.assertEqual(self.event.tickets_sold, 0)
        self.assertEqual(self.event.seats_available, 10)
        self.assertFalse(self.event.is_sold_out)

        user = make_user("ev_buyer")
        reserve_tickets(user, self.event, [TicketRequest(self.ticket_type.id, 4)])

        self.assertEqual(self.event.tickets_sold, 4)
        self.assertEqual(self.event.seats_available, 6)
        self.assertEqual(self.event.occupancy_percent, 40.0)

    def test_sold_out_closes_registration(self):
        user = make_user("ev_buyer2")
        reserve_tickets(user, self.event, [TicketRequest(self.ticket_type.id, 10)])

        self.assertTrue(self.event.is_sold_out)
        self.assertFalse(self.event.is_registration_open)
        self.assertIn("изчерпани", self.event.registration_closed_reason)

    def test_end_must_be_after_start(self):
        event = Event(
            organizer=self.organizer,
            venue=self.venue,
            title="Обърнати дати",
            description="Тест",
            starts_at=timezone.now() + timedelta(days=5),
            ends_at=timezone.now() + timedelta(days=4),
            capacity=10,
        )
        with self.assertRaises(ValidationError):
            event.full_clean(exclude=["slug"])

    def test_capacity_cannot_exceed_venue(self):
        small_venue = make_venue(name="Малка зала", capacity=30)
        event = Event(
            organizer=self.organizer,
            venue=small_venue,
            title="Прекалено голямо",
            description="Тест",
            starts_at=timezone.now() + timedelta(days=5),
            ends_at=timezone.now() + timedelta(days=5, hours=3),
            capacity=100,
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean(exclude=["slug"])
        self.assertIn("capacity", ctx.exception.error_dict)

    def test_deadline_cannot_be_after_start(self):
        self.event.registration_deadline = self.event.starts_at + timedelta(hours=1)
        with self.assertRaises(ValidationError):
            self.event.full_clean(exclude=["slug"])

    def test_draft_event_does_not_accept_registrations(self):
        self.event.status = EventStatus.DRAFT
        self.event.save()
        self.assertFalse(self.event.is_registration_open)

    def test_checked_in_count_reflects_used_tickets(self):
        from checkin.services import process_scan
        from registration.qr import build_payload

        user = make_user("ev_attendee")
        registration = reserve_tickets(
            user, self.event, [TicketRequest(self.ticket_type.id, 2)]
        )
        simulate_payment(registration, PaymentMethod.CARD)

        self.assertEqual(self.event.checked_in_count, 0)
        process_scan(
            build_payload(registration.tickets.first()), self.event, self.organizer
        )
        self.assertEqual(self.event.checked_in_count, 1)


class TicketTypeTests(TestCase):
    """Билетни типове, квоти и период на продажба."""

    def setUp(self):
        self.organizer = make_user("org_tt", Role.ORGANIZER)
        self.event = make_event(self.organizer, capacity=100)

    def test_quota_tracking(self):
        ticket_type = make_ticket_type(self.event, quota=5)
        self.assertEqual(ticket_type.remaining, 5)
        self.assertTrue(ticket_type.is_on_sale)

        user = make_user("tt_buyer")
        reserve_tickets(user, self.event, [TicketRequest(ticket_type.id, 5)])

        self.assertEqual(ticket_type.sold_count, 5)
        self.assertEqual(ticket_type.remaining, 0)
        self.assertFalse(ticket_type.is_on_sale)

    def test_inactive_type_is_not_on_sale(self):
        ticket_type = make_ticket_type(self.event)
        ticket_type.is_active = False
        ticket_type.save()
        self.assertFalse(ticket_type.is_on_sale)

    def test_sales_window_is_respected(self):
        ticket_type = make_ticket_type(self.event)

        ticket_type.sales_start = timezone.now() + timedelta(days=1)
        ticket_type.save()
        self.assertFalse(ticket_type.is_on_sale)

        ticket_type.sales_start = timezone.now() - timedelta(days=2)
        ticket_type.sales_end = timezone.now() - timedelta(days=1)
        ticket_type.save()
        self.assertFalse(ticket_type.is_on_sale)

    def test_duplicate_name_within_event_is_rejected(self):
        from django.db import IntegrityError, transaction

        make_ticket_type(self.event, "Стандартен")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TicketType.objects.create(
                    event=self.event, name="Стандартен", price=Decimal("10.00"), quota=5
                )

    def test_same_name_allowed_on_different_events(self):
        other = make_event(self.organizer, capacity=50, title="Второ за типове")
        make_ticket_type(self.event, "Стандартен")
        make_ticket_type(other, "Стандартен")
        self.assertEqual(TicketType.objects.filter(name="Стандартен").count(), 2)

    def test_free_ticket_type(self):
        free = make_ticket_type(self.event, "Безплатен", "0.00")
        self.assertTrue(free.is_free)


class ProgramItemTests(TestCase):
    """Точки от програмата."""

    def setUp(self):
        self.organizer = make_user("org_pi", Role.ORGANIZER)
        self.event = make_event(self.organizer, capacity=50, duration_hours=8)

    def test_program_item_must_fit_within_event(self):
        item = ProgramItem(
            event=self.event,
            title="Извън рамките",
            starts_at=self.event.starts_at - timedelta(hours=2),
            ends_at=self.event.starts_at - timedelta(hours=1),
        )
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_valid_program_item_is_accepted(self):
        item = ProgramItem(
            event=self.event,
            title="Лекция",
            speaker="Иван Петров",
            starts_at=self.event.starts_at + timedelta(hours=1),
            ends_at=self.event.starts_at + timedelta(hours=2),
        )
        item.full_clean()
        item.save()
        self.assertEqual(self.event.program_items.count(), 1)

    def test_items_are_ordered(self):
        for index in range(3):
            ProgramItem.objects.create(
                event=self.event,
                title=f"Точка {index}",
                starts_at=self.event.starts_at + timedelta(hours=index),
                ends_at=self.event.starts_at + timedelta(hours=index + 1),
                order=3 - index,
            )
        titles = [item.title for item in self.event.program_items.all()]
        self.assertEqual(titles, ["Точка 2", "Точка 1", "Точка 0"])


class EventVisibilityTests(TestCase):
    """Кои събития се виждат в каталога от кого."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("vis_owner", Role.ORGANIZER)
        cls.other = make_user("vis_other", Role.ORGANIZER)
        cls.participant = make_user("vis_part")
        cls.admin = make_user("vis_admin", Role.ADMIN)
        cls.venue = make_venue(capacity=500)

        cls.published = make_event(
            cls.owner, venue=cls.venue, capacity=20, title="Публикувано събитие"
        )
        cls.draft = make_event(
            cls.owner,
            venue=cls.venue,
            capacity=20,
            status=EventStatus.DRAFT,
            title="Черново събитие",
        )

    def test_anonymous_sees_only_published(self):
        response = self.client.get(reverse("events:event_list") + "?period=all")
        self.assertContains(response, "Публикувано събитие")
        self.assertNotContains(response, "Черново събитие")

    def test_participant_sees_only_published(self):
        self.client.force_login(self.participant)
        response = self.client.get(reverse("events:event_list") + "?period=all")
        self.assertNotContains(response, "Черново събитие")

    def test_owner_sees_own_draft(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("events:event_list") + "?period=all")
        self.assertContains(response, "Черново събитие")

    def test_other_organizer_does_not_see_foreign_draft(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("events:event_list") + "?period=all")
        self.assertNotContains(response, "Черново събитие")

    def test_admin_sees_all(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("events:event_list") + "?period=all")
        self.assertContains(response, "Черново събитие")


class EventStatusWorkflowTests(TestCase):
    """Смяна на статуса на събитие."""

    def setUp(self):
        self.organizer = make_user("org_flow", Role.ORGANIZER)
        self.event = make_event(
            self.organizer, capacity=20, status=EventStatus.DRAFT, title="Работен процес"
        )
        self.client.force_login(self.organizer)
        self.url = reverse("events:event_change_status", kwargs={"slug": self.event.slug})

    def test_cannot_publish_without_ticket_types(self):
        self.client.post(self.url, {"status": EventStatus.PUBLISHED})
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, EventStatus.DRAFT)

    def test_can_publish_with_ticket_type(self):
        make_ticket_type(self.event)
        self.client.post(self.url, {"status": EventStatus.PUBLISHED})
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, EventStatus.PUBLISHED)

    def test_invalid_status_is_rejected(self):
        self.client.post(self.url, {"status": "NONSENSE"})
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, EventStatus.DRAFT)
