"""
Тестове на изпращането на писма.

Проверява изискването „изпращане на потвърждения и напомняния по имейл“.
"""
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from notifications.models import EmailKind, EmailLog, EmailStatus
from notifications.services import reminder_already_sent, send_reminder
from registration.models import PaymentMethod
from registration.services import (
    TicketRequest,
    cancel_registration,
    reserve_tickets,
    simulate_payment,
)
from registration.tests.factories import make_event, make_ticket_type, make_user


class ConfirmationEmailTests(TestCase):
    """Потвърждение след успешно плащане."""

    def setUp(self):
        mail.outbox = []
        self.organizer = make_user("org_mail", Role.ORGANIZER)
        self.participant = make_user("part_mail", email="kupuvach@example.com")
        self.event = make_event(self.organizer, capacity=50, title="Събитие с писма")
        self.ticket_type = make_ticket_type(self.event, price="35.00", quota=50)

    def _pay(self, registration):
        """
        Плаща заявката и изпълнява отложените действия след транзакцията.

        Писмата се изпращат чрез transaction.on_commit, за да не тръгне
        потвърждение при оттеглена транзакция. В тестовете нищо не се записва
        реално, затова тези действия се изпълняват изрично.
        """
        with self.captureOnCommitCallbacks(execute=True):
            simulate_payment(registration, PaymentMethod.CARD)

    def _reserve(self, quantity):
        return reserve_tickets(
            self.participant, self.event, [TicketRequest(self.ticket_type.id, quantity)]
        )

    def test_confirmation_is_sent_after_payment(self):
        registration = self._reserve(2)
        # Преди плащане не се изпраща нищо.
        self.assertEqual(len(mail.outbox), 0)

        self._pay(registration)

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["kupuvach@example.com"])
        self.assertIn(self.event.title, message.subject)
        self.assertIn(registration.code, message.body)

    def test_confirmation_has_html_alternative(self):
        self._pay(self._reserve(1))

        message = mail.outbox[0]
        self.assertEqual(len(message.alternatives), 1)
        html_body, mimetype = message.alternatives[0]
        self.assertEqual(mimetype, "text/html")
        self.assertIn(self.event.title, html_body)

    def test_qr_codes_are_attached(self):
        """Всеки билет пътува със своя QR код като прикачен файл."""
        self._pay(self._reserve(3))

        message = mail.outbox[0]
        self.assertEqual(len(message.attachments), 3)
        for filename, content, mimetype in message.attachments:
            self.assertTrue(filename.startswith("bilet-"))
            self.assertEqual(mimetype, "image/png")
            self.assertTrue(content.startswith(b"\x89PNG"))

    def test_email_is_logged(self):
        registration = self._reserve(1)
        self._pay(registration)

        log = EmailLog.objects.get(registration=registration, kind=EmailKind.CONFIRMATION)
        self.assertEqual(log.status, EmailStatus.SENT)
        self.assertEqual(log.recipient, "kupuvach@example.com")

    def test_cancellation_email_is_sent(self):
        registration = self._reserve(1)
        self._pay(registration)
        mail.outbox = []

        with self.captureOnCommitCallbacks(execute=True):
            cancel_registration(registration)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Отказана", mail.outbox[0].subject)
        self.assertTrue(
            EmailLog.objects.filter(
                registration=registration, kind=EmailKind.CANCELLATION
            ).exists()
        )


