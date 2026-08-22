"""
Изгледи на модул „Събития“.

Публична част: каталог със събития и страница на събитие.
Служебна част (организатор/администратор): създаване, редакция, управление на
билетни типове и програма, локации.
"""
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.models import Role
from accounts.permissions import role_required, scope_events_for
from events.forms import (
    EventFilterForm,
    EventForm,
    ProgramItemFormSet,
    TicketTypeFormSet,
    VenueForm,
)
from events.models import Event, EventStatus, TicketType, Venue
from registration.models import TicketStatus


def event_list(request):
    """
    Публичен каталог със събития.

    Показва публикуваните събития; организаторът вижда допълнително и
    собствените си чернови, за да може да ги прегледа преди публикуване.
    """
    form = EventFilterForm(request.GET or None)
    events = (
        Event.objects.visible_to(request.user)
        .select_related("venue", "organizer")
        .annotate(
            sold=Count(
                "tickets",
                filter=Q(
                    tickets__status__in=[
                        TicketStatus.RESERVED,
                        TicketStatus.VALID,
                        TicketStatus.USED,
                    ]
                ),
                distinct=True,
            )
        )
    )

    period = "upcoming"
    if form.is_valid():
        query = form.cleaned_data.get("q")
        if query:
            events = events.filter(
                Q(title__icontains=query) | Q(description__icontains=query)
            )
        city = form.cleaned_data.get("city")
        if city:
            events = events.filter(venue__city=city)
        period = form.cleaned_data.get("period") or "upcoming"

    now = timezone.now()
    if period == "upcoming":
        events = events.filter(ends_at__gte=now).order_by("starts_at")
    elif period == "past":
        events = events.filter(ends_at__lt=now).order_by("-starts_at")
    else:
        events = events.order_by("-starts_at")

    return render(
        request,
        "events/event_list.html",
        {"events": events, "filter_form": form, "period": period},
    )


def event_detail(request, slug):
    """Страница на събитие — описание, програма, локация и билетни типове."""
    events = Event.objects.visible_to(request.user).select_related("venue", "organizer")
    event = get_object_or_404(
        events.prefetch_related("program_items", "ticket_types"), slug=slug
    )

    # Билетните типове с изчислена наличност — показват се в таблицата за избор.
    ticket_types = list(event.ticket_types.filter(is_active=True))

    # Дали текущият потребител вече има регистрация за това събитие.
    user_registrations = []
    if request.user.is_authenticated:
        user_registrations = list(
            event.registrations.filter(user=request.user)
            .prefetch_related("tickets")
            .order_by("-created_at")
        )

    can_manage = request.user.is_authenticated and (
        request.user.is_admin_role or event.organizer_id == request.user.id
    )

    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "ticket_types": ticket_types,
            "program_items": event.program_items.all(),
            "user_registrations": user_registrations,
            "can_manage": can_manage,
        },
    )


@role_required(Role.ORGANIZER)
def event_manage_list(request):
    """Списък със събитията, които потребителят управлява."""
    events = (
        scope_events_for(request.user, Event.objects.all())
        .select_related("venue")
        .annotate(
            sold=Count(
                "tickets",
                filter=Q(
                    tickets__status__in=[
                        TicketStatus.RESERVED,
                        TicketStatus.VALID,
                        TicketStatus.USED,
                    ]
                ),
                distinct=True,
            ),
            attended=Count(
                "tickets", filter=Q(tickets__status=TicketStatus.USED), distinct=True
            ),
        )
        .order_by("-starts_at")
    )

    status_filter = request.GET.get("status", "").strip()
    if status_filter in EventStatus.values:
        events = events.filter(status=status_filter)

    return render(
        request,
        "events/event_manage_list.html",
        {
            "events": events,
            "statuses": EventStatus.choices,
            "status_filter": status_filter,
        },
    )


@role_required(Role.ORGANIZER)
def event_create(request):
    """Създаване на ново събитие заедно с програма и билетни типове."""
    event = Event(organizer=request.user)

    if request.method == "POST":
        form = EventForm(request.POST, request.FILES, instance=event)
        ticket_formset = TicketTypeFormSet(request.POST, instance=event, prefix="tickets")
        program_formset = ProgramItemFormSet(request.POST, instance=event, prefix="program")

        if form.is_valid() and ticket_formset.is_valid() and program_formset.is_valid():
            with transaction.atomic():
                event = form.save(commit=False)
                event.organizer = request.user
                event.full_clean(exclude=["slug"])
                event.save()
                ticket_formset.instance = event
                ticket_formset.save()
                program_formset.instance = event
                program_formset.save()
            messages.success(request, f"Събитието „{event.title}“ е създадено успешно.")
            return redirect("events:event_manage", slug=event.slug)
    else:
        form = EventForm(instance=event)
        ticket_formset = TicketTypeFormSet(instance=event, prefix="tickets")
        program_formset = ProgramItemFormSet(instance=event, prefix="program")

    return render(
        request,
        "events/event_form.html",
        {
            "form": form,
            "ticket_formset": ticket_formset,
            "program_formset": program_formset,
            "is_create": True,
        },
    )


