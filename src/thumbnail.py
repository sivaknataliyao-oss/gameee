"""Генерация обложки (thumbnail) для YouTube.

Создаёт кликабельную обложку 1280x720:
- Фоновое изображение (из ассетов)
- Крупный заголовок
- Цветовой акцент
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter


def create_thumbnail(
    title: str,
    background_image: str | None,
    output_path: str,
    width: int = 1280,
    height: int = 720,
) -> str:
    """Создаёт YouTube thumbnail."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # Фон
    if background_image and os.path.exists(background_image):
        img = Image.open(background_image)
        img = img.resize((width, height), Image.LANCZOS)
        # Затемняем для читаемости текста
        img = img.filter(ImageFilter.GaussianBlur(radius=3))
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 140))
        img = img.convert("RGBA")
        img = Image.alpha_composite(img, overlay)
        img = img.convert("RGB")
    else:
        # Градиентный фон
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)
        for y in range(height):
            r = int(20 + (y / height) * 30)
            g = int(10 + (y / height) * 15)
            b = int(40 + (y / height) * 60)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

    draw = ImageDraw.Draw(img)

    # Красная плашка сверху (стиль "BREAKING NEWS")
    draw.rectangle([(40, 30), (350, 90)], fill=(220, 30, 30))
    _draw_text(draw, "BREAKING", (50, 35), size=44, color=(255, 255, 255))

    # Заголовок — крупный, жирный
    short_title = title[:80] if len(title) > 80 else title
    _draw_wrapped_text(
        draw, short_title.upper(),
        x=50, y=height // 2 - 100,
        max_width=width - 100,
        size=62,
        color=(255, 255, 255),
    )

    # Нижняя плашка
    draw.rectangle([(0, height - 60), (width, height)], fill=(220, 30, 30))
    _draw_text(draw, "DAILY NEWS UPDATE", (width // 2 - 180, height - 50), size=32, color=(255, 255, 255))

    img.save(output_path, "JPEG", quality=95)
    print(f"[THUMBNAIL] Обложка: {output_path}")
    return output_path


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Пытается загрузить шрифт, fallback на default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _draw_text(draw: ImageDraw.Draw, text: str, pos: tuple, size: int = 40,
               color: tuple = (255, 255, 255)) -> None:
    """Рисует текст с тенью."""
    font = _get_font(size)
    x, y = pos
    # Тень
    draw.text((x + 2, y + 2), text, fill=(0, 0, 0), font=font)
    draw.text((x, y), text, fill=color, font=font)


def _draw_wrapped_text(draw: ImageDraw.Draw, text: str, x: int, y: int,
                       max_width: int, size: int = 50,
                       color: tuple = (255, 255, 255)) -> None:
    """Рисует текст с переносом строк."""
    font = _get_font(size)
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width:
            if current_line:
                lines.append(current_line)
            current_line = word
        else:
            current_line = test
    if current_line:
        lines.append(current_line)

    line_height = size + 10
    for i, line in enumerate(lines[:4]):  # Макс 4 строки
        _draw_text(draw, line, (x, y + i * line_height), size, color)
