"""Форми на модул „Регистрация“."""
from django import forms

from accounts.forms import BootstrapFormMixin
from registration.models import PaymentMethod
from registration.services import TicketRequest


class TicketSelectionForm(BootstrapFormMixin, forms.Form):
    """
    Форма за избор на билети за конкретно събитие.

    Полетата се създават динамично — по едно числово поле за всеки активен
    билетен тип на събитието, с горна граница според останалата наличност.
    """

    contact_name = forms.CharField(label="Име за контакт", max_length=200)
    contact_email = forms.EmailField(label="Имейл за контакт")
    contact_phone = forms.CharField(label="Телефон", max_length=20, required=False)

    def __init__(self, *args, event=None, ticket_types=None, max_total=10, **kwargs):
        super().__init__(*args, **kwargs)
        self.event = event
        self.ticket_types = list(ticket_types or [])
        self.max_total = max_total

        for ticket_type in self.ticket_types:
            remaining = ticket_type.remaining
            field_name = f"qty_{ticket_type.id}"
            self.fields[field_name] = forms.IntegerField(
                label=ticket_type.name,
                min_value=0,
                max_value=min(remaining, max_total) if remaining else 0,
                initial=0,
                required=False,
                widget=forms.NumberInput(
                    attrs={
                        "class": "form-control",
                        "min": 0,
                        "max": min(remaining, max_total) if remaining else 0,
                        "value": 0,
                    }
                ),
            )
            if remaining == 0 or not ticket_type.is_on_sale:
                self.fields[field_name].widget.attrs["disabled"] = "disabled"

    def clean(self):
        cleaned = super().clean()

        total = 0
        for ticket_type in self.ticket_types:
            quantity = cleaned.get(f"qty_{ticket_type.id}") or 0
            total += quantity

        if total == 0:
            raise forms.ValidationError("Изберете поне един билет.")
        if total > self.max_total:
            raise forms.ValidationError(
                f"Не може да заявите повече от {self.max_total} билета наведнъж."
            )

        cleaned["_total_quantity"] = total
        return cleaned

    def get_ticket_requests(self) -> list[TicketRequest]:
        """Превръща попълнената форма в списък от заявки към слоя с логиката."""
        requests = []
        for ticket_type in self.ticket_types:
            quantity = self.cleaned_data.get(f"qty_{ticket_type.id}") or 0
            if quantity > 0:
                requests.append(
                    TicketRequest(ticket_type_id=ticket_type.id, quantity=quantity)
                )
        return requests

    def quantity_fields(self):
        """Полетата за количество, сдвоени със съответния билетен тип (за шаблона)."""
        for ticket_type in self.ticket_types:
            yield ticket_type, self[f"qty_{ticket_type.id}"]


class PaymentForm(BootstrapFormMixin, forms.Form):
    """
    Форма за симулираното плащане.

    Не се събират реални картови данни — заданието изисква само симулация,
    а събирането на такива данни без сертифициран процесор би било и опасно.
    """

    method = forms.ChoiceField(
        label="Начин на плащане",
        choices=PaymentMethod.choices,
        initial=PaymentMethod.CARD,
        widget=forms.RadioSelect,
    )
    confirm = forms.BooleanField(
        label="Потвърждавам, че данните за поръчката са верни",
        required=True,
    )
