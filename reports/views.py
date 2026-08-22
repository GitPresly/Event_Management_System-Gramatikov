"""
Изгледи на модул „Отчети“.

Достъпът е ограничен до организатори (само за собствените им събития) и
администратори (за всички).
"""
import csv
from datetime import datetime

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.models import Role
from accounts.permissions import get_managed_event, role_required, scope_events_for
from events.models import Event
from registration.models import TicketStatus
from reports.services import attendee_rows, event_report, overview_report


def _parse_date(value: str):
    """Превръща дата от формуляра (ГГГГ-ММ-ДД) в момент с часова зона."""
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return timezone.make_aware(parsed, timezone.get_current_timezone())


@role_required(Role.ORGANIZER)
def overview(request):
    """Обобщен отчет за всички управлявани събития."""
    events = scope_events_for(request.user, Event.objects.all())

    date_from = _parse_date(request.GET.get("from", ""))
    date_to = _parse_date(request.GET.get("to", ""))

    data = overview_report(events, date_from=date_from, date_to=date_to)
    data.update(
        {
            "date_from": request.GET.get("from", ""),
            "date_to": request.GET.get("to", ""),
        }
    )
    return render(request, "reports/overview.html", data)


@role_required(Role.ORGANIZER)
def event_detail(request, slug):
    """Подробен отчет за едно събитие — посещаемост и приходи."""
    event = get_managed_event(request.user, Event, slug=slug)
    data = event_report(event)
    return render(request, "reports/event_report.html", data)


@role_required(Role.ORGANIZER)
def event_export(request, slug):
    """Експорт на списъка с участници и статуса им на входа в CSV."""
    event = get_managed_event(request.user, Event, slug=slug)

    # Кодировката е utf-8, а не utf-8-sig: HttpResponse.write() кодира всеки
    # подаден низ поотделно, така че utf-8-sig би поставил BOM пред всеки ред.
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"otchet-{event.slug}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Един BOM в началото на файла, за да разпознае Excel кирилицата правилно.
    response.write("﻿")

    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        [
            "Заявка",
            "Код на билета",
            "Билетен тип",
            "Притежател",
            "Имейл",
            "Цена (лв.)",
            "Статус",
            "Час на влизане",
        ]
    )

    for ticket in attendee_rows(event):
        checked_in = (
            timezone.localtime(ticket.checked_in_at).strftime("%d.%m.%Y %H:%M:%S")
            if ticket.checked_in_at
            else ""
        )
        writer.writerow(
            [
                ticket.registration.code,
                ticket.short_code,
                ticket.ticket_type.name,
                ticket.holder_name,
                ticket.holder_email,
                f"{ticket.price_paid}".replace(".", ","),
                TicketStatus(ticket.status).label,
                checked_in,
            ]
        )

    return response


@role_required(Role.ORGANIZER)
def overview_export(request):
    """Експорт на обобщения отчет по събития в CSV."""
    events = scope_events_for(request.user, Event.objects.all())
    date_from = _parse_date(request.GET.get("from", ""))
    date_to = _parse_date(request.GET.get("to", ""))
    data = overview_report(events, date_from=date_from, date_to=date_to)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="obobshten-otchet.csv"'
    # Един BOM в началото на файла (виж бележката в event_export).
    response.write("﻿")

    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        [
            "Събитие",
            "Дата",
            "Локация",
            "Места",
            "Продадени билети",
            "Присъствали",
            "Посещаемост (%)",
            "Приходи (лв.)",
        ]
    )

    for event in data["events"]:
        writer.writerow(
            [
                event.title,
                timezone.localtime(event.starts_at).strftime("%d.%m.%Y %H:%M"),
                str(event.venue),
                event.capacity,
                event.issued,
                event.attended,
                f"{event.attendance_percent}".replace(".", ","),
                f"{event.revenue}".replace(".", ","),
            ]
        )

    writer.writerow([])
    writer.writerow(
        [
            "ОБЩО",
            "",
            "",
            "",
            data["issued"],
            data["attended"],
            f"{data['attendance_percent']}".replace(".", ","),
            f"{data['revenue']}".replace(".", ","),
        ]
    )

    return response
