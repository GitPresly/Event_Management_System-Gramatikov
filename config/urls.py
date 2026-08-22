"""
Главна карта на адресите (URL) на проекта.

Всяко приложение поддържа собствен urls.py, който се включва тук с
пространство от имена (namespace), напр. events:event_list.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("events.urls")),
    path("accounts/", include("accounts.urls")),
    path("registration/", include("registration.urls")),
    path("checkin/", include("checkin.urls")),
    path("reports/", include("reports.urls")),
]

# В режим на разработка Django сам обслужва качените файлове (QR кодове, корици).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Заглавия на вградения административен панел
admin.site.site_header = "Система за управление на събития"
admin.site.site_title = "Администрация"
admin.site.index_title = "Административен панел"