class ReminderCommandTests(TestCase):
    """Командата send_reminders."""

    def setUp(self):
        mail.outbox = []
        self.organizer = make_user("org_rem", Role.ORGANIZER)
        self.participant = make_user("part_rem", email="uchastnik@example.com")

        # Събитие след 12 часа — попада в прозореца от 24 часа.
        self.soon_event = make_event(
            self.organizer, capacity=50, title="Скоро", starts_in_days=0
        )
        self.soon_event.starts_at = timezone.now() + timedelta(hours=12)
        self.soon_event.ends_at = self.soon_event.starts_at + timedelta(hours=3)
        self.soon_event.registration_deadline = self.soon_event.starts_at
        self.soon_event.save()

        ticket_type = make_ticket_type(self.soon_event, quota=50)
        self.registration = reserve_tickets(
            self.participant, self.soon_event, [TicketRequest(ticket_type.id, 1)]
        )
        simulate_payment(self.registration, PaymentMethod.CARD)
        mail.outbox = []

    def _run(self, *args):
        out = StringIO()
        call_command("send_reminders", *args, stdout=out)
        return out.getvalue()

    def test_reminder_is_sent_for_upcoming_event(self):
        self._run()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Напомняне", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["uchastnik@example.com"])

    def test_reminder_is_not_sent_twice(self):
        """Втори пуск на командата не праща повторно писмо на същия участник."""
        self._run()
        mail.outbox = []

        output = self._run()

        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("пропуснати", output)
        self.assertEqual(
            EmailLog.objects.filter(
                registration=self.registration, kind=EmailKind.REMINDER
            ).count(),
            1,
        )

    def test_distant_event_gets_no_reminder(self):
        """Събитие извън прозореца не поражда напомняне."""
        far_organizer = make_user("org_far", Role.ORGANIZER)
        far_event = make_event(
            far_organizer, capacity=20, title="Далечно", starts_in_days=30
        )
        ticket_type = make_ticket_type(far_event, quota=20)
        far_user = make_user("part_far")
        registration = reserve_tickets(
            far_user, far_event, [TicketRequest(ticket_type.id, 1)]
        )
        simulate_payment(registration, PaymentMethod.CARD)
        mail.outbox = []

        self._run()

        recipients = [address for message in mail.outbox for address in message.to]
        self.assertNotIn(far_user.email, recipients)

    def test_unpaid_registration_gets_no_reminder(self):
        other = make_user("part_unpaid_rem", email="neplatil@example.com")
        ticket_type = self.soon_event.ticket_types.first()
        reserve_tickets(other, self.soon_event, [TicketRequest(ticket_type.id, 1)])
        mail.outbox = []

        self._run()

        recipients = [address for message in mail.outbox for address in message.to]
        self.assertNotIn("neplatil@example.com", recipients)

    def test_dry_run_sends_nothing(self):
        output = self._run("--dry-run")

        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("пробно", output)
        self.assertFalse(
            EmailLog.objects.filter(kind=EmailKind.REMINDER).exists()
        )

    def test_hours_option_widens_the_window(self):
        far_organizer = make_user("org_wide", Role.ORGANIZER)
        far_event = make_event(
            far_organizer, capacity=20, title="След 3 дни", starts_in_days=3
        )
        ticket_type = make_ticket_type(far_event, quota=20)
        far_user = make_user("part_wide", email="dalechen@example.com")
        registration = reserve_tickets(
            far_user, far_event, [TicketRequest(ticket_type.id, 1)]
        )
        simulate_payment(registration, PaymentMethod.CARD)
        mail.outbox = []

        self._run("--hours", "96")

        recipients = [address for message in mail.outbox for address in message.to]
        self.assertIn("dalechen@example.com", recipients)


class ReminderHelperTests(TestCase):
    """Помощната функция за проверка на вече изпратени напомняния."""

    def test_reminder_already_sent_reflects_the_log(self):
        organizer = make_user("org_helper", Role.ORGANIZER)
        participant = make_user("part_helper")
        event = make_event(organizer, capacity=20, title="Помощник")
        ticket_type = make_ticket_type(event, quota=20)

        registration = reserve_tickets(
            participant, event, [TicketRequest(ticket_type.id, 1)]
        )
        simulate_payment(registration, PaymentMethod.CARD)

        self.assertFalse(reminder_already_sent(registration))
        send_reminder(registration)
        self.assertTrue(reminder_already_sent(registration))
