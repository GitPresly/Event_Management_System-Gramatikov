"""
Модели на модул „Регистрация“.

Покрива изискванията от заданието:
  * онлайн регистрация и резервация на билет (симулация на плащане);
  * генериране на уникален QR код за всеки билет.

Структурата е на три нива:
  Registration — една заявка на един участник за едно събитие;
  Ticket       — отделен билет в рамките на заявката (носител на QR кода);
  Payment      — симулираното плащане по заявката.
"""
import secrets
import uuid
from decimal import Decimal

from django.db import models
from django.urls import reverse


class RegistrationStatus(models.TextChoices):
    """Състояние на заявката за регистрация."""

    PENDING = "PENDING", "Чака плащане"
    PAID = "PAID", "Платена"
    CANCELLED = "CANCELLED", "Отказана"


class TicketStatus(models.TextChoices):
    """
    Състояние на отделен билет.

    RESERVED — мястото е запазено, но заявката още не е платена;
    VALID    — билетът е платен и може да бъде използван за вход;
    USED     — билетът вече е бил сканиран на входа (check-in);
    CANCELLED — билетът е анулиран и мястото е освободено.
    """

    RESERVED = "RESERVED", "Резервиран"
    VALID = "VALID", "Валиден"
    USED = "USED", "Използван"
    CANCELLED = "CANCELLED", "Анулиран"


class PaymentMethod(models.TextChoices):
    """Начини на плащане (симулирани)."""

    CARD = "CARD", "Банкова карта"
    BANK = "BANK", "Банков превод"
    CASH = "CASH", "В брой на място"


class PaymentStatus(models.TextChoices):
    SUCCESS = "SUCCESS", "Успешно"
    FAILED = "FAILED", "Неуспешно"


def generate_registration_code() -> str:
    """Съставя четим уникален код на заявката, напр. REG-7QK4M2XD."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без лесно бъркащи се знаци
    while True:
        code = "REG-" + "".join(secrets.choice(alphabet) for _ in range(8))
        if not Registration.objects.filter(code=code).exists():
            return code


class Registration(models.Model):
    """Заявка за регистрация на участник за конкретно събитие."""

    code = models.CharField(
        "Код на заявката", max_length=20, unique=True, default=generate_registration_code
    )
    user = models.ForeignKey(
        "accounts.User",
        verbose_name="Участник",
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    event = models.ForeignKey(
        "events.Event",
        verbose_name="Събитие",
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.PENDING,
        db_index=True,
    )

    # Контактните данни се записват в момента на заявката, за да останат
    # непроменени дори ако потребителят по-късно редактира профила си.
    contact_name = models.CharField("Име за контакт", max_length=200)
    contact_email = models.EmailField("Имейл за контакт")
    contact_phone = models.CharField("Телефон", max_length=20, blank=True)

    total_amount = models.DecimalField(
        "Обща сума (€)", max_digits=10, decimal_places=2, default=Decimal("0.00")
    )

    created_at = models.DateTimeField("Създадена на", auto_now_add=True, db_index=True)
    paid_at = models.DateTimeField("Платена на", null=True, blank=True)
    cancelled_at = models.DateTimeField("Отказана на", null=True, blank=True)

    class Meta:
        verbose_name = "Регистрация"
        verbose_name_plural = "Регистрации"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event", "status"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.event.title}"

    def get_absolute_url(self):
        return reverse("registration:registration_detail", kwargs={"code": self.code})

    @property
    def ticket_count(self) -> int:
        return self.tickets.exclude(status=TicketStatus.CANCELLED).count()

    @property
    def is_payable(self) -> bool:
        """Дали заявката чака плащане."""
        return self.status == RegistrationStatus.PENDING

    @property
    def is_cancellable(self) -> bool:
        """
        Заявката може да се откаже, докато нито един билет не е използван.

        След check-in отказът вече няма смисъл — участникът е присъствал.
        """
        if self.status == RegistrationStatus.CANCELLED:
            return False
        return not self.tickets.filter(status=TicketStatus.USED).exists()


class Ticket(models.Model):
    """
    Отделен билет — носителят на QR кода.

    Полето uuid е уникално и служи за идентификатор в QR кода. Самият QR код
    не съдържа голия uuid, а подписана с тайния ключ стойност (виж qr.py),
    така че фалшифициран билет се разпознава още преди справка в базата.
    """

    uuid = models.UUIDField(
        "Уникален идентификатор", default=uuid.uuid4, unique=True, editable=False
    )
    registration = models.ForeignKey(
        Registration, verbose_name="Заявка", on_delete=models.CASCADE, related_name="tickets"
    )
    ticket_type = models.ForeignKey(
        "events.TicketType",
        verbose_name="Билетен тип",
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    # Събитието се дублира тук нарочно: почти всички отчети и проверки при
    # check-in филтрират по събитие и това спестява присъединяване на таблици.
    event = models.ForeignKey(
        "events.Event",
        verbose_name="Събитие",
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    holder_name = models.CharField("Име на притежателя", max_length=200)
    holder_email = models.EmailField("Имейл на притежателя")

    # Цената се записва в момента на покупката — по-късна промяна на цената
    # на билетния тип не бива да променя вече издадени билети.
    price_paid = models.DecimalField(
        "Платена цена (€)", max_digits=8, decimal_places=2, default=Decimal("0.00")
    )

    status = models.CharField(
        "Статус",
        max_length=20,
        choices=TicketStatus.choices,
        default=TicketStatus.RESERVED,
        db_index=True,
    )
    qr_image = models.ImageField(
        "QR код", upload_to="tickets/qr/", blank=True, null=True
    )

    issued_at = models.DateTimeField("Издаден на", auto_now_add=True)

    class Meta:
        verbose_name = "Билет"
        verbose_name_plural = "Билети"
        ordering = ["issued_at"]
        indexes = [
            models.Index(fields=["event", "status"]),
            models.Index(fields=["ticket_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"Билет {self.short_code} — {self.event.title}"

    def get_absolute_url(self):
        return reverse("registration:ticket_detail", kwargs={"uuid": self.uuid})

    @property
    def short_code(self) -> str:
        """Съкратен код за показване и за ръчно въвеждане при check-in."""
        return str(self.uuid).split("-")[0].upper()

    @property
    def is_checked_in(self) -> bool:
        return self.status == TicketStatus.USED

    @property
    def is_usable(self) -> bool:
        """Дали билетът може да бъде използван за вход."""
        return self.status == TicketStatus.VALID


class Payment(models.Model):
    """
    Симулация на плащане по заявка.

    Заданието изисква изрично симулация, не реален платежен процесор. Записът
    пази метода, сумата и генериран референтен номер, за да може плащането да
    се проследи в отчетите така, както би било при истинска интеграция.
    """

    registration = models.OneToOneField(
        Registration, verbose_name="Заявка", on_delete=models.CASCADE, related_name="payment"
    )
    amount = models.DecimalField("Сума (€)", max_digits=10, decimal_places=2)
    method = models.CharField(
        "Начин на плащане", max_length=20, choices=PaymentMethod.choices
    )
    transaction_ref = models.CharField(
        "Референтен номер", max_length=40, unique=True
    )
    status = models.CharField(
        "Статус", max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.SUCCESS
    )
    created_at = models.DateTimeField("Дата на плащане", auto_now_add=True)

    class Meta:
        verbose_name = "Плащане"
        verbose_name_plural = "Плащания"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.transaction_ref} — {self.amount} €"

    @staticmethod
    def generate_reference() -> str:
        """Генерира референтен номер на транзакция (симулиран)."""
        return "TXN-" + secrets.token_hex(8).upper()
