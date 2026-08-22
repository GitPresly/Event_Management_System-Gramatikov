"""
Модели на модул „Комуникация“.

Всяко изпратено (или неуспешно) писмо се записва в дневник. Това служи за две
неща: одит — да се докаже кога какво е изпратено; и предпазване от повторни
напомняния — преди изпращане системата проверява дали такова писмо вече е
било изпратено по същата заявка.
"""
from django.db import models


class EmailKind(models.TextChoices):
    """Видовете писма, които системата изпраща."""

    CONFIRMATION = "CONFIRMATION", "Потвърждение за регистрация"
    REMINDER = "REMINDER", "Напомняне за предстоящо събитие"
    CANCELLATION = "CANCELLATION", "Потвърждение за отказ"


class EmailStatus(models.TextChoices):
    SENT = "SENT", "Изпратено"
    FAILED = "FAILED", "Неуспешно"


class EmailLog(models.Model):
    """Запис за едно изпратено писмо."""

    kind = models.CharField(
        "Вид", max_length=20, choices=EmailKind.choices, db_index=True
    )
    recipient = models.EmailField("Получател")
    subject = models.CharField("Тема", max_length=255)

    registration = models.ForeignKey(
        "registration.Registration",
        verbose_name="Заявка",
        on_delete=models.CASCADE,
        related_name="email_logs",
        null=True,
        blank=True,
    )
    event = models.ForeignKey(
        "events.Event",
        verbose_name="Събитие",
        on_delete=models.CASCADE,
        related_name="email_logs",
        null=True,
        blank=True,
    )

    status = models.CharField(
        "Статус", max_length=20, choices=EmailStatus.choices, default=EmailStatus.SENT
    )
    error = models.TextField("Съобщение за грешка", blank=True)
    sent_at = models.DateTimeField("Изпратено на", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Изпратено писмо"
        verbose_name_plural = "Дневник на писмата"
        ordering = ["-sent_at"]
        indexes = [
            models.Index(fields=["registration", "kind"]),
            models.Index(fields=["event", "kind"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} → {self.recipient}"

    @property
    def is_sent(self) -> bool:
        return self.status == EmailStatus.SENT
