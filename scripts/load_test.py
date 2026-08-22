"""
Скрипт за проверка на поведението при натоварване.

Симулира голям брой участници, които се опитват да се регистрират за едно и
също събитие едновременно, и проверява дали системата продава повече билети,
отколкото има свободни места.

Работи срещу истински работещ сървър през HTTP — за разлика от автоматичните
тестове, които извикват логиката пряко. Така се проверява целият път: уеб
сървър → изглед → бизнес логика → база данни.

Употреба:
    # 1) В отделен прозорец стартирайте сървъра:
    #    python manage.py runserver
    # 2) След това:
    python scripts/load_test.py
    python scripts/load_test.py --users 100 --capacity 25
    python scripts/load_test.py --url http://127.0.0.1:8000 --users 50

Скриптът сам създава събитие за теста и потребителите към него, а накрая
изчиства създадените данни (освен ако не е подадено --keep).
"""
import argparse
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import django
import requests

# Проектът трябва да е достъпен за импортиране, за да се подготвят данните.
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.utils import timezone  # noqa: E402

from accounts.models import Role, User  # noqa: E402
from events.models import Event, EventStatus, TicketType, Venue  # noqa: E402
from registration.models import Ticket, TicketStatus  # noqa: E402

LOAD_TEST_PREFIX = "loadtest"
PASSWORD = "loadtest1234"
OCCUPYING = [TicketStatus.RESERVED, TicketStatus.VALID, TicketStatus.USED]


# ---------------------------------------------------------------------------
# Подготовка на данните
# ---------------------------------------------------------------------------

def prepare(user_count: int, capacity: int):
    """Създава събитие с ограничен капацитет и потребители, които ще го щурмуват."""
    organizer, created = User.objects.get_or_create(
        username=f"{LOAD_TEST_PREFIX}_organizer",
        defaults={
            "email": f"{LOAD_TEST_PREFIX}_org@example.com",
            "first_name": "Тест",
            "last_name": "Организатор",
            "role": Role.ORGANIZER,
        },
    )
    if created:
        organizer.set_password(PASSWORD)
        organizer.save()

    venue, _ = Venue.objects.get_or_create(
        name="Зала за тест на натоварване",
        city="Стара Загора",
        defaults={"address": "ул. „Тестова“ 1", "capacity": 10000},
    )

    starts_at = timezone.now() + timezone.timedelta(days=30)
    event = Event.objects.create(
        organizer=organizer,
        venue=venue,
        title=f"Тест на натоварване {timezone.now():%Y-%m-%d %H:%M:%S}",
        description="Събитие, създадено автоматично за проверка при натоварване.",
        starts_at=starts_at,
        ends_at=starts_at + timezone.timedelta(hours=4),
        capacity=capacity,
        status=EventStatus.PUBLISHED,
    )

    ticket_type = TicketType.objects.create(
        event=event,
        name="Стандартен",
        price=Decimal("25.00"),
        quota=capacity * 10,  # квотата нарочно не ограничава — водещ е капацитетът
    )

    users = []
    for index in range(user_count):
        username = f"{LOAD_TEST_PREFIX}_user{index:04d}"
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": f"{username}@example.com", "role": Role.PARTICIPANT},
        )
        if created:
            user.set_password(PASSWORD)
            user.save()
        users.append(username)

    return event, ticket_type, users


def cleanup(event):
    """Изтрива данните, създадени от този тест."""
    Ticket.objects.filter(event=event).delete()
    event.registrations.all().delete()
    event.ticket_types.all().delete()
    event.delete()
    User.objects.filter(username__startswith=LOAD_TEST_PREFIX).delete()
    Venue.objects.filter(name="Зала за тест на натоварване").delete()


# ---------------------------------------------------------------------------
# Една заявка
# ---------------------------------------------------------------------------

