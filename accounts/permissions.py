"""
Ролево базиран контрол на достъпа.

Заданието изисква три роли с различни права. За да не се повтаря една и съща
проверка във всеки изглед, тук са събрани декоратор (за функционални изгледи)
и mixin класове (за класови изгледи).

Правило за собствеността: администраторът вижда всичко, организаторът — само
собствените си събития, участникът — само собствените си регистрации.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from accounts.models import Role


def role_required(*roles):
    """
    Декоратор за функционални изгледи, който допуска само изброените роли.

    Пример:
        @role_required(Role.ORGANIZER, Role.ADMIN)
        def create_event(request): ...
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            # Администраторът има достъп навсякъде, независимо от списъка.
            if user.is_admin_role or user.role in roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied("Нямате права за достъп до тази страница.")

        return _wrapped

    return decorator


class RoleRequiredMixin:
    """
    Mixin за класови изгледи, който допуска само определени роли.

    Задава се чрез атрибута allowed_roles. Администраторът винаги преминава.
    """

    allowed_roles: tuple = ()

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (user.is_admin_role or user.role in self.allowed_roles):
            raise PermissionDenied("Нямате права за достъп до тази страница.")
        return super().dispatch(request, *args, **kwargs)


class OrganizerRequiredMixin(RoleRequiredMixin):
    """Достъп само за организатори (и администратори)."""

    allowed_roles = (Role.ORGANIZER,)


class AdminRequiredMixin(RoleRequiredMixin):
    """Достъп само за администратори."""

    allowed_roles = ()


class ParticipantRequiredMixin(RoleRequiredMixin):
    """Достъп само за участници (и администратори)."""

    allowed_roles = (Role.PARTICIPANT,)


def scope_events_for(user, queryset):
    """
    Ограничава подадения набор от събития според ролята на потребителя.

    Това е централното място за изолация на данните между организаторите —
    един организатор не трябва да вижда или променя чуждо събитие.
    """
    if user.is_admin_role:
        return queryset
    if user.is_organizer:
        return queryset.filter(organizer=user)
    return queryset.none()


def get_managed_event(user, model, **lookup):
    """
    Връща събитие, което потребителят има право да управлява, или 404.

    Използва се от изгледите за check-in и отчети, за да не се дублира
    проверката за собственост.
    """
    queryset = scope_events_for(user, model.objects.all())
    return get_object_or_404(queryset, **lookup)
