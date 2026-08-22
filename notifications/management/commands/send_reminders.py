"""
Команда за изпращане на напомняния за предстоящи събития.

Пуска се периодично (Windows Task Scheduler или cron). Изпраща напомняне на
всички участници с платена заявка за събитие, което започва в рамките на
зададения брой часове, като пропуска тези, на които вече е било изпратено.

Примери:
    python manage.py send_reminders
    python manage.py send_reminders --hours 48
    python manage.py send_reminders --dry-run
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import EventStatus
from notifications.services import reminder_already_sent, send_reminder
from registration.models import Registration, RegistrationStatus


class Command(BaseCommand):
    help = "Изпраща напомняния по имейл за предстоящи събития."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=settings.REMINDER_HOURS_BEFORE,
            help="Изпраща напомняния за събития, започващи в следващите N часа.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Само показва кой би получил напомняне, без да изпраща писма.",
        )
        parser.add_argument(
            "--event",
            type=str,
            default=None,
            help="Ограничава изпращането до едно събитие по неговия адресен идентификатор.",
        )

    def handle(self, *args, **options):
        hours = options["hours"]
        dry_run = options["dry_run"]
        event_slug = options["event"]

        now = timezone.now()
        window_end = now + timedelta(hours=hours)

        registrations = (
            Registration.objects.filter(
                status=RegistrationStatus.PAID,
                event__status=EventStatus.PUBLISHED,
                event__starts_at__gte=now,
                event__starts_at__lte=window_end,
            )
            .select_related("event", "user")
            .order_by("event__starts_at", "code")
        )

        if event_slug:
            registrations = registrations.filter(event__slug=event_slug)

        self.stdout.write(
            f"Проверка за събития до {timezone.localtime(window_end):%d.%m.%Y %H:%M} "
            f"({hours} ч.): намерени {registrations.count()} платени заявки."
        )

        sent = 0
        skipped = 0
        failed = 0

        for registration in registrations:
            if reminder_already_sent(registration):
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"  [пробно] {registration.code} → {registration.contact_email} "
                    f"({registration.event.title})"
                )
                sent += 1
                continue

            log = send_reminder(registration)
            if log.is_sent:
                sent += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Изпратено: {registration.code} → {registration.contact_email}"
                    )
                )
            else:
                failed += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"  Неуспешно: {registration.code} → {log.error}"
                    )
                )

        summary = (
            f"Готово. Изпратени: {sent}; пропуснати (вече напомнени): {skipped}; "
            f"неуспешни: {failed}."
        )
        self.stdout.write(self.style.SUCCESS(summary) if not failed else summary)
