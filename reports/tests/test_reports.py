"""
Тестове за точността на отчетите.

Проверява критерия за оценка „точност на отчетите“: числата се сравняват с
предварително известни стойности, изчислени ръчно.
"""
from decimal import Decimal

from django.test import TestCase

from accounts.models import Role
from checkin.services import process_scan
from registration.models import PaymentMethod, TicketStatus
from registration.qr import build_payload
from registration.services import (
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
from reports.services import event_report, overview_report


class EventReportAccuracyTests(TestCase):
    """
    Известен набор от данни с ръчно пресметнати очаквани стойности.

    Сценарий:
      * 3 участника купуват по 1 стандартен билет (по 40.00 €) — платени;
      * 1 участник купува 2 VIP билета (по 100.00 €) — платени;
      * 1 участник резервира 1 стандартен билет, но не плаща;
      * 1 участник купува 1 стандартен билет и после отказва заявката;
      * от платените влизат 3 души.

    Очаквани стойности:
      продадени билети  = 3 + 2 = 5
      приходи           = 3×40 + 2×100 = 320.00 €
      присъствали       = 3
      посещаемост       = 3/5 = 60.0%
      неявили се        = 2
      среден билет      = 320/5 = 64.00 €
    """

    @classmethod
    def setUpTestData(cls):
        cls.organizer = make_user("org_rep", Role.ORGANIZER)
        cls.venue = make_venue(capacity=500)
        cls.event = make_event(cls.organizer, venue=cls.venue, capacity=100)
        cls.standard = make_ticket_type(cls.event, "Стандартен", "40.00", quota=50)
        cls.vip = make_ticket_type(cls.event, "VIP", "100.00", quota=10)

        cls.paid_tickets = []

        # Три платени стандартни билета.
        for index in range(3):
            user = make_user(f"rep_std{index}")
            registration = reserve_tickets(
                user, cls.event, [TicketRequest(cls.standard.id, 1)]
            )
            simulate_payment(registration, PaymentMethod.CARD)
            cls.paid_tickets.extend(registration.tickets.all())

        # Два платени VIP билета в една заявка.
        vip_user = make_user("rep_vip")
        vip_registration = reserve_tickets(
            vip_user, cls.event, [TicketRequest(cls.vip.id, 2)]
        )
        simulate_payment(vip_registration, PaymentMethod.BANK)
        cls.paid_tickets.extend(vip_registration.tickets.all())

        # Една неплатена резервация.
        pending_user = make_user("rep_pending")
        reserve_tickets(pending_user, cls.event, [TicketRequest(cls.standard.id, 1)])

        # Една отказана заявка.
        cancelled_user = make_user("rep_cancelled")
        cancelled = reserve_tickets(
            cancelled_user, cls.event, [TicketRequest(cls.standard.id, 1)]
        )
        simulate_payment(cancelled, PaymentMethod.CARD)
        cancel_registration(cancelled)

        # Трима от платените участници влизат на събитието.
        for ticket in cls.paid_tickets[:3]:
            process_scan(build_payload(ticket), cls.event, cls.organizer)

    def setUp(self):
        self.report = event_report(self.event)

    def test_issued_ticket_count(self):
        self.assertEqual(self.report["issued"], 5)

    def test_revenue_excludes_unpaid_and_cancelled(self):
        self.assertEqual(self.report["revenue"], Decimal("320.00"))

    def test_attended_count(self):
        self.assertEqual(self.report["attended"], 3)

    def test_no_show_count(self):
        self.assertEqual(self.report["no_show"], 2)

    def test_attendance_percent(self):
        self.assertEqual(self.report["attendance_percent"], 60.0)

    def test_average_ticket_price(self):
        self.assertEqual(self.report["average_ticket_price"], Decimal("64.00"))

    def test_reserved_and_cancelled_counts(self):
        self.assertEqual(self.report["reserved"], 1)
        self.assertEqual(self.report["cancelled_tickets"], 1)

    def test_occupancy_percent(self):
        # 5 продадени билета при 100 места
        self.assertEqual(self.report["occupancy_percent"], 5.0)

    def test_registration_status_breakdown(self):
        registrations = self.report["registrations"]
        self.assertEqual(registrations["total"], 6)
        self.assertEqual(registrations["paid"], 4)
        self.assertEqual(registrations["pending"], 1)
        self.assertEqual(registrations["cancelled"], 1)

    def test_breakdown_by_ticket_type(self):
        rows = {row.name: row for row in self.report["by_type"]}

        standard = rows["Стандартен"]
        self.assertEqual(standard.sold, 3)
        self.assertEqual(standard.revenue, Decimal("120.00"))

        vip = rows["VIP"]
        self.assertEqual(vip.sold, 2)
        self.assertEqual(vip.revenue, Decimal("200.00"))

        # Сборът по типове съвпада с общата сума — вътрешна съгласуваност.
        self.assertEqual(
            standard.revenue + vip.revenue, self.report["revenue"]
        )

    def test_scan_summary_records_all_attempts(self):
        results = {row["result"]: row["count"] for row in self.report["scan_summary"]}
        self.assertEqual(results.get("OK"), 3)


class EmptyReportTests(TestCase):
    """Отчет за събитие без никакви данни не трябва да се чупи."""

    def test_report_for_event_without_registrations(self):
        organizer = make_user("org_empty", Role.ORGANIZER)
        event = make_event(organizer, capacity=10, title="Празно събитие")
        make_ticket_type(event)

        report = event_report(event)

        self.assertEqual(report["issued"], 0)
        self.assertEqual(report["attended"], 0)
        self.assertEqual(report["revenue"], Decimal("0.00"))
        self.assertEqual(report["attendance_percent"], 0.0)
        self.assertEqual(report["average_ticket_price"], Decimal("0.00"))
        self.assertEqual(report["hour_values"], [])


class OverviewReportTests(TestCase):
    """Обобщеният отчет сумира правилно няколко събития."""

    @classmethod
    def setUpTestData(cls):
        cls.organizer = make_user("org_ov", Role.ORGANIZER)
        cls.other = make_user("org_ov2", Role.ORGANIZER)
        cls.venue = make_venue(capacity=500)

        # Събитие 1: 2 билета по 50.00 = 100.00 €, 1 присъствал.
        cls.event1 = make_event(cls.organizer, venue=cls.venue, capacity=20, title="Първо")
        type1 = make_ticket_type(cls.event1, price="50.00", quota=20)
        user1 = make_user("ov_u1")
        reg1 = reserve_tickets(user1, cls.event1, [TicketRequest(type1.id, 2)])
        simulate_payment(reg1, PaymentMethod.CARD)
        process_scan(build_payload(reg1.tickets.first()), cls.event1, cls.organizer)

        # Събитие 2: 3 билета по 30.00 = 90.00 €, без присъствали.
        cls.event2 = make_event(cls.organizer, venue=cls.venue, capacity=20, title="Второ")
        type2 = make_ticket_type(cls.event2, price="30.00", quota=20)
        user2 = make_user("ov_u2")
        reg2 = reserve_tickets(user2, cls.event2, [TicketRequest(type2.id, 3)])
        simulate_payment(reg2, PaymentMethod.CARD)

        # Събитие на друг организатор — не бива да влиза в отчета.
        cls.foreign = make_event(cls.other, venue=cls.venue, capacity=20, title="Чуждо")
        type3 = make_ticket_type(cls.foreign, price="500.00", quota=20)
        user3 = make_user("ov_u3")
        reg3 = reserve_tickets(user3, cls.foreign, [TicketRequest(type3.id, 1)])
        simulate_payment(reg3, PaymentMethod.CARD)

    def test_totals_across_own_events(self):
        from events.models import Event

        own = Event.objects.filter(organizer=self.organizer)
        report = overview_report(own)

        self.assertEqual(report["event_count"], 2)
        self.assertEqual(report["issued"], 5)
        self.assertEqual(report["revenue"], Decimal("190.00"))
        self.assertEqual(report["attended"], 1)
        self.assertEqual(report["no_show"], 4)
        self.assertEqual(report["attendance_percent"], 20.0)

    def test_foreign_event_revenue_is_excluded(self):
        from events.models import Event

        own = Event.objects.filter(organizer=self.organizer)
        report = overview_report(own)

        # 500.00 € от чуждото събитие не трябва да се появяват никъде.
        self.assertNotIn(Decimal("690.00"), [report["revenue"]])
        self.assertEqual(report["revenue"], Decimal("190.00"))

    def test_per_event_rows_are_correct(self):
        from events.models import Event

        own = Event.objects.filter(organizer=self.organizer)
        rows = {row.title: row for row in overview_report(own)["events"]}

        self.assertEqual(rows["Първо"].issued, 2)
        self.assertEqual(rows["Първо"].revenue, Decimal("100.00"))
        self.assertEqual(rows["Първо"].attended, 1)
        self.assertEqual(rows["Първо"].attendance_percent, 50.0)

        self.assertEqual(rows["Второ"].issued, 3)
        self.assertEqual(rows["Второ"].revenue, Decimal("90.00"))
        self.assertEqual(rows["Второ"].attendance_percent, 0.0)


class ReportExportTests(TestCase):
    """Експортът в CSV съдържа правилните редове."""

    @classmethod
    def setUpTestData(cls):
        cls.organizer = make_user("org_csv", Role.ORGANIZER)
        cls.event = make_event(cls.organizer, capacity=20, title="Експорт")
        ticket_type = make_ticket_type(cls.event, price="25.00", quota=20)

        user = make_user("csv_user")
        registration = reserve_tickets(
            user, cls.event, [TicketRequest(ticket_type.id, 2)]
        )
        simulate_payment(registration, PaymentMethod.CARD)
        cls.registration = registration

    def test_csv_export_contains_ticket_rows(self):
        from django.urls import reverse

        self.client.force_login(self.organizer)
        response = self.client.get(
            reverse("reports:event_export", kwargs={"slug": self.event.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])

        content = response.content.decode("utf-8-sig")
        self.assertIn("Код на билета", content)
        self.assertIn(self.registration.code, content)
        # Два билета означават два реда с данни.
        self.assertEqual(content.count(self.registration.code), 2)

    def test_csv_has_exactly_one_bom(self):
        """
        Файлът трябва да започва с точно един BOM.

        При кодировка utf-8-sig Django поставя BOM пред всеки записан низ, което
        разваля показването в Excel — затова се използва utf-8 и ръчен BOM.
        """
        from django.urls import reverse

        self.client.force_login(self.organizer)
        response = self.client.get(
            reverse("reports:event_export", kwargs={"slug": self.event.slug})
        )

        raw = response.content
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\xef\xbb\xbf"), 1)

        # Първата колона на заглавния ред започва веднага след BOM.
        self.assertTrue(raw[3:].startswith("Заявка".encode("utf-8")))

    def test_overview_csv_has_exactly_one_bom(self):
        from django.urls import reverse

        self.client.force_login(self.organizer)
        response = self.client.get(reverse("reports:overview_export"))

        self.assertEqual(response.content.count(b"\xef\xbb\xbf"), 1)
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))

    def test_cancelled_tickets_are_excluded_from_export(self):
        from django.urls import reverse

        cancel_registration(self.registration)

        self.client.force_login(self.organizer)
        response = self.client.get(
            reverse("reports:event_export", kwargs={"slug": self.event.slug})
        )
        content = response.content.decode("utf-8-sig")
        self.assertNotIn(self.registration.code, content)
