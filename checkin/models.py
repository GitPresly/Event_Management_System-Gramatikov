"""
Модели на модул „На място“ (check-in).

Тук е втората половина от защитата срещу дублиране на билети. QR кодът е
подписан (виж registration/qr.py) и не може да бъде фалшифициран, но един
истински билет пак би могъл да бъде показан два пъти — например ако участникът
изпрати снимка на билета си на друг човек.

Затова връзката CheckIn ↔ Ticket е „едно към едно“: базата данни физически не
позволява втори запис за същия билет. Дори две сканирания да се случат в
абсолютно един и същи момент от два различни телефона, второто ще получи
грешка за нарушена уникалност и ще бъде отчетено като опит за дублиране.
"""
from django.db import models


class ScanResult(models.TextChoices):
    """Възможни изходи от едно сканиране."""

    OK = "OK", "Успешен вход"
    DUPLICATE = "DUPLICATE", "Билетът вече е използван"
    INVALID_SIGNATURE = "INVALID_SIGNATURE", "Невалиден или подправен код"
    NOT_FOUND = "NOT_FOUND", "Билетът не е намерен"
    WRONG_EVENT = "WRONG_EVENT", "Билет за друго събитие"
    NOT_PAID = "NOT_PAID", "Билетът не е платен"
    CANCELLED = "CANCELLED", "Билетът е анулиран"
    EVENT_NOT_ACTIVE = "EVENT_NOT_ACTIVE", "Събитието не е активно"


class CheckIn(models.Model):
    """
    Регистриран вход на участник.

    Един запис = един реално влязъл човек. Броят на записите за дадено събитие
    е „реалният брой присъстващи“, който заданието изисква да се проследява.
    """

    ticket = models.OneToOneField(
        "registration.Ticket",
        verbose_name="Билет",
        on_delete=models.CASCADE,
        related_name="checkin",
    )
    # Събитието се пази и тук, за да може броенето по събитие да става без
    # присъединяване на таблицата с билетите.
    event = models.ForeignKey(
        "events.Event",
        verbose_name="Събитие",
        on_delete=models.CASCADE,
        related_name="checkins",
    )
    operator = models.ForeignKey(
        "accounts.User",
        verbose_name="Извършил проверката",
        on_delete=models.PROTECT,
        related_name="performed_checkins",
    )
    checked_in_at = models.DateTimeField("Час на влизане", auto_now_add=True, db_index=True)
    note = models.CharField("Бележка", max_length=255, blank=True)

    class Meta:
        verbose_name = "Регистриран вход"
        verbose_name_plural = "Регистрирани входове"
        ordering = ["-checked_in_at"]
        indexes = [models.Index(fields=["event", "-checked_in_at"])]

    def __str__(self) -> str:
        return f"{self.ticket.short_code} @ {self.checked_in_at:%d.%m.%Y %H:%M}"


class ScanLog(models.Model):
    """
    Дневник на всички сканирания, включително неуспешните.

    Служи за одит: по него може да се докаже кога е бил направен опит с
    подправен билет или колко пъти е бил показан вече използван билет.
    """

    event = models.ForeignKey(
        "events.Event",
        verbose_name="Събитие",
        on_delete=models.CASCADE,
        related_name="scan_logs",
    )
    ticket = models.ForeignKey(
        "registration.Ticket",
        verbose_name="Билет",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scan_logs",
    )
    operator = models.ForeignKey(
        "accounts.User",
        verbose_name="Оператор",
        on_delete=models.PROTECT,
        related_name="scan_logs",
    )
    result = models.CharField(
        "Резултат", max_length=30, choices=ScanResult.choices, db_index=True
    )
    # Записва се само началото на кода — достатъчно за проследяване, без да се
    # съхранява целият валиден подпис в дневника.
    payload_preview = models.CharField("Сканиран код (начало)", max_length=60, blank=True)
    ip_address = models.GenericIPAddressField("IP адрес", null=True, blank=True)
    created_at = models.DateTimeField("Час на сканиране", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Запис от дневника"
        verbose_name_plural = "Дневник на сканиранията"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["event", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.get_result_display()} @ {self.created_at:%d.%m.%Y %H:%M:%S}"

    @property
    def is_success(self) -> bool:
        return self.result == ScanResult.OK
