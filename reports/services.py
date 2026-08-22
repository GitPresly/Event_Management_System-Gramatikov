"""
Изчисляване на отчетите.

Заданието поставя „точност на отчетите“ като отделен критерий за оценка,
затова всички числа се получават чрез агрегиращи заявки към базата данни
(SUM, COUNT), а не чрез обхождане на записите в Python. Причини:

  * базата брои върху актуалните данни в един момент, без разминаване;
  * при десетки хиляди билета обхождането в Python би било неприемливо бавно;
  * закръгляването на паричните суми се прави от типа NUMERIC, а не от
    двоичен плаващ тип, който натрупва грешка.
"""
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate, TruncHour
from django.utils import timezone

from checkin.models import CheckIn, ScanLog, ScanResult
from events.models import Event, TicketType
from registration.models import Registration, RegistrationStatus, Ticket, TicketStatus

# Статусите, при които билетът се брои за продаден.
SOLD_STATUSES = [TicketStatus.VALID, TicketStatus.USED]

MONEY = DecimalField(max_digits=12, decimal_places=2)
ZERO = Value(Decimal("0.00"), output_field=MONEY)


def event_report(event: Event) -> dict:
    """
    Пълен отчет за едно събитие: посещаемост и приходи.

    Връща речник, готов за подаване към шаблона.
    """
    tickets = Ticket.objects.filter(event=event)

    # --- Обобщени количества -------------------------------------------------
    totals = tickets.aggregate(
        issued=Count("id", filter=Q(status__in=SOLD_STATUSES)),
        reserved=Count("id", filter=Q(status=TicketStatus.RESERVED)),
        cancelled=Count("id", filter=Q(status=TicketStatus.CANCELLED)),
        attended=Count("id", filter=Q(status=TicketStatus.USED)),
        revenue=Coalesce(Sum("price_paid", filter=Q(status__in=SOLD_STATUSES)), ZERO),
    )

    issued = totals["issued"]
    attended = totals["attended"]
    no_show = max(issued - attended, 0)

    # --- Разбивка по билетни типове -----------------------------------------
    by_type = list(
        TicketType.objects.filter(event=event)
        .annotate(
            sold=Count("tickets", filter=Q(tickets__status__in=SOLD_STATUSES)),
            attended_count=Count("tickets", filter=Q(tickets__status=TicketStatus.USED)),
            revenue=Coalesce(
                Sum("tickets__price_paid", filter=Q(tickets__status__in=SOLD_STATUSES)),
                ZERO,
            ),
        )
        .order_by("-revenue", "name")
    )

    # Имената на добавените атрибути се различават от property-тата на модела
    # (remaining, occupancy_percent) — иначе присвояването би било невъзможно.
    for row in by_type:
        row.attendance_percent = (
            round(row.attended_count * 100 / row.sold, 1) if row.sold else 0.0
        )
        row.remaining_count = max(row.quota - row.sold, 0)

    # --- Разбивка на регистрациите по статус --------------------------------
    registrations = Registration.objects.filter(event=event)
    reg_totals = registrations.aggregate(
        total=Count("id"),
        paid=Count("id", filter=Q(status=RegistrationStatus.PAID)),
        pending=Count("id", filter=Q(status=RegistrationStatus.PENDING)),
        cancelled=Count("id", filter=Q(status=RegistrationStatus.CANCELLED)),
        paid_amount=Coalesce(
            Sum("total_amount", filter=Q(status=RegistrationStatus.PAID)), ZERO
        ),
    )

    # --- Разпределение на влизанията по час ---------------------------------
    checkin_hours = list(
        CheckIn.objects.filter(event=event)
        .annotate(hour=TruncHour("checked_in_at"))
        .values("hour")
        .annotate(count=Count("id"))
        .order_by("hour")
    )
    hour_labels = [timezone.localtime(row["hour"]).strftime("%H:%M") for row in checkin_hours]
    hour_values = [row["count"] for row in checkin_hours]

    # --- Продажби по дни ----------------------------------------------------
    sales_by_day = list(
        Registration.objects.filter(event=event, status=RegistrationStatus.PAID)
        .annotate(day=TruncDate("paid_at"))
        .values("day")
        .annotate(count=Count("id"), amount=Coalesce(Sum("total_amount"), ZERO))
        .order_by("day")
    )
    day_labels = [row["day"].strftime("%d.%m") for row in sales_by_day if row["day"]]
    day_values = [float(row["amount"]) for row in sales_by_day if row["day"]]

    # --- Дневник на сканиранията (за оценка на проблемите на входа) ---------
    scan_summary = list(
        ScanLog.objects.filter(event=event)
        .values("result")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    scan_labels = {value: label for value, label in ScanResult.choices}
    for row in scan_summary:
        row["label"] = scan_labels.get(row["result"], row["result"])

    return {
        "event": event,
        "issued": issued,
        "reserved": totals["reserved"],
        "cancelled_tickets": totals["cancelled"],
        "attended": attended,
        "no_show": no_show,
        "revenue": totals["revenue"],
        "attendance_percent": round(attended * 100 / issued, 1) if issued else 0.0,
        "occupancy_percent": round(issued * 100 / event.capacity, 1) if event.capacity else 0.0,
        "average_ticket_price": (
            (totals["revenue"] / issued).quantize(Decimal("0.01")) if issued else Decimal("0.00")
        ),
        "capacity": event.capacity,
        "seats_left": max(event.capacity - issued - totals["reserved"], 0),
        "by_type": by_type,
        "registrations": reg_totals,
        "hour_labels": hour_labels,
        "hour_values": hour_values,
        "day_labels": day_labels,
        "day_values": day_values,
        "scan_summary": scan_summary,
    }


def overview_report(events_qs, date_from=None, date_to=None) -> dict:
    """
    Обобщен отчет за няколко събития (табло на организатора/администратора).

    events_qs вече е ограничен според ролята на потребителя, така че тук няма
    нужда от допълнителна проверка за права.
    """
    if date_from:
        events_qs = events_qs.filter(starts_at__gte=date_from)
    if date_to:
        events_qs = events_qs.filter(starts_at__lte=date_to)

    event_ids = list(events_qs.values_list("id", flat=True))

    tickets = Ticket.objects.filter(event_id__in=event_ids)
    totals = tickets.aggregate(
        issued=Count("id", filter=Q(status__in=SOLD_STATUSES)),
        attended=Count("id", filter=Q(status=TicketStatus.USED)),
        revenue=Coalesce(Sum("price_paid", filter=Q(status__in=SOLD_STATUSES)), ZERO),
    )

    rows = list(
        events_qs.select_related("venue")
        .annotate(
            issued=Count("tickets", filter=Q(tickets__status__in=SOLD_STATUSES), distinct=True),
            attended=Count(
                "tickets", filter=Q(tickets__status=TicketStatus.USED), distinct=True
            ),
            revenue=Coalesce(
                Sum("tickets__price_paid", filter=Q(tickets__status__in=SOLD_STATUSES)),
                ZERO,
            ),
        )
        .order_by("-starts_at")
    )

    for row in rows:
        row.attendance_percent = (
            round(row.attended * 100 / row.issued, 1) if row.issued else 0.0
        )
        # occupancy_percent е property на Event, затова тук се използва друго име.
        row.occupancy = (
            round(row.issued * 100 / row.capacity, 1) if row.capacity else 0.0
        )

    issued = totals["issued"]
    attended = totals["attended"]

    return {
        "events": rows,
        "event_count": len(event_ids),
        "issued": issued,
        "attended": attended,
        "no_show": max(issued - attended, 0),
        "revenue": totals["revenue"],
        "attendance_percent": round(attended * 100 / issued, 1) if issued else 0.0,
        "chart_labels": [row.title for row in rows[:10]],
        "chart_revenue": [float(row.revenue) for row in rows[:10]],
        "chart_attended": [row.attended for row in rows[:10]],
    }


def attendee_rows(event: Event):
    """
    Редовете за експорт в CSV — по един на билет.

    Използва се от изгледа за сваляне на отчета.
    """
    return (
        Ticket.objects.filter(event=event)
        .exclude(status=TicketStatus.CANCELLED)
        .select_related("ticket_type", "registration", "registration__user", "checkin")
        .annotate(checked_in_at=F("checkin__checked_in_at"))
        .order_by("registration__code", "issued_at")
    )
