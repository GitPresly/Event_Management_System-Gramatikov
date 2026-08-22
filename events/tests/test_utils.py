"""Тестове на транслитерацията и съставянето на адресни идентификатори."""
from django.test import TestCase

from accounts.models import Role
from events.utils import slugify_bg, transliterate
from registration.tests.factories import make_event, make_user


class TransliterationTests(TestCase):
    """Преобразуване на кирилица на латиница."""

    def test_basic_words(self):
        cases = [
            ("София", "Sofiya"),
            ("Стара Загора", "Stara Zagora"),
            ("Пловдив", "Plovdiv"),
            ("Конференция", "Konferentsiya"),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(transliterate(source), expected)

    def test_multiletter_replacements_keep_capitalisation(self):
        """Буквите с многознаков заместител не стават изцяло главни."""
        self.assertEqual(transliterate("Живот"), "Zhivot")
        self.assertEqual(transliterate("Щастие"), "Shtastie")
        self.assertEqual(transliterate("Чудо"), "Chudo")

    def test_latin_and_digits_are_untouched(self):
        self.assertEqual(transliterate("Django 5.2"), "Django 5.2")
        self.assertEqual(transliterate("Web 2026"), "Web 2026")

    def test_mixed_text(self):
        self.assertEqual(
            transliterate("Работилница Django"), "Rabotilnitsa Django"
        )


class SlugifyTests(TestCase):
    """Адресните идентификатори остават четими и на кирилица."""

    def test_cyrillic_title_produces_readable_slug(self):
        self.assertEqual(
            slugify_bg("Концерт „Класика под звездите“"),
            "kontsert-klasika-pod-zvezdite",
        )

    def test_mixed_title(self):
        self.assertEqual(
            slugify_bg("Работилница „Django за начинаещи“"),
            "rabotilnitsa-django-za-nachinaeshti",
        )

    def test_empty_input_falls_back(self):
        self.assertEqual(slugify_bg(""), "event")
        self.assertEqual(slugify_bg("!!!"), "event")


class EventSlugTests(TestCase):
    """Слуговете на събитията се съставят по същия начин."""

    def test_event_slug_is_readable(self):
        organizer = make_user("org_slug", Role.ORGANIZER)
        event = make_event(organizer, title="Национална конференция 2026")
        self.assertEqual(event.slug, "natsionalna-konferentsiya-2026")

    def test_duplicate_titles_get_distinct_slugs(self):
        organizer = make_user("org_slug2", Role.ORGANIZER)
        first = make_event(organizer, title="Семинар по сигурност")
        second = make_event(organizer, title="Семинар по сигурност")

        self.assertEqual(first.slug, "seminar-po-sigurnost")
        self.assertEqual(second.slug, "seminar-po-sigurnost-2")
