"""
Модели на приложение accounts.

Тук е дефиниран потребителският модел на системата. Той разширява стандартния
AbstractUser на Django Auth с поле за роля, защото заданието изисква три
различни роли с различни права: Администратор, Организатор и Участник.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    """Ролите в системата съгласно заданието."""

    ADMIN = "ADMIN", "Администратор"
    ORGANIZER = "ORGANIZER", "Организатор"
    PARTICIPANT = "PARTICIPANT", "Участник"


class User(AbstractUser):
    """
    Потребител на системата.

    Наследява цялата функционалност на Django Auth (хеширане на паролите,
    сесии, разрешения) и добавя роля, по която се определят правата на достъп.
    """

    role = models.CharField(
        "Роля",
        max_length=20,
        choices=Role.choices,
        default=Role.PARTICIPANT,
        db_index=True,
    )
    phone = models.CharField("Телефон", max_length=20, blank=True)
    organization = models.CharField(
        "Организация",
        max_length=150,
        blank=True,
        help_text="Попълва се основно за организатори.",
    )

    # Имейлът се използва за изпращане на билети и напомняния, затова е задължителен.
    email = models.EmailField("Имейл адрес", unique=True)

    class Meta:
        verbose_name = "Потребител"
        verbose_name_plural = "Потребители"
        ordering = ["username"]

    def __str__(self) -> str:
        full_name = self.get_full_name()
        return f"{full_name} ({self.username})" if full_name else self.username

    # -- Помощни свойства за проверка на ролята -----------------------------
    # Използват се в изгледите и шаблоните вместо сравнения с низове.

    @property
    def is_admin_role(self) -> bool:
        """Администратор е всеки с роля ADMIN, както и суперпотребителят."""
        return self.role == Role.ADMIN or self.is_superuser

    @property
    def is_organizer(self) -> bool:
        return self.role == Role.ORGANIZER

    @property
    def is_participant(self) -> bool:
        return self.role == Role.PARTICIPANT

    @property
    def can_manage_events(self) -> bool:
        """Достъп до създаване и редактиране на събития."""
        return self.is_admin_role or self.is_organizer

    def display_name(self) -> str:
        """Име за показване в интерфейса."""
        return self.get_full_name() or self.username
