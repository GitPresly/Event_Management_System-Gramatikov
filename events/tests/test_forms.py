"""
Тестове на формите за билетни типове.

Проверяват най-вече, че отрицателна цена не може да бъде записана, и че
премахнатите редове от набора от форми не се записват.
"""
from decimal import Decimal

from django.test import TestCase

from accounts.models import Role
from events.forms import TicketTypeForm, TicketTypeFormSet
from events.models import TicketType
from registration.tests.factories import make_event, make_ticket_type, make_user


class TicketTypePriceTests(TestCase):
    """Цената не може да е отрицателна."""

    def setUp(self):
        self.organizer = make_user("org_price", Role.ORGANIZER)
        self.event = make_event(self.organizer, capacity=50)

    def _form(self, price, quota="10"):
        return TicketTypeForm(
            data={
                "name": "Стандартен",
                "description": "",
                "price": price,
                "quota": quota,
                "sales_start": "",
                "sales_end": "",
                "is_active": "on",
            }
        )

    def test_negative_price_is_rejected(self):
        form = self._form("-25.00")
        self.assertFalse(form.is_valid())
        self.assertIn("price", form.errors)
        self.assertIn("отрицателна", " ".join(form.errors["price"]))

    def test_small_negative_price_is_rejected(self):
        self.assertFalse(self._form("-0.01").is_valid())

    def test_zero_price_is_allowed(self):
        """Нулевата цена е валидна — така се задава безплатен билет."""
        form = self._form("0.00")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["price"], Decimal("0.00"))

    def test_positive_price_is_allowed(self):
        form = self._form("35.50")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["price"], Decimal("35.50"))

    def test_negative_quota_is_rejected(self):
        self.assertFalse(self._form("10.00", quota="-5").is_valid())

    def test_zero_quota_is_rejected(self):
        """Квота 0 е безсмислена — не може да се продаде нито един билет."""
        self.assertFalse(self._form("10.00", quota="0").is_valid())

    def test_widgets_expose_lower_bounds_to_the_browser(self):
        """Атрибутът min пречи на стрелките в браузъра да слязат под границата."""
        form = TicketTypeForm()
        self.assertEqual(form.fields["price"].widget.attrs["min"], "0")
        self.assertEqual(form.fields["price"].widget.attrs["step"], "0.01")
        # PositiveIntegerField иначе би задал min=0 — тук трябва да е 1.
        self.assertEqual(form.fields["quota"].widget.attrs["min"], "1")


class TicketTypeFormSetTests(TestCase):
    """Премахнатите редове не се записват."""

    def setUp(self):
        self.organizer = make_user("org_fs", Role.ORGANIZER)
        self.event = make_event(self.organizer, capacity=50)

    def _payload(self, rows, initial=0):
        data = {
            "tickets-TOTAL_FORMS": str(len(rows)),
            "tickets-INITIAL_FORMS": str(initial),
            "tickets-MIN_NUM_FORMS": "0",
            "tickets-MAX_NUM_FORMS": "1000",
        }
        for index, row in enumerate(rows):
            for key, value in row.items():
                data[f"tickets-{index}-{key}"] = value
        return data

    def test_row_marked_for_deletion_is_not_created(self):
        data = self._payload(
            [
                {"name": "Оставащ", "price": "20.00", "quota": "10", "is_active": "on"},
                {
                    "name": "Премахнат",
                    "price": "99.00",
                    "quota": "5",
                    "is_active": "on",
                    "DELETE": "on",
                },
            ]
        )
        formset = TicketTypeFormSet(data, instance=self.event, prefix="tickets")
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()

        names = list(
            TicketType.objects.filter(event=self.event).values_list("name", flat=True)
        )
        self.assertEqual(names, ["Оставащ"])

    def test_existing_row_marked_for_deletion_is_removed(self):
        existing = make_ticket_type(self.event, "За изтриване", "15.00", quota=10)

        data = self._payload(
            [
                {
                    "id": str(existing.pk),
                    "name": existing.name,
                    "price": "15.00",
                    "quota": "10",
                    "is_active": "on",
                    "DELETE": "on",
                }
            ],
            initial=1,
        )
        formset = TicketTypeFormSet(data, instance=self.event, prefix="tickets")
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()

        self.assertFalse(TicketType.objects.filter(pk=existing.pk).exists())

    def test_deleted_row_with_invalid_data_does_not_block_saving(self):
        """
        Премахнат ред с невалидни данни не бива да проваля формата.

        Това е важно за интерфейса: потребителят може да е въвел нещо грешно и
        после да е натиснал бутона за премахване — тогава редът просто се
        пренебрегва, вместо да блокира записа.
        """
        data = self._payload(
            [
                {"name": "Валиден", "price": "10.00", "quota": "5", "is_active": "on"},
                {
                    "name": "",
                    "price": "-500",
                    "quota": "-3",
                    "is_active": "on",
                    "DELETE": "on",
                },
            ]
        )
        formset = TicketTypeFormSet(data, instance=self.event, prefix="tickets")
        self.assertTrue(formset.is_valid(), formset.errors)
        formset.save()

        self.assertEqual(TicketType.objects.filter(event=self.event).count(), 1)
