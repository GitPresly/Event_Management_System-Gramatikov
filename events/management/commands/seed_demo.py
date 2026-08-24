"""
Команда за зареждане на демонстрационни данни.

Създава пълен набор от свързани данни — потребители и в трите роли, локации,
събития в различни състояния, билетни типове, програма, платени и неплатени
регистрации и извършени check-in-и. Това позволява системата да се демонстрира
и оцени веднага след инсталация, без ръчно въвеждане.

Употреба:
    python manage.py seed_demo
    python manage.py seed_demo --reset      (изтрива предишните демо данни)
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, User
from checkin.models import CheckIn, ScanLog
from events.models import Event, EventStatus, ProgramItem, TicketType, Venue
from notifications.models import EmailLog
from registration.models import (
    Payment,
    PaymentMethod,
    PaymentStatus,
    Registration,
    RegistrationStatus,
    Ticket,
    TicketStatus,
)
from registration.qr import attach_qr_to_ticket

# Паролата е една и съща за всички демо профили, за да е удобно при преглед.
DEMO_PASSWORD = "demo1234"

VENUES = [
    ("Зала „Тракия“", "бул. „Цар Симеон Велики“ 158", "Стара Загора", 400),
    ("Конферентен център НДК", "пл. „България“ 1", "София", 1200),
    ("Културен дом „Възраждане“", "ул. „Ген. Столетов“ 12", "Пловдив", 250),
    ("Аула на ПГКНМА", "ул. „Августа Траяна“ 44", "Стара Загора", 120),
]

PARTICIPANT_NAMES = [
    ("Ана", "Петрова"), ("Борис", "Иванов"), ("Виктория", "Димитрова"),
    ("Георги", "Стоянов"), ("Даниела", "Колева"), ("Емил", "Николов"),
    ("Живка", "Тодорова"), ("Захари", "Маринов"), ("Ивана", "Георгиева"),
    ("Калоян", "Ангелов"), ("Лидия", "Василева"), ("Мартин", "Христов"),
    ("Надежда", "Илиева"), ("Огнян", "Панайотов"), ("Петя", "Райкова"),
    ("Радослав", "Симеонов"), ("Силвия", "Атанасова"), ("Тодор", "Желязков"),
    ("Христина", "Динева"), ("Явор", "Костадинов"),
]

EVENT_BLUEPRINTS = [
    {
        "title": "Национална конференция по уеб технологии 2026",
        "description": (
            "Двудневна конференция за разработчици, посветена на съвременните "
            "уеб технологии, архитектурни подходи и добри практики. Лекции от "
            "водещи специалисти, практически работилници и панелна дискусия."
        ),
        "venue": 1,
        "days_offset": 21,
        "duration_hours": 8,
        "capacity": 300,
        "status": EventStatus.PUBLISHED,
        "ticket_types": [
            ("Стандартен", "Достъп до всички лекции", "120.00", 200),
            ("VIP", "Достъп до лекции, обяд и вечеря с лекторите", "260.00", 50),
            ("Студентски", "Намалена цена срещу представяне на студентска карта", "45.00", 60),
        ],
        "program": [
            ("Регистрация и кафе", "", 0, 1),
            ("Откриване и въвеждаща лекция", "проф. Иван Петров", 1, 2),
            ("Архитектура на съвременните уеб приложения", "инж. Мария Стоянова", 2, 3),
            ("Обедна почивка", "", 3, 4),
            ("Практическа работилница: REST и GraphQL", "Димитър Колев", 4, 6),
            ("Панелна дискусия и закриване", "", 6, 8),
        ],
    },
    {
        "title": "Работилница „Django за начинаещи“",
        "description": (
            "Еднодневна практическа работилница, в която участниците изграждат "
            "своето първо уеб приложение с Django — от модела на данните до "
            "работещ интерфейс. Необходим е собствен лаптоп."
        ),
        "venue": 3,
        "days_offset": 10,
        "duration_hours": 6,
        "capacity": 40,
        "status": EventStatus.PUBLISHED,
        "ticket_types": [
            ("Пълна такса", "Включва материали и обяд", "80.00", 30),
            ("Ученически", "За ученици от професионални гимназии", "20.00", 15),
        ],
        "program": [
            ("Въведение и настройка на средата", "Ивайло Граматиков", 0, 1),
            ("Модели и миграции", "Ивайло Граматиков", 1, 3),
            ("Изгледи, шаблони и форми", "Ивайло Граматиков", 3, 5),
            ("Самостоятелна задача и обратна връзка", "", 5, 6),
        ],
    },
    {
        "title": "Концерт „Класика под звездите“",
        "description": (
            "Открит концерт на симфоничния оркестър с програма от произведения "
            "на Моцарт, Бетовен и Чайковски. При лошо време концертът се "
            "премества в закрита зала."
        ),
        "venue": 0,
        "days_offset": 35,
        "duration_hours": 3,
        "capacity": 380,
        "status": EventStatus.PUBLISHED,
        "ticket_types": [
            ("Партер", "Места на първите редове", "45.00", 150),
            ("Балкон", "Места на балкона", "28.00", 200),
            ("Деца до 12 г.", "Безплатен вход с придружител", "0.00", 30),
        ],
        "program": [
            ("Отваряне на вратите", "", 0, 1),
            ("Първо отделение", "Симфоничен оркестър", 1, 2),
            ("Антракт", "", 2, 2),
            ("Второ отделение", "Симфоничен оркестър", 2, 3),
        ],
    },
    {
        "title": "Хакатон „Смарт град Стара Загора“",
        "description": (
            "48-часов хакатон, в който отбори разработват решения за градската "
            "среда — транспорт, енергийна ефективност и обществени услуги. "
            "Осигурени са ментори, храна и награден фонд."
        ),
        "venue": 3,
        "days_offset": -14,
        "duration_hours": 10,
        "capacity": 100,
        "status": EventStatus.FINISHED,
        "ticket_types": [
            ("Участник", "Участие в отбор", "0.00", 80),
            ("Ментор", "Менторска подкрепа на отборите", "0.00", 20),
        ],
        "program": [
            ("Откриване и представяне на казусите", "", 0, 2),
            ("Работа по проектите", "", 2, 8),
            ("Представяне пред жури", "", 8, 10),
        ],
    },
    {
        "title": "Семинар „Киберсигурност в образованието“",
        "description": (
            "Полудневен семинар за учители и IT администратори относно защитата "
            "на училищните информационни системи и личните данни на учениците."
        ),
        "venue": 2,
        "days_offset": -35,
        "duration_hours": 4,
        "capacity": 150,
        "status": EventStatus.FINISHED,
        "ticket_types": [
            ("Стандартен", "Включва сертификат за участие", "60.00", 120),
            ("Група (от 3 души)", "Отстъпка при групова заявка", "45.00", 30),
        ],
        "program": [
            ("Актуални заплахи", "инж. Николай Тодоров", 0, 1),
            ("Защита на личните данни", "адв. Елена Маринова", 1, 2),
            ("Практически насоки", "", 2, 4),
        ],
    },
    {
        "title": "Изложение „Роботика и изкуствен интелект“",
        "description": (
            "Изложение с демонстрации на роботизирани системи и приложения на "
            "изкуствения интелект. Подходящо за ученици, студенти и специалисти."
        ),
        "venue": 1,
        "days_offset": 60,
        "duration_hours": 9,
        "capacity": 500,
        "status": EventStatus.DRAFT,
        "ticket_types": [
            ("Дневен вход", "Достъп за един ден", "15.00", 400),
            ("Семеен пакет", "До 4 души", "40.00", 100),
        ],
        "program": [
            ("Отваряне на изложението", "", 0, 1),
            ("Демонстрации на роботи", "", 1, 5),
            ("Лекция за приложения на ИИ", "д-р Стефан Георгиев", 5, 6),
            ("Свободно разглеждане", "", 6, 9),
        ],
    },
]


class Command(BaseCommand):
    help = "Зарежда демонстрационни данни в системата."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Изтрива всички съществуващи данни преди зареждането.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(20260915)  # един и същ резултат при всяко пускане

        if options["reset"]:
            self.stdout.write("Изтриване на съществуващите данни...")
            ScanLog.objects.all().delete()
            CheckIn.objects.all().delete()
            EmailLog.objects.all().delete()
            Payment.objects.all().delete()
            Ticket.objects.all().delete()
            Registration.objects.all().delete()
            ProgramItem.objects.all().delete()
            TicketType.objects.all().delete()
            Event.objects.all().delete()
            Venue.objects.all().delete()
            User.objects.exclude(is_superuser=True).delete()

        users = self._create_users()
        venues = self._create_venues()
        events = self._create_events(users["organizers"], venues)
        self._create_registrations(events, users["participants"])

        self._print_summary(users)

    # -- Потребители ---------------------------------------------------------

    def _create_users(self) -> dict:
        self.stdout.write("Създаване на потребители...")

        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@events.local",
                "first_name": "Системен",
                "last_name": "Администратор",
                "role": Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin.set_password(DEMO_PASSWORD)
            admin.save()

        organizers = []
        organizer_data = [
            ("organizer1", "Ивайло", "Граматиков", "ПГКНМА „Проф. Минко Балкански“"),
            ("organizer2", "Мария", "Стоянова", "Културен център Стара Загора"),
            ("organizer3", "Николай", "Тодоров", "IT Академия"),
        ]
        for username, first, last, org in organizer_data:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@events.local",
                    "first_name": first,
                    "last_name": last,
                    "role": Role.ORGANIZER,
                    "organization": org,
                    "phone": f"+3598{random.randint(10000000, 99999999)}",
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            organizers.append(user)

        participants = []
        for index, (first, last) in enumerate(PARTICIPANT_NAMES, start=1):
            username = f"user{index:02d}"
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.com",
                    "first_name": first,
                    "last_name": last,
                    "role": Role.PARTICIPANT,
                    "phone": f"+3598{random.randint(10000000, 99999999)}",
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            participants.append(user)

        return {"admin": admin, "organizers": organizers, "participants": participants}

    # -- Локации -------------------------------------------------------------

    def _create_venues(self) -> list:
        self.stdout.write("Създаване на локации...")
        venues = []
        for name, address, city, capacity in VENUES:
            venue, _ = Venue.objects.get_or_create(
                name=name,
                city=city,
                defaults={"address": address, "capacity": capacity},
            )
            venues.append(venue)
        return venues

    # -- Събития -------------------------------------------------------------

    def _create_events(self, organizers, venues) -> list:
        self.stdout.write("Създаване на събития...")
        now = timezone.now()
        events = []

        for index, blueprint in enumerate(EVENT_BLUEPRINTS):
            starts_at = (now + timedelta(days=blueprint["days_offset"])).replace(
                hour=random.choice([9, 10, 14, 18]), minute=0, second=0, microsecond=0
            )
            ends_at = starts_at + timedelta(hours=blueprint["duration_hours"])

            event, created = Event.objects.get_or_create(
                title=blueprint["title"],
                defaults={
                    "organizer": organizers[index % len(organizers)],
                    "venue": venues[blueprint["venue"]],
                    "description": blueprint["description"],
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "registration_deadline": starts_at - timedelta(hours=2),
                    "capacity": blueprint["capacity"],
                    "status": blueprint["status"],
                },
            )

            if created:
                for name, description, price, quota in blueprint["ticket_types"]:
                    TicketType.objects.create(
                        event=event,
                        name=name,
                        description=description,
                        price=Decimal(price),
                        quota=quota,
                    )

                for order, (title, speaker, start_h, end_h) in enumerate(
                    blueprint["program"], start=1
                ):
                    item_start = starts_at + timedelta(hours=start_h)
                    item_end = starts_at + timedelta(hours=max(end_h, start_h + 1))
                    ProgramItem.objects.create(
                        event=event,
                        title=title,
                        speaker=speaker,
                        starts_at=item_start,
                        ends_at=min(item_end, ends_at),
                        order=order,
                    )

            events.append(event)

        return events

    # -- Регистрации, плащания и check-in -----------------------------------

    def _create_registrations(self, events, participants) -> None:
        self.stdout.write("Създаване на регистрации, плащания и check-in-и...")
        now = timezone.now()

        for event in events:
            if event.status == EventStatus.DRAFT:
                continue  # за чернови не се приемат регистрации

            if event.registrations.exists():
                continue  # данните вече са заредени

            ticket_types = list(event.ticket_types.all())
            if not ticket_types:
                continue

            # Колко участници се регистрират за това събитие.
            target = min(len(participants), max(6, event.capacity // 12))
            chosen = random.sample(participants, target)

            for participant in chosen:
                ticket_type = random.choices(
                    ticket_types, weights=[max(t.quota, 1) for t in ticket_types], k=1
                )[0]
                quantity = random.choices([1, 1, 1, 2, 2, 3], k=1)[0]

                # 15% от заявките остават неплатени — така отчетите показват и
                # реалистичен дял чакащи плащане.
                is_paid = random.random() > 0.15

                created_at = event.starts_at - timedelta(
                    days=random.randint(1, 20), hours=random.randint(0, 23)
                )

                registration = Registration.objects.create(
                    user=participant,
                    event=event,
                    status=RegistrationStatus.PAID if is_paid else RegistrationStatus.PENDING,
                    contact_name=participant.display_name(),
                    contact_email=participant.email,
                    contact_phone=participant.phone,
                    total_amount=ticket_type.price * quantity,
                )
                # auto_now_add не позволява директно задаване при create.
                Registration.objects.filter(pk=registration.pk).update(
                    created_at=created_at,
                    paid_at=created_at + timedelta(minutes=5) if is_paid else None,
                )

                tickets = []
                for _ in range(quantity):
                    tickets.append(
                        Ticket(
                            registration=registration,
                            ticket_type=ticket_type,
                            event=event,
                            holder_name=participant.display_name(),
                            holder_email=participant.email,
                            price_paid=ticket_type.price,
                            status=TicketStatus.VALID if is_paid else TicketStatus.RESERVED,
                        )
                    )
                Ticket.objects.bulk_create(tickets)

                if is_paid:
                    Payment.objects.create(
                        registration=registration,
                        amount=registration.total_amount,
                        method=random.choice(PaymentMethod.values),
                        transaction_ref=Payment.generate_reference(),
                        status=PaymentStatus.SUCCESS,
                    )
                    # QR кодовете се генерират само за платените билети.
                    for ticket in registration.tickets.all():
                        attach_qr_to_ticket(ticket)

            # За вече започналите/приключилите събития отбелязваме и влизания.
            if event.starts_at < now:
                self._simulate_checkins(event)

    def _simulate_checkins(self, event) -> None:
        """Отбелязва част от валидните билети като използвани (реални влизания)."""
        operator = event.organizer
        valid_tickets = list(event.tickets.filter(status=TicketStatus.VALID))

        # Около 80% посещаемост — останалите са неявили се (no-show).
        attending = random.sample(valid_tickets, int(len(valid_tickets) * 0.8))

        for ticket in attending:
            checkin = CheckIn.objects.create(
                ticket=ticket, event=event, operator=operator
            )
            # Влизанията се разпределят в час преди началото на събитието.
            moment = event.starts_at - timedelta(minutes=random.randint(1, 60))
            CheckIn.objects.filter(pk=checkin.pk).update(checked_in_at=moment)

            ticket.status = TicketStatus.USED
            ticket.save(update_fields=["status"])

    # -- Обобщение -----------------------------------------------------------

    def _print_summary(self, users) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Демонстрационните данни са заредени."))
        self.stdout.write("")
        self.stdout.write("Статистика:")
        self.stdout.write(f"  Потребители:  {User.objects.count()}")
        self.stdout.write(f"  Локации:      {Venue.objects.count()}")
        self.stdout.write(f"  Събития:      {Event.objects.count()}")
        self.stdout.write(f"  Регистрации:  {Registration.objects.count()}")
        self.stdout.write(f"  Билети:       {Ticket.objects.count()}")
        self.stdout.write(f"  Check-in-и:   {CheckIn.objects.count()}")
        self.stdout.write("")
        self.stdout.write("Демо профили (парола за всички: " + DEMO_PASSWORD + "):")
        self.stdout.write("  admin       — Администратор")
        self.stdout.write("  organizer1  — Организатор (Ивайло Граматиков)")
        self.stdout.write("  organizer2  — Организатор (Мария Стоянова)")
        self.stdout.write("  user01      — Участник")
        self.stdout.write("")
