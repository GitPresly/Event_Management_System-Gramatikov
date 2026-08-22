"""Форми за регистрация и управление на потребители."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from accounts.models import Role, User


class BootstrapFormMixin:
    """Добавя CSS класовете на Bootstrap към всички полета на формата."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class SignUpForm(BootstrapFormMixin, UserCreationForm):
    """
    Публична форма за самостоятелна регистрация.

    Създава единствено потребители с роля „Участник“ — ролите „Организатор“ и
    „Администратор“ се назначават само от администратор, за да не може някой да
    си даде повишени права сам.
    """

    first_name = forms.CharField(label="Име", max_length=150)
    last_name = forms.CharField(label="Фамилия", max_length=150)
    email = forms.EmailField(label="Имейл адрес")
    phone = forms.CharField(label="Телефон", max_length=20, required=False)

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "phone")
        labels = {"username": "Потребителско име"}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Вече съществува потребител с този имейл адрес.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = Role.PARTICIPANT
        user.email = self.cleaned_data["email"]
        user.phone = self.cleaned_data.get("phone", "")
        if commit:
            user.save()
        return user


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    """Форма за вход с надписи на български."""

    username = forms.CharField(label="Потребителско име")
    password = forms.CharField(label="Парола", widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": "Грешно потребителско име или парола.",
        "inactive": "Този профил е деактивиран.",
    }


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    """Редактиране на собствения профил."""

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone", "organization")
        labels = {
            "first_name": "Име",
            "last_name": "Фамилия",
            "email": "Имейл адрес",
            "phone": "Телефон",
            "organization": "Организация",
        }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Вече съществува потребител с този имейл адрес.")
        return email


class UserManagementForm(BootstrapFormMixin, forms.ModelForm):
    """
    Форма, с която администраторът управлява чужди профили.

    Само оттук може да се смени ролята на потребител.
    """

    class Meta:
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "phone",
            "organization",
            "role",
            "is_active",
        )
        labels = {
            "username": "Потребителско име",
            "first_name": "Име",
            "last_name": "Фамилия",
            "email": "Имейл адрес",
            "phone": "Телефон",
            "organization": "Организация",
            "role": "Роля",
            "is_active": "Активен профил",
        }
