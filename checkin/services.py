"""
Логика на проверката на билети на входа.

Функцията process_scan е единствената точка, през която минава всяко
сканиране — и от камерата, и от ръчното въвеждане на код. Така правилата за
валидност са на едно място и не могат да се заобиколят.

Редът на проверките е от най-евтината към най-скъпата:
  1. подпис на кода      — само изчисление, без обръщение към базата;
  2. съществуване на билета;
  3. принадлежност към правилното събитие;
  4. статус на билета;
  5. заключване на реда и създаване на записа за вход.
"""
import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import TextField
from django.db.models.functions import Cast
from django.utils import timezone

from checkin.models import CheckIn, ScanLog, ScanResult
from events.models import EventStatus
from registration.models import Ticket, TicketStatus
from registration.qr import InvalidTicketError, verify_payload

logger = logging.getLogger(__name__)


@dataclass
class ScanOutcome:
    """Резултат от едно сканиране — връща се към интерфейса."""

    result: str
    message: str
    ticket: Ticket | None = None
    checkin: CheckIn | None = None

    @property
    def is_success(self) -> bool:
        return self.result == ScanResult.OK

    @property
    def result_label(self) -> str:
        return ScanResult(self.result).label

    def as_dict(self) -> dict:
        """Представяне за JSON отговора към страницата за сканиране."""
        data = {
            "success": self.is_success,
            "result": self.result,
            "result_label": self.result_label,
            "message": self.message,
        }
        if self.ticket:
            data["ticket"] = {
                "code": self.ticket.short_code,
                "holder": self.ticket.holder_name,
                "type": self.ticket.ticket_type.name,
                "registration": self.ticket.registration.code,
            }
        if self.checkin:
            data["checked_in_at"] = timezone.localtime(
                self.checkin.checked_in_at
            ).strftime("%H:%M:%S")
        return data


def _log(event, operator, result, payload, ticket=None, ip=None) -> None:
    """Записва опита в дневника. Всяко сканиране оставя следа."""
    ScanLog.objects.create(
        event=event,
        ticket=ticket,
        operator=operator,
        result=result,
        payload_preview=(payload or "")[:60],
        ip_address=ip,
    )


