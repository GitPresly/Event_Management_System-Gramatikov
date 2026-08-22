"""
Изгледи на модул „На място“.

Съдържа конзолата за сканиране (камера + ръчно въвеждане), крайната точка,
която обработва едно сканиране, и крайната точка за живата статистика.
"""
import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Role
from accounts.permissions import get_managed_event, role_required, scope_events_for
from checkin.models import CheckIn, ScanLog, ScanResult
from checkin.services import event_live_stats, process_scan
from events.models import Event, EventStatus


def _client_ip(request):
    """Извлича IP адреса на клиента (при работа зад обратен прокси)."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@role_required(Role.ORGANIZER)
def checkin_event_list(request):
    """Избор на събитие, за което да се извършва check-in."""
    events = (
        scope_events_for(request.user, Event.objects.all())
        .filter(status__in=[EventStatus.PUBLISHED, EventStatus.FINISHED])
        .select_related("venue")
        .order_by("-starts_at")
    )
    return render(request, "checkin/event_list.html", {"events": events})


@role_required(Role.ORGANIZER)
def scan_console(request, slug):
    """
    Конзола за проверка на билети.

    Показва скенер за QR код през камерата, поле за ръчно въвеждане на код и
    брояч на присъстващите, който се обновява автоматично.
    """
    event = get_managed_event(request.user, Event, slug=slug)
    stats = event_live_stats(event)

    return render(
        request,
        "checkin/scan_console.html",
        {"event": event, "stats": stats},
    )


@role_required(Role.ORGANIZER)
@require_POST
def scan(request, slug):
    """
    Обработва едно сканиране и връща резултата в JSON.

    Приема както JSON тяло (от скенера), така и обикновена форма (при ръчно
    въвеждане без JavaScript).
    """
    event = get_managed_event(request.user, Event, slug=slug)

    if request.content_type == "application/json":
        try:
            data = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return JsonResponse(
                {"success": False, "message": "Невалидни данни в заявката."}, status=400
            )
        payload = data.get("payload", "")
    else:
        payload = request.POST.get("payload", "")

    outcome = process_scan(
        payload=payload, event=event, operator=request.user, ip=_client_ip(request)
    )

    response = outcome.as_dict()
    response["stats"] = event_live_stats(event)
    return JsonResponse(response)


@role_required(Role.ORGANIZER)
@require_GET
def live_stats(request, slug):
    """
    Текущ брой присъстващи в JSON вид.

    Страницата за check-in извиква този адрес на всеки няколко секунди — така
    се постига проследяване на присъстващите в реално време без нужда от
    постоянна връзка (WebSocket), която заданието не изисква.
    """
    event = get_managed_event(request.user, Event, slug=slug)
    return JsonResponse(event_live_stats(event))


@role_required(Role.ORGANIZER)
def attendee_list(request, slug):
    """Списък с влезлите участници и дневник на сканиранията."""
    event = get_managed_event(request.user, Event, slug=slug)

    checkins = (
        CheckIn.objects.filter(event=event)
        .select_related("ticket", "ticket__ticket_type", "operator", "ticket__registration")
        .order_by("-checked_in_at")
    )

    logs = (
        ScanLog.objects.filter(event=event)
        .select_related("ticket", "operator")
        .order_by("-created_at")[:100]
    )

    result_filter = request.GET.get("result", "").strip()
    if result_filter in ScanResult.values:
        logs = (
            ScanLog.objects.filter(event=event, result=result_filter)
            .select_related("ticket", "operator")
            .order_by("-created_at")[:100]
        )

    return render(
        request,
        "checkin/attendee_list.html",
        {
            "event": event,
            "checkins": checkins,
            "logs": logs,
            "results": ScanResult.choices,
            "result_filter": result_filter,
            "stats": event_live_stats(event),
        },
    )
