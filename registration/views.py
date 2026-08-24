"""
Изгледи на модул „Регистрация“.

Потокът е: избор на билети → заявка (чака плащане) → симулация на плащане →
издадени билети с QR код.
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from events.models import Event
from registration.forms import PaymentForm, TicketSelectionForm
from registration.models import Registration, RegistrationStatus, Ticket, TicketStatus
from registration.qr import build_payload, render_qr_png
from registration.services import (
    RegistrationError,
    cancel_registration,
    reserve_tickets,
    simulate_payment,
)


def _user_can_see_registration(user, registration: Registration) -> bool:
    """Заявката е видима за нейния автор, за организатора на събитието и за администратора."""
    if user.is_admin_role:
        return True
    if registration.user_id == user.id:
        return True
    return registration.event.organizer_id == user.id


@login_required
def register_for_event(request, slug):
    """Избор на билети за събитие и създаване на заявка."""
    event = get_object_or_404(
        Event.objects.visible_to(request.user).select_related("venue"), slug=slug
    )

    if not event.is_registration_open:
        messages.error(
            request,
            event.registration_closed_reason or "Регистрацията за това събитие е затворена.",
        )
        return redirect("events:event_detail", slug=event.slug)

    ticket_types = [tt for tt in event.ticket_types.filter(is_active=True) if tt.is_on_sale]
    if not ticket_types:
        messages.error(request, "В момента няма билети в продажба за това събитие.")
        return redirect("events:event_detail", slug=event.slug)

    max_total = min(settings.MAX_TICKETS_PER_REGISTRATION, event.seats_available)

    if request.method == "POST":
        form = TicketSelectionForm(
            request.POST, event=event, ticket_types=ticket_types, max_total=max_total
        )
        if form.is_valid():
            try:
                registration = reserve_tickets(
                    user=request.user,
                    event=event,
                    requests=form.get_ticket_requests(),
                    contact={
                        "contact_name": form.cleaned_data["contact_name"],
                        "contact_email": form.cleaned_data["contact_email"],
                        "contact_phone": form.cleaned_data.get("contact_phone", ""),
                    },
                )
            except RegistrationError as exc:
                # Съобщенията от слоя с логиката са предназначени за потребителя.
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Заявка {registration.code} е създадена. Остава да я платите.",
                )
                return redirect("registration:payment", code=registration.code)
    else:
        form = TicketSelectionForm(
            event=event,
            ticket_types=ticket_types,
            max_total=max_total,
            initial={
                "contact_name": request.user.display_name(),
                "contact_email": request.user.email,
                "contact_phone": request.user.phone,
            },
        )

    return render(
        request,
        "registration/register.html",
        {"event": event, "form": form, "max_total": max_total},
    )


@login_required
def payment(request, code):
    """Страница за симулираното плащане на заявка."""
    registration = get_object_or_404(
        Registration.objects.select_related("event", "event__venue"), code=code
    )

    if registration.user_id != request.user.id and not request.user.is_admin_role:
        raise Http404("Заявката не е намерена.")

    if registration.status == RegistrationStatus.PAID:
        messages.info(request, "Тази заявка вече е платена.")
        return redirect("registration:registration_detail", code=registration.code)

    if registration.status == RegistrationStatus.CANCELLED:
        messages.error(request, "Тази заявка е отказана.")
        return redirect("registration:my_registrations")

    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            try:
                simulate_payment(registration, method=form.cleaned_data["method"])
            except RegistrationError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    "Плащането е успешно. Билетите Ви са издадени и изпратени по имейл.",
                )
                return redirect("registration:registration_detail", code=registration.code)
    else:
        form = PaymentForm()

    return render(
        request,
        "registration/payment.html",
        {
            "registration": registration,
            "form": form,
            "tickets": registration.tickets.select_related("ticket_type"),
        },
    )


@login_required
def registration_detail(request, code):
    """Детайли на заявка заедно с издадените билети и техните QR кодове."""
    registration = get_object_or_404(
        Registration.objects.select_related("event", "event__venue", "user"), code=code
    )

    if not _user_can_see_registration(request.user, registration):
        raise Http404("Заявката не е намерена.")

    return render(
        request,
        "registration/registration_detail.html",
        {
            "registration": registration,
            "tickets": registration.tickets.select_related("ticket_type").order_by(
                "issued_at"
            ),
            "payment": getattr(registration, "payment", None),
        },
    )


@login_required
def my_registrations(request):
    """Списък със собствените заявки на участника."""
    registrations = (
        Registration.objects.filter(user=request.user)
        .select_related("event", "event__venue")
        .prefetch_related("tickets")
        .order_by("-created_at")
    )

    status_filter = request.GET.get("status", "").strip()
    if status_filter in RegistrationStatus.values:
        registrations = registrations.filter(status=status_filter)

    return render(
        request,
        "registration/my_registrations.html",
        {
            "registrations": registrations,
            "statuses": RegistrationStatus.choices,
            "status_filter": status_filter,
        },
    )


@login_required
def my_tickets(request):
    """Всички валидни и използвани билети на участника."""
    tickets = (
        Ticket.objects.filter(registration__user=request.user)
        .exclude(status=TicketStatus.CANCELLED)
        .select_related("event", "event__venue", "ticket_type", "registration")
        .order_by("-event__starts_at")
    )
    return render(request, "registration/my_tickets.html", {"tickets": tickets})


@login_required
def ticket_detail(request, uuid):
    """
    Страница на отделен билет с голям QR код — това е екранът, който се показва
    на входа при check-in.
    """
    ticket = get_object_or_404(
        Ticket.objects.select_related(
            "event", "event__venue", "ticket_type", "registration", "registration__user"
        ),
        uuid=uuid,
    )

    if not _user_can_see_registration(request.user, ticket.registration):
        raise Http404("Билетът не е намерен.")

    return render(
        request,
        "registration/ticket_detail.html",
        {"ticket": ticket, "checkin": getattr(ticket, "checkin", None)},
    )


@login_required
def ticket_qr(request, uuid):
    """
    Отдава QR изображението на билета.

    С параметър ?download=1 файлът се предлага за изтегляне вместо да се показва
    в страницата — това обслужва бутона „Изтегли QR кода“.

    Ако файлът още не е генериран (напр. билетът е само резервиран), кодът се
    изчертава в движение, но само за валидни билети.
    """
    ticket = get_object_or_404(
        Ticket.objects.select_related("registration", "event"), uuid=uuid
    )

    if not _user_can_see_registration(request.user, ticket.registration):
        raise Http404("Билетът не е намерен.")

    if ticket.status == TicketStatus.CANCELLED:
        raise Http404("Билетът е анулиран.")

    as_attachment = request.GET.get("download") == "1"
    filename = f"bilet-{ticket.short_code}.png"

    if ticket.qr_image:
        return FileResponse(
            ticket.qr_image.open("rb"),
            content_type="image/png",
            as_attachment=as_attachment,
            filename=filename,
        )

    png = render_qr_png(build_payload(ticket))
    response = HttpResponse(png, content_type="image/png")
    if as_attachment:
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def cancel(request, code):
    """Отказ на заявка от участника или от администратор."""
    if request.method != "POST":
        return redirect("registration:registration_detail", code=code)

    registration = get_object_or_404(Registration, code=code)

    if registration.user_id != request.user.id and not request.user.is_admin_role:
        raise Http404("Заявката не е намерена.")

    try:
        cancel_registration(registration, by_user=request.user)
    except RegistrationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request, f"Заявка {registration.code} е отказана и местата са освободени."
        )

    return redirect("registration:my_registrations")
