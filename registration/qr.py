"""
Генериране и проверка на QR кодовете на билетите.

Ключово решение за нефункционалното изискване „сигурност на билетите (защита
от дублиране)“:

QR кодът НЕ съдържа голия идентификатор на билета, а стойност, подписана с
тайния ключ на приложението чрез django.core.signing. Подписът е HMAC-SHA256.
Това означава, че:

  * никой не може да си съчини валиден QR код, без да знае SECRET_KEY;
  * промяна дори на един знак в кода прави подписа невалиден и билетът се
    отхвърля още преди да се направи справка в базата данни.

Защитата от повторно използване на един и същ (валиден) билет се постига на
друго ниво — чрез уникалната връзка CheckIn ↔ Ticket в модул checkin.
"""
import io

import qrcode
from django.core import signing
from django.core.files.base import ContentFile
from qrcode.constants import ERROR_CORRECT_M

# Префикс, по който се разпознава, че сканираният текст е билет на тази система.
PAYLOAD_PREFIX = "EMS1"

# Отделна „сол“ за подписа — така подписите на билетите не могат да се
# използват в друг контекст на приложението.
SIGNING_SALT = "ems.ticket.qr"


class InvalidTicketError(Exception):
    """Хвърля се, когато сканираният код не е валиден билет на системата."""


def build_payload(ticket) -> str:
    """
    Съставя текста, който се записва в QR кода на билета.

    Форматът е: EMS1:<uuid>:<подпис>
    """
    signed = signing.Signer(salt=SIGNING_SALT).sign(str(ticket.uuid))
    return f"{PAYLOAD_PREFIX}:{signed}"


def verify_payload(payload: str) -> str:
    """
    Проверява подписа на сканиран код и връща uuid на билета.

    Хвърля InvalidTicketError, ако кодът е чужд, подправен или с грешен формат.
    """
    if not payload:
        raise InvalidTicketError("Празен код.")

    payload = payload.strip()

    if not payload.startswith(f"{PAYLOAD_PREFIX}:"):
        raise InvalidTicketError("Кодът не е билет на тази система.")

    signed = payload[len(PAYLOAD_PREFIX) + 1 :]

    try:
        return signing.Signer(salt=SIGNING_SALT).unsign(signed)
    except signing.BadSignature as exc:
        raise InvalidTicketError("Невалиден подпис — билетът е подправен.") from exc


def render_qr_png(payload: str, box_size: int = 8, border: int = 2) -> bytes:
    """
    Изчертава QR код от подадения текст и го връща като PNG в паметта.

    Използва библиотеката qrcode, посочена изрично в заданието.
    Нивото на корекция на грешки M позволява кодът да се разчете дори при
    леко замърсен или измачкан разпечатан билет.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def attach_qr_to_ticket(ticket, save: bool = True) -> None:
    """
    Генерира QR изображението за билета и го записва в полето qr_image.

    Извиква се при успешно (симулирано) плащане — преди това билетът е само
    резервация и няма нужда от QR код.
    """
    payload = build_payload(ticket)
    png = render_qr_png(payload)
    filename = f"ticket-{ticket.short_code}.png"
    ticket.qr_image.save(filename, ContentFile(png), save=save)
