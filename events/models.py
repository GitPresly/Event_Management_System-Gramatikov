"""
Модели на модул „Събития“.

Покрива изискванията от заданието:
  * създаване на събитие с програма, локация и брой места;
  * управление на билетни типове и цени.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from events.utils import slugify_bg


class EventStatus(models.TextChoices):
    """Жизнен цикъл на едно събитие."""

    DRAFT = "DRAFT", "Чернова"
    PUBLISHED = "PUBLISHED", "Публикувано"
    CANCELLED = "CANCELLED", "Отменено"
    FINISHED = "FINISHED", "Приключило"


class Venue(models.Model):
    """
    Локация, на която се провежда събитие.

    Изнесена е в отделен модел, защото един организатор обикновено използва
    едни и същи зали многократно — така данните не се преписват при всяко събитие.
    """

    name = models.CharField("Наименование", max_length=150)
    address = models.CharField("Адрес", max_length=255)
    city = models.CharField("Град", max_length=100, db_index=True)
    capacity = models.PositiveIntegerField(
        "Максимален капацитет",
        validators=[MinValueValidator(1)],
        help_text="Общ брой места, които залата побира.",
    )
    notes = models.TextField("Бележки", blank=True)

    class Meta:
        verbose_name = "Локация"
        verbose_name_plural = "Локации"
        ordering = ["city", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "city"], name="unique_venue_name_per_city"
            )
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.city}"


class EventQuerySet(models.QuerySet):
    """Често използвани филтри върху събития."""

    def published(self):
        return self.filter(status=EventStatus.PUBLISHED)

    def upcoming(self):
        return self.filter(starts_at__gte=timezone.now())

    def past(self):
        return self.filter(starts_at__lt=timezone.now())

    def visible_to(self, user):
        """
        Кои събития вижда даден потребител в каталога.

        Участниците и анонимните виждат само публикуваните; организаторът
        вижда и собствените си чернови; администраторът — всичко.
        """
        if not user.is_authenticated:
            return self.published()
        if user.is_admin_role:
            return self
        if user.is_organizer:
            return self.filter(models.Q(status=EventStatus.PUBLISHED) | models.Q(organizer=user))
        return self.published()


class Event(models.Model):
    """Събитие — централният обект в системата."""

    organizer = models.ForeignKey(
        "accounts.User",
        verbose_name="Организатор",
        on_delete=models.PROTECT,
        related_name="organized_events",
    )
    venue = models.ForeignKey(
        Venue,
        verbose_name="Локация",
        on_delete=models.PROTECT,
        related_name="events",
    )

    title = models.CharField("Заглавие", max_length=200)
    slug = models.SlugField("Адресен идентификатор", max_length=220, unique=True, blank=True)
    description = models.TextField("Описание")

    starts_at = models.DateTimeField("Начало", db_index=True)
    ends_at = models.DateTimeField("Край")
    registration_deadline = models.DateTimeField(
        "Краен срок за регистрация",
        null=True,
        blank=True,
        help_text="Ако не се попълни, регистрациите се приемат до началото на събитието.",
    )

    capacity = models.PositiveIntegerField(
        "Брой места",
        validators=[MinValueValidator(1)],
        help_text="Общият брой места за това събитие. Не може да бъде надхвърлен.",
    )

    status = models.CharField(
        "Статус",
        max_length=20,
        choices=EventStatus.choices,
        default=EventStatus.DRAFT,
        db_index=True,
    )
    cover_image = models.ImageField(
        "Изображение", upload_to="events/covers/", blank=True, null=True
    )

    created_at = models.DateTimeField("Създадено на", auto_now_add=True)
    updated_at = models.DateTimeField("Променено на", auto_now=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        verbose_name = "Събитие"
        verbose_name_plural = "Събития"
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["status", "starts_at"]),
            models.Index(fields=["organizer", "starts_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="event_ends_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity__gt=0), name="event_capacity_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    def _build_unique_slug(self) -> str:
        """Съставя уникален адресен идентификатор от заглавието."""
        base = slugify_bg(self.title)
        candidate = base
        counter = 2
        while Event.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def clean(self):
        """Проверки, които се изпълняват при валидиране на формата."""
        errors = {}
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "Краят на събитието трябва да е след началото."
        if self.registration_deadline and self.starts_at:
            if self.registration_deadline > self.starts_at:
                errors["registration_deadline"] = (
                    "Крайният срок за регистрация не може да е след началото на събитието."
                )
        if self.venue_id and self.capacity and self.capacity > self.venue.capacity:
            errors["capacity"] = (
                f"Броят места ({self.capacity}) надхвърля капацитета на локацията "
                f"({self.venue.capacity})."
            )
        if errors:
            raise ValidationError(errors)

    def get_absolute_url(self):
        return reverse("events:event_detail", kwargs={"slug": self.slug})

    # -- Изчислими показатели ----------------------------------------------

    @property
    def tickets_sold(self) -> int:
        """Брой заети места — резервирани, платени или вече използвани."""
        from registration.models import TicketStatus

        return self.tickets.filter(
            status__in=[TicketStatus.RESERVED, TicketStatus.VALID, TicketStatus.USED]
        ).count()

    @property
    def seats_available(self) -> int:
        return max(self.capacity - self.tickets_sold, 0)

    @property
    def checked_in_count(self) -> int:
        """Реален брой присъстващи, отчетени чрез check-in."""
        from registration.models import TicketStatus

        return self.tickets.filter(status=TicketStatus.USED).count()

    @property
    def occupancy_percent(self) -> float:
        """Процент запълване спрямо обявения брой места."""
        if not self.capacity:
            return 0.0
        return round(self.tickets_sold * 100 / self.capacity, 1)

    @property
    def is_sold_out(self) -> bool:
        return self.seats_available == 0

    @property
    def effective_deadline(self):
        """Краен момент, до който се приемат регистрации."""
        return self.registration_deadline or self.starts_at

    @property
    def is_registration_open(self) -> bool:
        """Дали в момента се приемат регистрации за това събитие."""
        return (
            self.status == EventStatus.PUBLISHED
            and timezone.now() <= self.effective_deadline
            and not self.is_sold_out
        )

    @property
    def registration_closed_reason(self) -> str:
        """Обяснение защо регистрацията не е възможна (за интерфейса)."""
        if self.status == EventStatus.CANCELLED:
            return "Събитието е отменено."
        if self.status == EventStatus.FINISHED:
            return "Събитието вече е приключило."
        if self.status != EventStatus.PUBLISHED:
            return "Събитието още не е публикувано."
        if self.is_sold_out:
            return "Всички места са изчерпани."
        if timezone.now() > self.effective_deadline:
            return "Крайният срок за регистрация е изтекъл."
        return ""

    @property
    def is_past(self) -> bool:
        return self.ends_at < timezone.now()

    @property
    def is_ongoing(self) -> bool:
        return self.starts_at <= timezone.now() <= self.ends_at


class ProgramItem(models.Model):
    """
    Точка от програмата на събитието (лекция, панел, почивка).

    Заданието изисква събитието да се създава „с програма“ — това е моделът,
    който я представя.
    """

    event = models.ForeignKey(
        Event, verbose_name="Събитие", on_delete=models.CASCADE, related_name="program_items"
    )
    title = models.CharField("Заглавие", max_length=200)
    speaker = models.CharField("Лектор / водещ", max_length=150, blank=True)
    starts_at = models.DateTimeField("Начало")
    ends_at = models.DateTimeField("Край")
    description = models.TextField("Описание", blank=True)
    order = models.PositiveIntegerField("Подредба", default=0)

    class Meta:
        verbose_name = "Точка от програмата"
        verbose_name_plural = "Програма"
        ordering = ["order", "starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="program_item_ends_after_start",
            )
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.starts_at:%H:%M})"

    def clean(self):
        errors = {}
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "Краят трябва да е след началото."
        # Точката от програмата трябва да попада в рамките на събитието.
        if self.event_id and self.starts_at:
            if self.starts_at < self.event.starts_at or (
                self.ends_at and self.ends_at > self.event.ends_at
            ):
                errors["starts_at"] = (
                    "Точката от програмата трябва да е в рамките на събитието "
                    f"({self.event.starts_at:%d.%m.%Y %H:%M} – "
                    f"{self.event.ends_at:%d.%m.%Y %H:%M})."
                )
        if errors:
            raise ValidationError(errors)


class TicketType(models.Model):
    """
    Билетен тип с цена и квота (напр. Стандартен, VIP, Студентски).

    Квотата е независима от общия капацитет на събитието: и двете се проверяват
    при резервация, като по-строгото ограничение е водещо.
    """

    event = models.ForeignKey(
        Event, verbose_name="Събитие", on_delete=models.CASCADE, related_name="ticket_types"
    )
    name = models.CharField("Наименование", max_length=100)
    description = models.CharField("Описание", max_length=255, blank=True)
    price = models.DecimalField(
        "Цена (€)",
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    quota = models.PositiveIntegerField(
        "Квота",
        validators=[MinValueValidator(1)],
        help_text="Максимален брой билети от този тип.",
    )
    sales_start = models.DateTimeField("Начало на продажбите", null=True, blank=True)
    sales_end = models.DateTimeField("Край на продажбите", null=True, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Билетен тип"
        verbose_name_plural = "Билетни типове"
        ordering = ["price", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "name"], name="unique_ticket_type_name_per_event"
            ),
            models.CheckConstraint(
                condition=models.Q(quota__gt=0), name="ticket_type_quota_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0), name="ticket_type_price_non_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} — {self.price} €"

    def clean(self):
        if self.sales_start and self.sales_end and self.sales_end <= self.sales_start:
            raise ValidationError(
                {"sales_end": "Краят на продажбите трябва да е след началото им."}
            )

    @property
    def sold_count(self) -> int:
        """Брой билети от този тип, които заемат място."""
        from registration.models import TicketStatus

        return self.tickets.filter(
            status__in=[TicketStatus.RESERVED, TicketStatus.VALID, TicketStatus.USED]
        ).count()

    @property
    def remaining(self) -> int:
        return max(self.quota - self.sold_count, 0)

    @property
    def is_on_sale(self) -> bool:
        """Дали билетният тип се продава в момента."""
        if not self.is_active or self.remaining == 0:
            return False
        now = timezone.now()
        if self.sales_start and now < self.sales_start:
            return False
        if self.sales_end and now > self.sales_end:
            return False
        return True

    @property
    def is_free(self) -> bool:
        return self.price == Decimal("0.00")
