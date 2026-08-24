"""
Генериране на иконата на сайта (favicon) в растерни формати.

Изчертава същата форма като static/img/favicon.svg — билет с изрезки отстрани
и перфорация по средата — и я записва като PNG в няколко размера и като .ico.

Растерните варианти са нужни, защото не всички браузъри и мобилни системи
поддържат SVG икона, а някои изискват точно /favicon.ico.

Изчертаването е с четирикратно увеличение и последващо смаляване (supersampling),
за да излязат ръбовете гладки, вместо назъбени.

Употреба:
    python scripts/make_favicon.py
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "static" / "img"

BLUE = (13, 110, 253, 255)      # #0d6efd — основният цвят на интерфейса
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)

SUPERSAMPLE = 4

# Размерите, които се записват като отделни PNG файлове.
PNG_SIZES = {
    "favicon-16.png": 16,
    "favicon-32.png": 32,
    "favicon-48.png": 48,
    "apple-touch-icon.png": 180,   # начален екран в iOS
    "icon-512.png": 512,           # уеб приложение / споделяне
}

# Размерите вътре в един .ico файл.
ICO_SIZES = [16, 32, 48, 64, 128, 256]


def draw_icon(size: int, rounded_background: bool = True) -> Image.Image:
    """
    Изчертава иконата в зададен размер.

    Координатите са същите като в SVG файла (мрежа 64×64) и се мащабират.
    """
    work = size * SUPERSAMPLE
    scale = work / 64

    def px(value: float) -> float:
        """Превръща координата от мрежата 64×64 в пиксели."""
        return value * scale

    image = Image.new("RGBA", (work, work), TRANSPARENT)
    draw = ImageDraw.Draw(image)

    # Основа със заоблени ъгли.
    if rounded_background:
        draw.rounded_rectangle(
            [0, 0, work - 1, work - 1], radius=px(14), fill=BLUE
        )
    else:
        draw.rectangle([0, 0, work - 1, work - 1], fill=BLUE)

    # Тялото на билета.
    draw.rounded_rectangle(
        [px(10), px(20), px(54), px(46)], radius=px(5), fill=WHITE
    )

    # Изрезките отстрани — кръгове в цвета на основата върху белия правоъгълник.
    for cx in (10, 54):
        draw.ellipse(
            [px(cx - 5), px(33 - 5), px(cx + 5), px(33 + 5)], fill=BLUE
        )

    # Перфорацията по средата — къси чертички.
    dash, gap = 3.0, 3.5
    y = 25.0
    while y < 41:
        draw.line(
            [px(32), px(y), px(32), px(min(y + dash, 41))],
            fill=BLUE,
            width=max(int(px(2.5)), 1),
        )
        y += dash + gap

    # Смаляване до желания размер с качествен филтър.
    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for filename, size in PNG_SIZES.items():
        icon = draw_icon(size)
        path = OUT_DIR / filename
        icon.save(path, format="PNG", optimize=True)
        print(f"  {path.relative_to(BASE_DIR)}  ({size}×{size})")

    # Един .ico файл с всички размери вътре.
    largest = draw_icon(256)
    ico_path = BASE_DIR / "static" / "favicon.ico"
    largest.save(ico_path, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"  {ico_path.relative_to(BASE_DIR)}  ({', '.join(map(str, ICO_SIZES))})")

    print("\nГотово. Иконите са записани в static/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