@role_required(Role.ORGANIZER)
def event_edit(request, slug):
    """Редакция на съществуващо събитие. Достъпна само за собственика му."""
    event = get_object_or_404(scope_events_for(request.user, Event.objects.all()), slug=slug)

    if request.method == "POST":
        form = EventForm(request.POST, request.FILES, instance=event)
        ticket_formset = TicketTypeFormSet(request.POST, instance=event, prefix="tickets")
        program_formset = ProgramItemFormSet(request.POST, instance=event, prefix="program")

        if form.is_valid() and ticket_formset.is_valid() and program_formset.is_valid():
            with transaction.atomic():
                event = form.save(commit=False)
                event.full_clean(exclude=["slug"])
                event.save()
                ticket_formset.save()
                program_formset.save()
            messages.success(request, "Промените са запазени.")
            return redirect("events:event_manage", slug=event.slug)
    else:
        form = EventForm(instance=event)
        ticket_formset = TicketTypeFormSet(instance=event, prefix="tickets")
        program_formset = ProgramItemFormSet(instance=event, prefix="program")

    return render(
        request,
        "events/event_form.html",
        {
            "form": form,
            "ticket_formset": ticket_formset,
            "program_formset": program_formset,
            "event": event,
            "is_create": False,
        },
    )


@role_required(Role.ORGANIZER)
def event_manage(request, slug):
    """Служебен изглед на едно събитие с обобщени показатели и бързи действия."""
    event = get_object_or_404(
        scope_events_for(request.user, Event.objects.all()).select_related("venue"),
        slug=slug,
    )

    ticket_types = event.ticket_types.annotate(
        sold=Count(
            "tickets",
            filter=Q(
                tickets__status__in=[
                    TicketStatus.RESERVED,
                    TicketStatus.VALID,
                    TicketStatus.USED,
                ]
            ),
        )
    ).order_by("price")

    return render(
        request,
        "events/event_manage.html",
        {
            "event": event,
            "ticket_types": ticket_types,
            "program_items": event.program_items.all(),
            "statuses": EventStatus.choices,
        },
    )


@role_required(Role.ORGANIZER)
def event_change_status(request, slug):
    """Смяна на статуса на събитие (публикуване, отмяна, приключване)."""
    if request.method != "POST":
        return redirect("events:event_manage", slug=slug)

    event = get_object_or_404(scope_events_for(request.user, Event.objects.all()), slug=slug)
    new_status = request.POST.get("status", "")

    if new_status not in EventStatus.values:
        messages.error(request, "Невалиден статус.")
        return redirect("events:event_manage", slug=event.slug)

    # Не се публикува събитие без нито един билетен тип — иначе никой не може
    # да се регистрира и публикуването е безсмислено.
    if new_status == EventStatus.PUBLISHED and not event.ticket_types.filter(
        is_active=True
    ).exists():
        messages.error(
            request,
            "За да публикувате събитието, добавете поне един активен билетен тип.",
        )
        return redirect("events:event_manage", slug=event.slug)

    event.status = new_status
    event.save(update_fields=["status", "updated_at"])
    messages.success(
        request, f"Статусът е променен на „{EventStatus(new_status).label}“."
    )
    return redirect("events:event_manage", slug=event.slug)


@role_required(Role.ORGANIZER)
def venue_list(request):
    """Списък с локациите."""
    venues = Venue.objects.annotate(event_count=Count("events")).order_by("city", "name")
    return render(request, "events/venue_list.html", {"venues": venues})


@role_required(Role.ORGANIZER)
def venue_create(request):
    """Създаване на нова локация."""
    if request.method == "POST":
        form = VenueForm(request.POST)
        if form.is_valid():
            venue = form.save()
            messages.success(request, f"Локацията „{venue}“ е добавена.")
            return redirect("events:venue_list")
    else:
        form = VenueForm()
    return render(request, "events/venue_form.html", {"form": form, "is_create": True})


@role_required(Role.ORGANIZER)
def venue_edit(request, pk):
    """Редакция на локация."""
    venue = get_object_or_404(Venue, pk=pk)
    if request.method == "POST":
        form = VenueForm(request.POST, instance=venue)
        if form.is_valid():
            form.save()
            messages.success(request, "Локацията е обновена.")
            return redirect("events:venue_list")
    else:
        form = VenueForm(instance=venue)
    return render(
        request, "events/venue_form.html", {"form": form, "venue": venue, "is_create": False}
    )
