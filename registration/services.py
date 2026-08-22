"""
Бизнес логика на модул „Регистрация“.

Тук е решено нефункционалното изискване „обработка на голям брой едновременни
регистрации“. Проблемът е класически: ако двама участници заявят последното
свободно място в един и същи момент, наивната проверка

    if event.seats_available >= 1:   # и двамата виждат 1 свободно място
        create_ticket()              # и двамата създават билет

продава едно място два пъти. Решението тук е песимистично заключване:

  1. Цялата операция е в една транзакция (transaction.atomic).
  2. Редът на събитието се заключва с SELECT ... FOR UPDATE. Втората заявка
     изчаква, докато първата приключи.
  3. Свободните места и квотите се преброяват ОТНОВО, вече вътре в
     заключението, върху актуалните данни.

Така при N едновременни заявки за M места се продават точно M билета.
"""
import logging
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from events.models import Event, TicketType
from registration.models import (
    Payment,
    PaymentMethod,
    PaymentStatus,
    Registration,
    RegistrationStatus,
    Ticket,
    TicketStatus,
)
from registration.qr import attach_qr_to_ticket

logger = logging.getLogger(__name__)

# Статусите, при които билетът заема място от капацитета.
OCCUPYING_STATUSES = [TicketStatus.RESERVED, TicketStatus.VALID, TicketStatus.USED]


class RegistrationError(Exception):
    """Грешка в процеса на регистрация, която трябва да се покаже на потребителя."""


@dataclass(frozen=True)
class TicketRequest:
    """Заявено количество от един билетен тип."""

    ticket_type_id: int
    quantity: int


def _count_occupied(event_id: int) -> int:
    """Брой места, заети към този момент за дадено събитие."""
    return Ticket.objects.filter(
        event_id=event_id, status__in=OCCUPYING_STATUSES
    ).count()


def _count_occupied_per_type(ticket_type_ids) -> dict[int, int]:
    """Брой заети места по билетни типове — с една заявка вместо по една на тип."""
    rows = (
        Ticket.objects.filter(
            ticket_type_id__in=ticket_type_ids, status__in=OCCUPYING_STATUSES
        )
        .values("ticket_type_id")
        .annotate(total=Count("id"))
    )
    return {row["ticket_type_id"]: row["total"] for row in rows}


@transaction.atomic
def reserve_tickets(user, event, requests: list[TicketRequest], contact=None) -> Registration:
    """
    Създава заявка за регистрация и резервира местата.

    Аргументи:
        user     — участникът, който се регистрира;
        event    — събитието;
        requests — списък от заявени количества по билетни типове;
        contact  — по избор речник с contact_name/contact_email/contact_phone.

    Връща създадената заявка със статус „Чака плащане“.
    Хвърля RegistrationError при невалидна или неизпълнима заявка.
    """
    requested = [r for r in requests if r.quantity > 0]
    if not requested:
        raise RegistrationError("Изберете поне един билет.")

    total_quantity = sum(r.quantity for r in requested)
    max_allowed = settings.MAX_TICKETS_PER_REGISTRATION
    if total_quantity > max_allowed:
        raise RegistrationError(
            f"Не може да заявите повече от {max_allowed} билета в една регистрация."
        )

    # 1) Заключваме реда на събитието. Всяка друга едновременна регистрация за
    #    същото събитие изчаква тук, докато текущата транзакция приключи.
    locked_event = Event.objects.select_for_update().get(pk=event.pk)

    if not locked_event.is_registration_open:
        raise RegistrationError(
            locked_event.registration_closed_reason or "Регистрацията е затворена."
        )

    # 2) Заключваме и заявените билетни типове (подредени по идентификатор, за
    #    да не се стигне до взаимно блокиране при разминаващ се ред на заключване).
    type_ids = sorted({r.ticket_type_id for r in requested})
    locked_types = {
        tt.id: tt
        for tt in TicketType.objects.select_for_update()
        .filter(id__in=type_ids, event=locked_event)
        .order_by("id")
    }

    if len(locked_types) != len(type_ids):
        raise RegistrationError("Избран е билетен тип, който не принадлежи на това събитие.")

    # 3) Препроверка на общия капацитет — вече върху актуалните данни.
    occupied = _count_occupied(locked_event.pk)
    free_seats = locked_event.capacity - occupied
    if total_quantity > free_seats:
        if free_seats <= 0:
            raise RegistrationError("За съжаление всички места вече са изчерпани.")
        raise RegistrationError(
            f"Останали са само {free_seats} свободни места, а заявявате {total_quantity}."
        )

    # 4) Препроверка на квотите по билетни типове.
    occupied_per_type = _count_occupied_per_type(type_ids)
    for request_item in requested:
        ticket_type = locked_types[request_item.ticket_type_id]
        if not ticket_type.is_active:
            raise RegistrationError(f"Билетен тип „{ticket_type.name}“ вече не е активен.")

        now = timezone.now()
        if ticket_type.sales_start and now < ticket_type.sales_start:
            raise RegistrationError(
                f"Продажбите за „{ticket_type.name}“ още не са започнали."
            )
        if ticket_type.sales_end and now > ticket_type.sales_end:
            raise RegistrationError(f"Продажбите за „{ticket_type.name}“ са приключили.")

        remaining = ticket_type.quota - occupied_per_type.get(ticket_type.id, 0)
        if request_item.quantity > remaining:
            if remaining <= 0:
                raise RegistrationError(
                    f"Билетите от тип „{ticket_type.name}“ са изчерпани."
                )
            raise RegistrationError(
                f"От тип „{ticket_type.name}“ са останали само {remaining} билета."
            )

    # 5) Създаваме заявката и билетите.
    contact = contact or {}
    registration = Registration.objects.create(
        user=user,
        event=locked_event,
        status=RegistrationStatus.PENDING,
        contact_name=contact.get("contact_name") or user.display_name(),
        contact_email=contact.get("contact_email") or user.email,
        contact_phone=contact.get("contact_phone") or user.phone,
        total_amount=Decimal("0.00"),
    )

    tickets = []
    total = Decimal("0.00")
    for request_item in requested:
        ticket_type = locked_types[request_item.ticket_type_id]
        for _ in range(request_item.quantity):
            tickets.append(
                Ticket(
                    registration=registration,
                    ticket_type=ticket_type,
                    event=locked_event,
                    holder_name=registration.contact_name,
                    holder_email=registration.contact_email,
                    price_paid=ticket_type.price,
                    status=TicketStatus.RESERVED,
                )
            )
            total += ticket_type.price

    Ticket.objects.bulk_create(tickets)

    registration.total_amount = total
    registration.save(update_fields=["total_amount"])

    logger.info(
        "Създадена регистрация %s за събитие %s: %s билета, %s лв.",
        registration.code,
        locked_event.pk,
        total_quantity,
        total,
    )
    return registration


