"""
Помощни функции за създаване на данни в тестовете.

Събрани са на едно място, за да не се повтаря еднаква подготовка във всеки
тестов случай.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, TicketType, Venue


def make_user(username, role=Role.PARTICIPANT, **extra) -> User:
    """Създава потребител с посочената роля и парола „test1234“."""
    user = User.objects.create_user(
        username=username,
        email=extra.pop("email", f"{username}@example.com"),
        password=extra.pop("password", "test1234"),
        first_name=extra.pop("first_name", username.capitalize()),
        last_name=extra.pop("last_name", "Тестов"),
        role=role,
        **extra,
    )
    return user


def make_venue(name=None, city="Стара Загора", capacity=500) -> Venue:
    """
    Създава локация с уникално име.

    Моделът Venue има ограничение за уникалност на двойката (име, град), затова
    когато името не е зададено изрично, се добавя пореден номер — иначе всяко
    второ извикване в един и същи тест би се провалило.
    """
    if name is None:
        name = f"Тестова зала {Venue.objects.count() + 1}"
    return Venue.objects.create(
        name=name, address="ул. „Тестова“ 1", city=city, capacity=capacity
    )


def make_event(
    organizer,
    venue=None,
    capacity=100,
    status=EventStatus.PUBLISHED,
    starts_in_days=7,
    duration_hours=4,
    title="Тестово събитие",
) -> Event:
    """Създава събитие, което по подразбиране приема регистрации."""
    starts_at = timezone.now() + timedelta(days=starts_in_days)
    return Event.objects.create(
        organizer=organizer,
        venue=venue or make_venue(capacity=max(capacity, 500)),
        title=title,
        description="Описание на тестовото събитие.",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=duration_hours),
        capacity=capacity,
        status=status,
    )


def make_ticket_type(event, name="Стандартен", price="50.00", quota=100) -> TicketType:
    return TicketType.objects.create(
        event=event, name=name, price=Decimal(price), quota=quota
    )