def process_scan(payload: str, event, operator, ip: str | None = None) -> ScanOutcome:
    """
    Обработва един сканиран (или ръчно въведен) код за конкретно събитие.

    Връща ScanOutcome и винаги записва ред в дневника на сканиранията.
    """
    payload = (payload or "").strip()

    # Събитието трябва да е в състояние, в което изобщо се пуска публика.
    if event.status in (EventStatus.DRAFT, EventStatus.CANCELLED):
        _log(event, operator, ScanResult.EVENT_NOT_ACTIVE, payload, ip=ip)
        return ScanOutcome(
            ScanResult.EVENT_NOT_ACTIVE,
            "Събитието не е активно — check-in не се извършва.",
        )

    # 1) Проверка на подписа. Подправен код се отхвърля тук, без справка в базата.
    try:
        ticket_uuid = verify_payload(payload)
    except InvalidTicketError as exc:
        # Допуска се и ръчно въведен съкратен код (първите 8 знака от uuid).
        ticket = _find_by_short_code(payload, event)
        if ticket is None:
            _log(event, operator, ScanResult.INVALID_SIGNATURE, payload, ip=ip)
            return ScanOutcome(ScanResult.INVALID_SIGNATURE, str(exc))
        ticket_uuid = str(ticket.uuid)

    # 2) Търсене на билета.
    ticket = (
        Ticket.objects.select_related("event", "ticket_type", "registration")
        .filter(uuid=ticket_uuid)
        .first()
    )
    if ticket is None:
        _log(event, operator, ScanResult.NOT_FOUND, payload, ip=ip)
        return ScanOutcome(ScanResult.NOT_FOUND, "Билетът не е намерен в системата.")

    # 3) Билетът трябва да е за това събитие.
    if ticket.event_id != event.id:
        _log(event, operator, ScanResult.WRONG_EVENT, payload, ticket=ticket, ip=ip)
        return ScanOutcome(
            ScanResult.WRONG_EVENT,
            f"Билетът е за друго събитие: „{ticket.event.title}“.",
            ticket=ticket,
        )

    # 4) Статус на билета.
    if ticket.status == TicketStatus.CANCELLED:
        _log(event, operator, ScanResult.CANCELLED, payload, ticket=ticket, ip=ip)
        return ScanOutcome(ScanResult.CANCELLED, "Билетът е анулиран.", ticket=ticket)

    if ticket.status == TicketStatus.RESERVED:
        _log(event, operator, ScanResult.NOT_PAID, payload, ticket=ticket, ip=ip)
        return ScanOutcome(
            ScanResult.NOT_PAID,
            f"Билетът не е платен (заявка {ticket.registration.code}).",
            ticket=ticket,
        )

    if ticket.status == TicketStatus.USED:
        existing = CheckIn.objects.filter(ticket=ticket).first()
        _log(event, operator, ScanResult.DUPLICATE, payload, ticket=ticket, ip=ip)
        moment = (
            timezone.localtime(existing.checked_in_at).strftime("%H:%M:%S")
            if existing
            else "по-рано"
        )
        return ScanOutcome(
            ScanResult.DUPLICATE,
            f"Този билет вече е използван в {moment}.",
            ticket=ticket,
            checkin=existing,
        )

    # 5) Записване на входа. Редът на билета се заключва, за да не могат две
    #    едновременни сканирания да минат и двете.
    try:
        with transaction.atomic():
            locked = Ticket.objects.select_for_update().get(pk=ticket.pk)

            # Повторна проверка вътре в заключението — статусът може да се е
            # променил, докато сме чакали ключалката.
            if locked.status != TicketStatus.VALID:
                existing = CheckIn.objects.filter(ticket=locked).first()
                _log(event, operator, ScanResult.DUPLICATE, payload, ticket=locked, ip=ip)
                return ScanOutcome(
                    ScanResult.DUPLICATE,
                    "Този билет вече е използван.",
                    ticket=locked,
                    checkin=existing,
                )

            checkin = CheckIn.objects.create(
                ticket=locked, event=event, operator=operator
            )
            locked.status = TicketStatus.USED
            locked.save(update_fields=["status"])
            ticket = locked

    except IntegrityError:
        # Последна преграда: уникалността в базата е отхвърлила втория запис.
        existing = CheckIn.objects.filter(ticket=ticket).first()
        _log(event, operator, ScanResult.DUPLICATE, payload, ticket=ticket, ip=ip)
        return ScanOutcome(
            ScanResult.DUPLICATE,
            "Този билет вече е използван.",
            ticket=ticket,
            checkin=existing,
        )

    _log(event, operator, ScanResult.OK, payload, ticket=ticket, ip=ip)
    logger.info(
        "Успешен check-in: билет %s, събитие %s, оператор %s",
        ticket.short_code,
        event.pk,
        operator.username,
    )
    return ScanOutcome(
        ScanResult.OK,
        f"Добре дошли, {ticket.holder_name}!",
        ticket=ticket,
        checkin=checkin,
    )


def _find_by_short_code(code: str, event) -> Ticket | None:
    """
    Търси билет по съкратения код, въведен ръчно.

    Ръчното въвеждане е резервен вариант, когато камерата не работи или QR
    кодът е повреден. Търси се само в рамките на текущото събитие, за да е
    практически невъзможно случайно съвпадение на съкратен код.
    """
    code = (code or "").strip().lower().replace(" ", "")
    if len(code) != 8:
        return None
    try:
        int(code, 16)  # съкратеният код е шестнадесетичен
    except ValueError:
        return None

    # В PostgreSQL колоната е от тип uuid, затова се преобразува към текст,
    # преди да се търси по начало на низа.
    return (
        Ticket.objects.select_related("event", "ticket_type", "registration")
        .filter(event=event)
        .annotate(uuid_text=Cast("uuid", TextField()))
        .filter(uuid_text__startswith=code)
        .first()
    )


def event_live_stats(event) -> dict:
    """
    Текущи показатели за таблото на организатора.

    Извиква се на всеки няколко секунди от страницата за check-in, затова е
    сведена до няколко броения по индексирани колони.
    """
    total_valid = Ticket.objects.filter(
        event=event, status__in=[TicketStatus.VALID, TicketStatus.USED]
    ).count()
    checked_in = CheckIn.objects.filter(event=event).count()

    recent = (
        CheckIn.objects.filter(event=event)
        .select_related("ticket", "ticket__ticket_type")
        .order_by("-checked_in_at")[:10]
    )

    return {
        "checked_in": checked_in,
        "total_tickets": total_valid,
        "remaining": max(total_valid - checked_in, 0),
        "percent": round(checked_in * 100 / total_valid, 1) if total_valid else 0.0,
        "capacity": event.capacity,
        "recent": [
            {
                "code": c.ticket.short_code,
                "holder": c.ticket.holder_name,
                "type": c.ticket.ticket_type.name,
                "time": timezone.localtime(c.checked_in_at).strftime("%H:%M:%S"),
            }
            for c in recent
        ],
    }
