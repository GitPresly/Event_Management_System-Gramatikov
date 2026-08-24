"""Форми на модул „Събития“."""
from django import forms
from django.forms import inlineformset_factory

from accounts.forms import BootstrapFormMixin
from events.models import Event, ProgramItem, TicketType, Venue


class DateTimeLocalInput(forms.DateTimeInput):
    """Поле за дата и час, използващо native HTML5 контрола."""

    input_type = "datetime-local"

    def format_value(self, value):
        # HTML5 контролата очаква формат ГГГГ-ММ-ДДTЧЧ:ММ
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return value.strftime("%Y-%m-%dT%H:%M")


class VenueForm(BootstrapFormMixin, forms.ModelForm):
    """Създаване и редакция на локация."""

    class Meta:
        model = Venue
        fields = ("name", "address", "city", "capacity", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class EventForm(BootstrapFormMixin, forms.ModelForm):
    """
    Създаване и редакция на събитие.

    Организаторът не избира сам кой е организаторът на събитието — той се
    задава автоматично от изгледа, за да не може да припише събитие на друг.
    """

    class Meta:
        model = Event
        fields = (
            "title",
            "description",
            "venue",
            "capacity",
            "starts_at",
            "ends_at",
            "registration_deadline",
            "status",
            "cover_image",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
            "starts_at": DateTimeLocalInput(),
            "ends_at": DateTimeLocalInput(),
            "registration_deadline": DateTimeLocalInput(),
        }

    def clean_capacity(self):
        """
        Броят места не може да падне под вече продадените билети.

        Без тази проверка организаторът би могъл да намали капацитета и да
        създаде събитие с повече продадени билети, отколкото места.
        """
        capacity = self.cleaned_data["capacity"]
        if self.instance.pk:
            sold = self.instance.tickets_sold
            if capacity < sold:
                raise forms.ValidationError(
                    f"Броят места не може да е под вече заетите {sold} места."
                )
        return capacity


class TicketTypeForm(BootstrapFormMixin, forms.ModelForm):
    """Форма за отделен билетен тип."""

    class Meta:
        model = TicketType
        fields = (
            "name",
            "description",
            "price",
            "quota",
            "sales_start",
            "sales_end",
            "is_active",
        )
        widgets = {
            "sales_start": DateTimeLocalInput(),
            "sales_end": DateTimeLocalInput(),
            # min и step се задават и на самото поле, за да не може браузърът
            # изобщо да изпрати отрицателна цена или количество. Проверката на
            # сървъра по-долу остава задължителна — HTML атрибутите се заобикалят
            # лесно и не са мярка за сигурност.
            "price": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
            "quota": forms.NumberInput(attrs={"min": "1", "step": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # PositiveIntegerField.formfield() задава min_value=0 и презаписва
        # атрибута от Meta.widgets, затова долната граница се налага тук.
        self.fields["quota"].min_value = 1
        self.fields["quota"].widget.attrs["min"] = "1"

    def clean_price(self):
        """Цената не може да бъде отрицателна."""
        price = self.cleaned_data.get("price")
        if price is not None and price < 0:
            raise forms.ValidationError(
                "Цената не може да бъде отрицателна. Въведете 0 за безплатен билет."
            )
        return price

    def clean_quota(self):
        quota = self.cleaned_data["quota"]
        if self.instance.pk:
            sold = self.instance.sold_count
            if quota < sold:
                raise forms.ValidationError(
                    f"Квотата не може да е под вече продадените {sold} билета."
                )
        return quota


class ProgramItemForm(BootstrapFormMixin, forms.ModelForm):
    """Форма за отделна точка от програмата."""

    class Meta:
        model = ProgramItem
        fields = ("title", "speaker", "starts_at", "ends_at", "description", "order")
        widgets = {
            "starts_at": DateTimeLocalInput(),
            "ends_at": DateTimeLocalInput(),
            "description": forms.Textarea(attrs={"rows": 2}),
        }


# Наборите от форми позволяват билетните типове и програмата да се редактират
# на същата страница като събитието.
TicketTypeFormSet = inlineformset_factory(
    Event, TicketType, form=TicketTypeForm, extra=1, can_delete=True
)

ProgramItemFormSet = inlineformset_factory(
    Event, ProgramItem, form=ProgramItemForm, extra=1, can_delete=True
)


class EventFilterForm(forms.Form):
    """Филтър за публичния каталог със събития."""

    q = forms.CharField(
        label="Търсене",
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Заглавие или описание"}
        ),
    )
    city = forms.ChoiceField(
        label="Град",
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    period = forms.ChoiceField(
        label="Период",
        required=False,
        choices=[
            ("upcoming", "Предстоящи"),
            ("past", "Минали"),
            ("all", "Всички"),
        ],
        initial="upcoming",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cities = (
            Venue.objects.order_by("city")
            .values_list("city", flat=True)
            .distinct()
        )
        self.fields["city"].choices = [("", "Всички градове")] + [(c, c) for c in cities]
