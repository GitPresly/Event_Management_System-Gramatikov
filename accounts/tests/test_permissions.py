"""
Тестове на ролево базирания достъп.

Проверява, че всяка роля вижда точно това, което ѝ се полага, и че един
организатор не може да достигне до чуждо събитие.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User
from registration.models import PaymentMethod
from registration.services import TicketRequest, reserve_tickets, simulate_payment
from registration.tests.factories import (
    make_event,
    make_ticket_type,
    make_user,
    make_venue,
)


class AccessMatrixTests(TestCase):
    """Кой до кои страници има достъп."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("admin_t", Role.ADMIN)
        cls.organizer = make_user("organizer_t", Role.ORGANIZER)
        cls.other_organizer = make_user("organizer2_t", Role.ORGANIZER)
        cls.participant = make_user("participant_t")

        cls.venue = make_venue(capacity=500)
        cls.event = make_event(cls.organizer, venue=cls.venue, capacity=50)
        make_ticket_type(cls.event)

    def _get(self, url, user=None):
        if user:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get(url)

    # -- Публични страници ---------------------------------------------------

    def test_event_list_is_public(self):
        self.assertEqual(self._get(reverse("events:event_list")).status_code, 200)

    def test_event_detail_is_public(self):
        url = reverse("events:event_detail", kwargs={"slug": self.event.slug})
        self.assertEqual(self._get(url).status_code, 200)

    # -- Служебни страници ---------------------------------------------------

    def test_participant_cannot_open_management_pages(self):
        protected = [
            reverse("events:event_manage_list"),
            reverse("events:event_create"),
            reverse("events:venue_list"),
            reverse("checkin:event_list"),
            reverse("reports:overview"),
        ]
        for url in protected:
            with self.subTest(url=url):
                self.assertEqual(self._get(url, self.participant).status_code, 403)

    def test_organizer_can_open_management_pages(self):
        allowed = [
            reverse("events:event_manage_list"),
            reverse("events:event_create"),
            reverse("events:venue_list"),
            reverse("checkin:event_list"),
            reverse("reports:overview"),
        ]
        for url in allowed:
            with self.subTest(url=url):
                self.assertEqual(self._get(url, self.organizer).status_code, 200)

    def test_admin_can_open_everything(self):
        urls = [
            reverse("events:event_manage_list"),
            reverse("accounts:user_list"),
            reverse("reports:overview"),
            reverse("checkin:event_list"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self._get(url, self.admin).status_code, 200)

    def test_only_admin_manages_users(self):
        url = reverse("accounts:user_list")
        self.assertEqual(self._get(url, self.participant).status_code, 403)
        self.assertEqual(self._get(url, self.organizer).status_code, 403)
        self.assertEqual(self._get(url, self.admin).status_code, 200)

    def test_anonymous_is_redirected_to_login(self):
        response = self._get(reverse("events:event_manage_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)


class OwnershipIsolationTests(TestCase):
    """Изолация на данните между отделните организатори."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner_t", Role.ORGANIZER)
        cls.intruder = make_user("intruder_t", Role.ORGANIZER)
        cls.admin = make_user("admin_iso", Role.ADMIN)

        cls.venue = make_venue(capacity=500)
        cls.event = make_event(cls.owner, venue=cls.venue, capacity=50, title="Чуждо събитие")
        make_ticket_type(cls.event)

    def test_organizer_cannot_open_foreign_event_management(self):
        self.client.force_login(self.intruder)
        urls = [
            reverse("events:event_manage", kwargs={"slug": self.event.slug}),
            reverse("events:event_edit", kwargs={"slug": self.event.slug}),
            reverse("reports:event_report", kwargs={"slug": self.event.slug}),
            reverse("checkin:scan_console", kwargs={"slug": self.event.slug}),
            reverse("checkin:attendee_list", kwargs={"slug": self.event.slug}),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_owner_can_open_own_event_management(self):
        self.client.force_login(self.owner)
        url = reverse("events:event_manage", kwargs={"slug": self.event.slug})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_admin_can_open_any_event_management(self):
        self.client.force_login(self.admin)
        url = reverse("events:event_manage", kwargs={"slug": self.event.slug})
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_organizer_list_shows_only_own_events(self):
        self.client.force_login(self.intruder)
        response = self.client.get(reverse("events:event_manage_list"))
        self.assertNotContains(response, "Чуждо събитие")

    def test_organizer_cannot_scan_for_foreign_event(self):
        self.client.force_login(self.intruder)
        url = reverse("checkin:scan", kwargs={"slug": self.event.slug})
        response = self.client.post(
            url, data='{"payload": "EMS1:test"}', content_type="application/json"
        )
        self.assertEqual(response.status_code, 404)


class RegistrationPrivacyTests(TestCase):
    """Чужди заявки и билети не са достъпни."""

    @classmethod
    def setUpTestData(cls):
        cls.organizer = make_user("org_priv", Role.ORGANIZER)
        cls.buyer = make_user("buyer_priv")
        cls.stranger = make_user("stranger_priv")

        cls.event = make_event(cls.organizer, capacity=50)
        ticket_type = make_ticket_type(cls.event)
        cls.registration = reserve_tickets(
            cls.buyer, cls.event, [TicketRequest(ticket_type.id, 1)]
        )
        simulate_payment(cls.registration, PaymentMethod.CARD)
        cls.ticket = cls.registration.tickets.first()

    def test_owner_sees_own_registration(self):
        self.client.force_login(self.buyer)
        url = reverse(
            "registration:registration_detail", kwargs={"code": self.registration.code}
        )
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_stranger_cannot_see_foreign_registration(self):
        self.client.force_login(self.stranger)
        url = reverse(
            "registration:registration_detail", kwargs={"code": self.registration.code}
        )
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_stranger_cannot_see_foreign_ticket_qr(self):
        self.client.force_login(self.stranger)
        url = reverse("registration:ticket_qr", kwargs={"uuid": self.ticket.uuid})
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_event_organizer_can_see_registration_for_own_event(self):
        """Организаторът вижда заявките за своето събитие — нужно е за check-in."""
        self.client.force_login(self.organizer)
        url = reverse(
            "registration:registration_detail", kwargs={"code": self.registration.code}
        )
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_stranger_cannot_cancel_foreign_registration(self):
        self.client.force_login(self.stranger)
        url = reverse("registration:cancel", kwargs={"code": self.registration.code})
        self.assertEqual(self.client.post(url).status_code, 404)


class SignUpTests(TestCase):
    """Самостоятелна регистрация на нов потребител."""

    def test_signup_creates_participant_only(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "newuser",
                "first_name": "Нов",
                "last_name": "Потребител",
                "email": "newuser@example.com",
                "phone": "+359888123456",
                "password1": "SilnaParola123",
                "password2": "SilnaParola123",
            },
        )
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username="newuser")
        self.assertEqual(user.role, Role.PARTICIPANT)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_signup_cannot_set_privileged_role(self):
        """Дори ролята да бъде подадена във формата, тя се пренебрегва."""
        self.client.post(
            reverse("accounts:signup"),
            {
                "username": "sneaky",
                "first_name": "Опит",
                "last_name": "Заобикаляне",
                "email": "sneaky@example.com",
                "role": Role.ADMIN,
                "password1": "SilnaParola123",
                "password2": "SilnaParola123",
            },
        )
        self.assertEqual(User.objects.get(username="sneaky").role, Role.PARTICIPANT)

    def test_duplicate_email_is_rejected(self):
        make_user("existing", email="taken@example.com")
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "username": "another",
                "first_name": "Друг",
                "last_name": "Човек",
                "email": "taken@example.com",
                "password1": "SilnaParola123",
                "password2": "SilnaParola123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="another").exists())
