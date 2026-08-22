"""
Изгледи на приложение accounts.

Обхваща: вход/изход (върху Django Auth), самостоятелна регистрация на участници,
профил, начално табло според ролята и управление на потребителите от администратор.
"""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.forms import LoginForm, ProfileForm, SignUpForm, UserManagementForm
from accounts.models import Role, User
from accounts.permissions import role_required
from events.models import Event, EventStatus
from registration.models import Registration, RegistrationStatus, Ticket, TicketStatus


class EMSLoginView(LoginView):
    """Вход в системата, използващ стандартния механизъм на Django Auth."""

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class EMSLogoutView(LogoutView):
    """Изход от системата."""

    next_page = "events:event_list"


def signup(request):
    """Самостоятелна регистрация — създава профил с роля „Участник“."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(
                request,
                f"Добре дошли, {user.display_name()}! Профилът Ви е създаден успешно.",
            )
            return redirect("accounts:dashboard")
    else:
        form = SignUpForm()

    return render(request, "accounts/signup.html", {"form": form})


@login_required
def dashboard(request):
    """
    Начално табло след вход. Съдържанието зависи от ролята на потребителя.
    """
    user = request.user
    now = timezone.now()
    context = {"now": now}

    if user.is_participant and not user.is_admin_role:
        # Участник — вижда собствените си регистрации и билети.
        registrations = (
            Registration.objects.filter(user=user)
            .select_related("event", "event__venue")
            .prefetch_related("tickets")
            .order_by("-created_at")
        )
        context["registrations"] = registrations[:10]
        context["upcoming_tickets"] = (
            Ticket.objects.filter(
                registration__user=user,
                status=TicketStatus.VALID,
                event__starts_at__gte=now,
            )
            .select_related("event", "ticket_type", "event__venue")
            .order_by("event__starts_at")[:5]
        )
        context["stats"] = {
            "registrations": registrations.count(),
            "tickets": Ticket.objects.filter(
                registration__user=user,
                status__in=[TicketStatus.VALID, TicketStatus.USED],
            ).count(),
            "attended": Ticket.objects.filter(
                registration__user=user, status=TicketStatus.USED
            ).count(),
        }
        return render(request, "accounts/dashboard_participant.html", context)

    # Организатор и администратор — виждат обобщение на управляваните събития.
    events = Event.objects.all()
    if user.is_organizer and not user.is_admin_role:
        events = events.filter(organizer=user)

    events = events.select_related("venue").annotate(
        sold=Count(
            "tickets",
            filter=Q(tickets__status__in=[TicketStatus.VALID, TicketStatus.USED]),
            distinct=True,
        ),
        attended=Count(
            "tickets", filter=Q(tickets__status=TicketStatus.USED), distinct=True
        ),
    )

    revenue = (
        Registration.objects.filter(
            event__in=Event.objects.filter(pk__in=events.values("pk")),
            status=RegistrationStatus.PAID,
        ).aggregate(total=Sum("total_amount"))["total"]
        or 0
    )

    context.update(
        {
            "upcoming_events": events.filter(starts_at__gte=now).order_by("starts_at")[:6],
            "past_events": events.filter(starts_at__lt=now).order_by("-starts_at")[:6],
            "stats": {
                "total_events": events.count(),
                "published": events.filter(status=EventStatus.PUBLISHED).count(),
                "drafts": events.filter(status=EventStatus.DRAFT).count(),
                "revenue": revenue,
            },
        }
    )
    return render(request, "accounts/dashboard_organizer.html", context)


@login_required
def profile(request):
    """Преглед и редакция на собствения профил."""
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Профилът е обновен успешно.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    return render(request, "accounts/profile.html", {"form": form})


@role_required(Role.ADMIN)
def user_list(request):
    """Списък с всички потребители — достъпен само за администратор."""
    users = User.objects.all().order_by("role", "username")

    role_filter = request.GET.get("role", "").strip()
    if role_filter in Role.values:
        users = users.filter(role=role_filter)

    search = request.GET.get("q", "").strip()
    if search:
        users = users.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
        )

    return render(
        request,
        "accounts/user_list.html",
        {
            "users": users,
            "roles": Role.choices,
            "role_filter": role_filter,
            "search": search,
            "counts": {
                "admins": User.objects.filter(role=Role.ADMIN).count(),
                "organizers": User.objects.filter(role=Role.ORGANIZER).count(),
                "participants": User.objects.filter(role=Role.PARTICIPANT).count(),
            },
        },
    )


@role_required(Role.ADMIN)
def user_edit(request, pk):
    """Редакция на потребител (включително смяна на ролята) от администратор."""
    user_obj = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = UserManagementForm(request.POST, instance=user_obj)
        if form.is_valid():
            # Предпазна мярка: администраторът не може да си отнеме сам достъпа.
            if user_obj == request.user and not form.cleaned_data["is_active"]:
                messages.error(request, "Не можете да деактивирате собствения си профил.")
            else:
                form.save()
                messages.success(request, f"Профилът на {user_obj.username} е обновен.")
                return redirect("accounts:user_list")
    else:
        form = UserManagementForm(instance=user_obj)

    return render(
        request, "accounts/user_edit.html", {"form": form, "user_obj": user_obj}
    )