@transaction.atomic
def simulate_payment(registration: Registration, method: str = PaymentMethod.CARD) -> Payment:
    """
    Симулира плащане по заявката и издава билетите.

    Реален платежен процесор не се използва — заданието изисква симулация.
    След „плащането“ билетите стават валидни и за всеки се генерира QR код.
    """
    locked = Registration.objects.select_for_update().get(pk=registration.pk)

    if locked.status == RegistrationStatus.PAID:
        raise RegistrationError("Тази заявка вече е платена.")
    if locked.status == RegistrationStatus.CANCELLED:
        raise RegistrationError("Тази заявка е отказана и не може да бъде платена.")

    if method not in PaymentMethod.values:
        raise RegistrationError("Невалиден начин на плащане.")

    payment = Payment.objects.create(
        registration=locked,
        amount=locked.total_amount,
        method=method,
        transaction_ref=Payment.generate_reference(),
        status=PaymentStatus.SUCCESS,
    )

    locked.status = RegistrationStatus.PAID
    locked.paid_at = timezone.now()
    locked.save(update_fields=["status", "paid_at"])

    # Билетите стават валидни и получават своя QR код.
    tickets = list(locked.tickets.filter(status=TicketStatus.RESERVED))
    for ticket in tickets:
        ticket.status = TicketStatus.VALID
        ticket.save(update_fields=["status"])
        attach_qr_to_ticket(ticket)

    logger.info(
        "Платена заявка %s (%s лв., %s), издадени %s билета",
        locked.code,
        locked.total_amount,
        method,
        len(tickets),
    )

    # Потвърждението се изпраща след успешно записване на транзакцията, за да
    # не тръгне имейл при последващо оттегляне (rollback).
    from notifications.services import send_confirmation

    transaction.on_commit(lambda: send_confirmation(locked))

    registration.refresh_from_db()
    return payment


@transaction.atomic
def cancel_registration(registration: Registration, by_user=None) -> Registration:
    """
    Отказва заявка и освобождава заетите места.

    Билети, които вече са били използвани за вход, не се анулират — участникът
    реално е присъствал и това трябва да остане в отчетите.
    """
    locked = Registration.objects.select_for_update().get(pk=registration.pk)

    if locked.status == RegistrationStatus.CANCELLED:
        raise RegistrationError("Заявката вече е отказана.")

    if locked.tickets.filter(status=TicketStatus.USED).exists():
        raise RegistrationError(
            "Заявката не може да бъде отказана — част от билетите вече са използвани."
        )

    locked.tickets.filter(
        status__in=[TicketStatus.RESERVED, TicketStatus.VALID]
    ).update(status=TicketStatus.CANCELLED)

    locked.status = RegistrationStatus.CANCELLED
    locked.cancelled_at = timezone.now()
    locked.save(update_fields=["status", "cancelled_at"])

    logger.info("Отказана заявка %s от %s", locked.code, by_user or "система")

    from notifications.services import send_cancellation

    transaction.on_commit(lambda: send_cancellation(locked))

    registration.refresh_from_db()
    return locked


def availability_snapshot(event: Event) -> dict:
    """
    Връща моментна картина на наличността за дадено събитие.

    Използва се от страницата на събитието и от формата за регистрация.
    Изчислява се с една заявка към базата вместо с по една на билетен тип.
    """
    occupied = Ticket.objects.filter(
        event=event, status__in=OCCUPYING_STATUSES
    ).count()

    per_type = (
        TicketType.objects.filter(event=event)
        .annotate(
            sold=Count("tickets", filter=Q(tickets__status__in=OCCUPYING_STATUSES))
        )
        .order_by("price")
    )

    return {
        "capacity": event.capacity,
        "occupied": occupied,
        "available": max(event.capacity - occupied, 0),
        "ticket_types": per_type,
    }
