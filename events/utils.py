"""
Помощни функции на модул „Събития“.

Основното тук е транслитерацията на кирилица. Стандартният slugify на Django
работи само с латиница и просто изхвърля кирилските букви — заглавие като
„Концерт „Класика под звездите“ би дало празен адрес. Затова текстът първо се
преобразува на латиница по официалната българска транслитерация, а чак после
се подава на slugify.

Резултат: „Концерт „Класика под звездите“ → koncert-klasika-pod-zvezdite
"""
from django.utils.text import slugify

# Таблица за транслитерация съгласно Закона за транслитерацията.
CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a",
    "ь": "y", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    """Преобразува кирилски текст на латиница, като запазва останалите знаци."""
    result = []
    for char in text:
        lower = char.lower()
        replacement = CYRILLIC_TO_LATIN.get(lower)
        if replacement is None:
            result.append(char)
        elif char.isupper():
            # Запазва главната буква: „Ж“ → „Zh“, а не „ZH“.
            result.append(replacement.capitalize())
        else:
            result.append(replacement)
    return "".join(result)


def slugify_bg(text: str, fallback: str = "event") -> str:
    """
    Съставя адресен идентификатор от текст на български.

    Използва се вместо направо slugify, защото последният изхвърля кирилицата.
    """
    return slugify(transliterate(text)) or fallback
