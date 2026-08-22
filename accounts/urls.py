"""Адреси на приложение accounts."""
from django.contrib.auth import views as auth_views
from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    # Вход и изход — върху вградените изгледи на Django Auth
    path("login/", views.EMSLoginView.as_view(), name="login"),
    path("logout/", views.EMSLogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    # Смяна на паролата (вградени изгледи на Django Auth)
    path(
        "password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            success_url="/accounts/password/change/done/",
        ),
        name="password_change",
    ),
    path(
        "password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/password_change_done.html"
        ),
        name="password_change_done",
    ),
    # Профил и табло
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    # Управление на потребители (само администратор)
    path("users/", views.user_list, name="user_list"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
]
