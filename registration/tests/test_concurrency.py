"""
Тестове за поведението при едновременни регистрации.

Това е проверката на нефункционалното изискване „обработка на голям брой
едновременни регистрации“ и на критерия „надеждност при натоварване“.

Използва се TransactionTestCase, а не обикновеният TestCase: TestCase обвива
всеки тест в една транзакция, която не се записва, и другите нишки не биха
видели данните. TransactionTestCase работи с реални транзакции — точно както
в работеща система.
"""
from concurrent.futures import ThreadPoolExecutor

from django.db import connections
from django.test import TransactionTestCase

from accounts.models import Role
from registration.models import Ticket, TicketStatus
from registration.services import RegistrationError, TicketRequest, reserve_tickets
from registration.tests.factories import (
    make_event,
    make_ticket_type,
    make_user,
    make_venue,
)

OCCUPYING = [TicketStatus.RESERVED, TicketStatus.VALID, TicketStatus.USED]


class ConcurrentRegistrationTests(TransactionTestCase):
    """Паралелни заявки за едни и същи места."""

    # Всяка нишка получава собствена връзка към базата — трябва да се затвори.
    reset_sequences = True

    def _reserve_in_thread(self, user, event, ticket_type, quantity=1):
        """
        Изпълнява една резервация в отделна нишка.

        Връща (успех, съобщение). Връзката към базата се затваря изрично, за да
        не остане отворена след приключване на нишката.
        """
        try:
            reserve_tickets(user, event, [TicketRequest(ticket_type.id, quantity)])
            return True, ""
        except RegistrationError as exc:
            return False, str(exc)
        finally:
            connections.close_all()

    def test_no_overselling_when_many_users_race_for_last_seats(self):
        """
        30 участника едновременно се борят за 10 места.

        Очакван резултат: продадени са точно 10 билета — нито един повече.
        Без заключването в reserve_tickets тук биха се получили повече от 10.
        """
        organizer = make_user("org_race", Role.ORGANIZER)
        venue = make_venue(capacity=1000)
        event = make_event(organizer, venue=venue, capacity=10, title="Надпревара")
        ticket_type = make_ticket_type(event, quota=100)

        users = [make_user(f"racer{i:02d}") for i in range(30)]

        with ThreadPoolExecutor(max_workers=30) as pool:
            futures = [
                pool.submit(self._reserve_in_thread, user, event, ticket_type)
                for user in users
            ]
            results = [future.result() for future in futures]

        successes = sum(1 for ok, _ in results if ok)
        sold = Ticket.objects.filter(event=event, status__in=OCCUPYING).count()

        self.assertEqual(sold, 10, f"Продадени са {sold} билета при капацитет 10.")
        self.assertEqual(successes, 10)
        self.assertEqual(sum(1 for ok, _ in results if not ok), 20)

    def test_quota_is_respected_under_concurrency(self):
        """
        Квотата на билетния тип също се спазва при паралелни заявки.

        Капацитетът на събитието е висок, така че ограничението идва изцяло от
        квотата на билетния тип.
        """
        organizer = make_user("org_quota", Role.ORGANIZER)
        venue = make_venue(name="Зала за квоти", capacity=1000)
        event = make_event(organizer, venue=venue, capacity=200, title="Квоти")
        vip = make_ticket_type(event, "VIP", "200.00", quota=5)

        users = [make_user(f"vip{i:02d}") for i in range(20)]

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [
                pool.submit(self._reserve_in_thread, user, event, vip) for user in users
            ]
            results = [future.result() for future in futures]

        sold = Ticket.objects.filter(ticket_type=vip, status__in=OCCUPYING).count()
        self.assertEqual(sold, 5, f"Продадени са {sold} VIP билета при квота 5.")
        self.assertEqual(sum(1 for ok, _ in results if ok), 5)

    def test_multi_ticket_requests_do_not_oversell(self):
        """
        Заявки за по няколко билета не могат да надхвърлят капацитета.

        12 участника заявяват по 3 билета за събитие с 20 места. Резервацията е
        „всичко или нищо“, затова минават най-много 6 заявки (6 × 3 = 18),
        а общият брой билети никога не надхвърля 20.
        """
        organizer = make_user("org_multi", Role.ORGANIZER)
        venue = make_venue(name="Зала за групи", capacity=1000)
        event = make_event(organizer, venue=venue, capacity=20, title="Групови заявки")
        ticket_type = make_ticket_type(event, quota=100)

        users = [make_user(f"group{i:02d}") for i in range(12)]

        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [
                pool.submit(self._reserve_in_thread, user, event, ticket_type, 3)
                for user in users
            ]
            results = [future.result() for future in futures]

        sold = Ticket.objects.filter(event=event, status__in=OCCUPYING).count()
        successes = sum(1 for ok, _ in results if ok)

        self.assertLessEqual(sold, 20, f"Свръхпродажба: {sold} билета при 20 места.")
        self.assertEqual(sold, successes * 3)
        # Всяка успяла заявка получава пълните си 3 билета — няма частични.
        self.assertGreaterEqual(successes, 6)

    def test_repeated_requests_from_same_user_are_counted(self):
        """
        Един и същ потребител, изпратил няколко паралелни заявки (напр. чрез
        многократно натискане на бутона), не може да заобиколи капацитета.
        """
        organizer = make_user("org_repeat", Role.ORGANIZER)
        venue = make_venue(name="Зала за повторения", capacity=1000)
        event = make_event(organizer, venue=venue, capacity=4, title="Двоен клик")
        ticket_type = make_ticket_type(event, quota=100)
        user = make_user("clicker")

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [
                pool.submit(self._reserve_in_thread, user, event, ticket_type)
                for _ in range(10)
            ]
            [future.result() for future in futures]

        sold = Ticket.objects.filter(event=event, status__in=OCCUPYING).count()
        self.assertEqual(sold, 4)
