"""
Изпращане на писма към участниците.

В режим на разработка (DEBUG=True) писмата не се изпращат реално, а се
извеждат в конзолата — това позволява целият поток да се демонстрира без
достъп до пощенски сървър. В продукция същият код работи през SMTP.

Всяко писмо се записва в дневника EmailLog, независимо дали е успешно.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from notifications.models import EmailKind, EmailLog, EmailStatus
from registration.models import TicketStatus

logger = logging.getLogger(__name__)


def _absolute_url(path: str) -> str:
    """Съставя пълен адрес към страница от системата за използване в писмата."""
    return f"{settings.SITE_URL.rstrip('/')}{path}"


def _send(
    kind: str,
    subject: str,
    recipient: str,
    text_body: str,
    html_body: str,
    registration=None,
    event=None,
    attachments=None,
) -> EmailLog:
    """
    Общата част от изпращането: съставя писмото, изпраща го и го записва.

    Грешката при изпращане не спира работата на приложението — тя се записва в
    дневника, за да може администраторът да я види. В противен случай отпаднал
    пощенски сървър би провалил и самата регистрация.
    """
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(html_body, "text/html")

    for filename, content, mimetype in attachments or []:
        message.attach(filename, content, mimetype)

    status = EmailStatus.SENT
    error = ""
    try:
        message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 — грешката се записва, не се крие
        status = EmailStatus.FAILED
        error = str(exc)
        logger.error("Неуспешно изпращане на писмо до %s: %s", recipient, exc)

    return EmailLog.objects.create(
        kind=kind,
        recipient=recipient,
        subject=subject,
        registration=registration,
        event=event,
        status=status,
        error=error,
    )


def send_confirmation(registration) -> EmailLog:
    """
    Изпраща потвърждение за успешна регистрация заедно с билетите.

    QR кодовете се прикачват като изображения, за да може участникът да покаже
    билета и без интернет връзка на място.
    """
    event = registration.event
    tickets = list(
        registration.tickets.filter(
            status__in=[TicketStatus.VALID, TicketStatus.USED]
        ).select_related("ticket_type")
    )

    context = {
        "registration": registration,
        "event": event,
        "tickets": tickets,
        "tickets_url": _absolute_url(reverse("registration:my_tickets")),
        "registration_url": _absolute_url(registration.get_absolute_url()),
    }

    subject = f"Потвърждение за регистрация — {event.title}"
    text_body = render_to_string("notifications/email/confirmation.txt", context)
    html_body = render_to_string("notifications/email/confirmation.html", context)

    # Прикачване на QR кодовете на билетите.
    attachments = []
    for ticket in tickets:
        if ticket.qr_image:
            try:
                ticket.qr_image.open("rb")
                attachments.append(
                    (f"bilet-{ticket.short_code}.png", ticket.qr_image.read(), "image/png")
                )
            except (FileNotFoundError, ValueError):
                logger.warning("Липсва QR изображение за билет %s", ticket.short_code)
            finally:
                ticket.qr_image.close()

    return _send(
        kind=EmailKind.CONFIRMATION,
        subject=subject,
        recipient=registration.contact_email,
        text_body=text_body,
        html_body=html_body,
        registration=registration,
        event=event,
        attachments=attachments,
    )


def send_reminder(registration) -> EmailLog:
    """Изпраща напомняне за предстоящо събитие."""
    event = registration.event
    tickets = list(
        registration.tickets.filter(status=TicketStatus.VALID).select_related("ticket_type")
    )

    hours_left = int((event.starts_at - timezone.now()).total_seconds() // 3600)

    context = {
        "registration": registration,
        "event": event,
        "tickets": tickets,
        "hours_left": max(hours_left, 0),
        "tickets_url": _absolute_url(reverse("registration:my_tickets")),
        "registration_url": _absolute_url(registration.get_absolute_url()),
    }

    subject = f"Напомняне: {event.title} — {timezone.localtime(event.starts_at):%d.%m.%Y, %H:%M}"
    text_body = render_to_string("notifications/email/reminder.txt", context)
    html_body = render_to_string("notifications/email/reminder.html", context)

    return _send(
        kind=EmailKind.REMINDER,
        subject=subject,
        recipient=registration.contact_email,
        text_body=text_body,
        html_body=html_body,
        registration=registration,
        event=event,
    )


def send_cancellation(registration) -> EmailLog:
    """Изпраща потвърждение, че заявката е отказана."""
    event = registration.event
    context = {
        "registration": registration,
        "event": event,
        "events_url": _absolute_url(reverse("events:event_list")),
    }

    subject = f"Отказана регистрация — {event.title}"
    text_body = render_to_string("notifications/email/cancellation.txt", context)
    html_body = render_to_string("notifications/email/cancellation.html", context)

    return _send(
        kind=EmailKind.CANCELLATION,
        subject=subject,
        recipient=registration.contact_email,
        text_body=text_body,
        html_body=html_body,
        registration=registration,
        event=event,
    )


def reminder_already_sent(registration) -> bool:
    """Проверява дали по тази заявка вече е изпратено напомняне."""
    return EmailLog.objects.filter(
        registration=registration, kind=EmailKind.REMINDER, status=EmailStatus.SENT
    ).exists()
