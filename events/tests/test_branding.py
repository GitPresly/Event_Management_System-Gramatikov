"""
Тестове на оформлението на страницата: заглавие в раздела и икона на сайта.

Дребни на пръв поглед, но лесно се чупят при разместване на шаблона base.html,
а се забелязват трудно — затова са покрити тук.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from registration.tests.factories import make_event, make_ticket_type, make_user

SITE_NAME = "Уеб система за управление на събития"


class PageTitleTests(TestCase):
    """Заглавието на всяка страница завършва с името на системата."""

    @classmethod
    def setUpTestData(cls):
        cls.organizer = make_user("org_title", Role.ORGANIZER)
        cls.event = make_event(cls.organizer, capacity=20, title="Тестов концерт")
        make_ticket_type(cls.event)

    def _title(self, response) -> str:
        html = response.content.decode("utf-8")
        start = html.index("<title>") + len("<title>")
        return html[start : html.index("</title>")].strip()

    def test_event_list_title(self):
        title = self._title(self.client.get(reverse("events:event_list")))
        self.assertEqual(title, f"Събития — {SITE_NAME}")

    def test_event_detail_title_starts_with_event_name(self):
        title = self._title(
            self.client.get(
                reverse("events:event_detail", kwargs={"slug": self.event.slug})
            )
        )
        self.assertEqual(title, f"Тестов концерт — {SITE_NAME}")

    def test_login_page_title(self):
        title = self._title(self.client.get(reverse("accounts:login")))
        self.assertEqual(title, f"Вход — {SITE_NAME}")

    def test_every_page_title_carries_the_site_name(self):
        pages = [
            reverse("events:event_list"),
            reverse("accounts:login"),
            reverse("accounts:signup"),
            reverse("events:event_detail", kwargs={"slug": self.event.slug}),
        ]
        for url in pages:
            with self.subTest(url=url):
                self.assertIn(SITE_NAME, self._title(self.client.get(url)))


class FaviconTests(TestCase):
    """Иконата на сайта е обявена в страницата и се отдава на /favicon.ico."""

    def test_head_declares_svg_and_png_icons(self):
        html = self.client.get(reverse("events:event_list")).content.decode("utf-8")

        self.assertIn('rel="icon"', html)
        self.assertIn("favicon.svg", html)
        self.assertIn("favicon-32.png", html)
        self.assertIn("favicon-16.png", html)
        self.assertIn("apple-touch-icon.png", html)
        self.assertIn('name="theme-color"', html)

    def test_root_favicon_redirects_to_static_file(self):
        """
        Браузърите искат /favicon.ico от корена, независимо от <link> тага.

        Без това пренасочване всяко зареждане на страница оставя 404 в дневника.
        """
        response = self.client.get("/favicon.ico")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("favicon.ico"))
        self.assertIn("static", response["Location"])

    def test_icon_files_exist_on_disk(self):
        from django.conf import settings

        base = settings.BASE_DIR / "static"
        expected = [
            base / "favicon.ico",
            base / "img" / "favicon.svg",
            base / "img" / "favicon-16.png",
            base / "img" / "favicon-32.png",
            base / "img" / "apple-touch-icon.png",
        ]
        for path in expected:
            with self.subTest(path=path.name):
                self.assertTrue(path.exists(), f"Липсва файл: {path}")
                self.assertGreater(path.stat().st_size, 0)