def register_once(base_url, username, event, ticket_type):
    """
    Изпълнява пълния път на един участник: вход → изпращане на регистрация.

    Връща (успех, код на отговора, продължителност в секунди).
    """
    session = requests.Session()
    started = time.perf_counter()

    try:
        # 1) Вход — нужен е CSRF маркер от страницата за вход.
        login_url = f"{base_url}/accounts/login/"
        page = session.get(login_url, timeout=30)
        csrf = session.cookies.get("csrftoken")

        response = session.post(
            login_url,
            data={
                "username": username,
                "password": PASSWORD,
                "csrfmiddlewaretoken": csrf,
            },
            headers={"Referer": login_url},
            timeout=30,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return False, f"вход {response.status_code}", time.perf_counter() - started

        # 2) Заявка за билет.
        register_url = f"{base_url}/registration/event/{event.slug}/register/"
        page = session.get(register_url, timeout=30)
        csrf = session.cookies.get("csrftoken")

        response = session.post(
            register_url,
            data={
                "csrfmiddlewaretoken": csrf,
                f"qty_{ticket_type.id}": "1",
                "contact_name": username,
                "contact_email": f"{username}@example.com",
                "contact_phone": "",
            },
            headers={"Referer": register_url},
            timeout=30,
            allow_redirects=False,
        )

        elapsed = time.perf_counter() - started

        # Успешната резервация пренасочва към страницата за плащане.
        if response.status_code == 302 and "/payment/" in response.headers.get("Location", ""):
            return True, "резервиран", elapsed

        return False, "отказан (няма места)", elapsed

    except requests.RequestException as exc:
        return False, f"грешка: {type(exc).__name__}", time.perf_counter() - started


# ---------------------------------------------------------------------------
# Основна процедура
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Проверка на системата при едновременни регистрации."
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Адрес на сървъра.")
    parser.add_argument("--users", type=int, default=60, help="Брой едновременни участници.")
    parser.add_argument("--capacity", type=int, default=20, help="Брой места на събитието.")
    parser.add_argument(
        "--workers", type=int, default=0, help="Брой нишки (0 = колкото са участниците)."
    )
    parser.add_argument(
        "--keep", action="store_true", help="Запазва създадените данни след теста."
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    workers = args.workers or args.users

    print("=" * 72)
    print("ПРОВЕРКА НА СИСТЕМАТА ПРИ ЕДНОВРЕМЕННИ РЕГИСТРАЦИИ")
    print("=" * 72)
    print(f"Сървър:                {base_url}")
    print(f"Едновременни участници: {args.users}")
    print(f"Свободни места:         {args.capacity}")
    print(f"Паралелни нишки:        {workers}")
    print()

    # Проверка дали сървърът работи, преди да се създават данни.
    try:
        requests.get(base_url, timeout=10)
    except requests.RequestException:
        print(f"ГРЕШКА: сървърът на {base_url} не отговаря.")
        print("Стартирайте го с:  python manage.py runserver")
        return 1

    print("Подготовка на данните...")
    event, ticket_type, users = prepare(args.users, args.capacity)
    print(f"Създадено събитие: „{event.title}“ ({event.capacity} места)")
    print()

    print(f"Изпращане на {args.users} едновременни заявки...")
    started = time.perf_counter()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(register_once, base_url, username, event, ticket_type)
            for username in users
        ]
        results = [future.result() for future in futures]

    total_time = time.perf_counter() - started

    # -- Резултати ----------------------------------------------------------
    successes = [r for r in results if r[0]]
    failures = [r for r in results if not r[0]]
    durations = sorted(r[2] for r in results)

    sold = Ticket.objects.filter(event=event, status__in=OCCUPYING).count()

    print()
    print("-" * 72)
    print("РЕЗУЛТАТИ")
    print("-" * 72)
    print(f"Общо време:                 {total_time:.2f} с")
    print(f"Пропускателна способност:   {len(results) / total_time:.1f} заявки/с")
    print()
    print(f"Успешни резервации:         {len(successes)}")
    print(f"Отказани заявки:            {len(failures)}")
    print()
    print("Време за отговор (вход + регистрация):")
    print(f"  минимално:                {durations[0]:.3f} с")
    print(f"  медиана:                  {statistics.median(durations):.3f} с")
    print(f"  95-и персентил:           {durations[int(len(durations) * 0.95) - 1]:.3f} с")
    print(f"  максимално:               {durations[-1]:.3f} с")
    print()

    # -- Основната проверка -------------------------------------------------
    print("-" * 72)
    print("ПРОВЕРКА ЗА СВРЪХПРОДАЖБА")
    print("-" * 72)
    print(f"Места на събитието:         {event.capacity}")
    print(f"Резервирани билети:         {sold}")
    print()

    if sold > event.capacity:
        print(f"ПРОВАЛ: продадени са {sold - event.capacity} билета в повече от капацитета!")
        exit_code = 1
    elif sold < event.capacity and len(users) > event.capacity:
        print(f"ВНИМАНИЕ: продадени са само {sold} от {event.capacity} възможни места.")
        exit_code = 0
    else:
        print("УСПЕХ: продадени са точно толкова билети, колкото са местата.")
        print("Заключването на реда на събитието е предотвратило свръхпродажбата.")
        exit_code = 0

    # Разбивка на причините за отказ.
    if failures:
        reasons = {}
        for _, reason, _ in failures:
            reasons[reason] = reasons.get(reason, 0) + 1
        print()
        print("Причини за отказ:")
        for reason, count in sorted(reasons.items(), key=lambda item: -item[1]):
            print(f"  {reason}: {count}")

    print()
    if args.keep:
        print(f"Данните са запазени. Събитие: {base_url}{event.get_absolute_url()}")
    else:
        print("Изчистване на тестовите данни...")
        cleanup(event)
        print("Готово.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
