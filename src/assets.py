"""Сбор визуальных ассетов для видео.

Использует Pexels API (бесплатно, до 200 запросов/час).
Получи ключ: https://www.pexels.com/api/
"""

import os
import requests


PEXELS_API_URL = "https://api.pexels.com/v1/search"


def search_images(query: str, count: int = 5, api_key: str | None = None) -> list[dict]:
    """Ищет изображения на Pexels по запросу."""
    key = api_key or os.environ.get("PEXELS_API_KEY", "")
    if not key:
        print("[ASSETS] ⚠ PEXELS_API_KEY не задан — изображения не будут скачаны")
        return []

    headers = {"Authorization": key}
    params = {"query": query, "per_page": count, "orientation": "landscape", "size": "large"}

    try:
        resp = requests.get(PEXELS_API_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for photo in data.get("photos", []):
            results.append({
                "id": photo["id"],
                "url": photo["src"]["large2x"],
                "alt": photo.get("alt", query),
                "photographer": photo.get("photographer", ""),
            })
        return results
    except Exception as e:
        print(f"[ASSETS] Ошибка поиска: {e}")
        return []


def download_image(url: str, save_path: str) -> str | None:
    """Скачивает изображение по URL."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(resp.content)
        return save_path
    except Exception as e:
        print(f"[ASSETS] Ошибка скачивания: {e}")
        return None


def collect_visuals(script: dict, run_dir: str, api_key: str | None = None) -> list[str]:
    """Собирает изображения для каждой секции сценария."""
    assets_dir = os.path.join(run_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    downloaded = []

    for i, section in enumerate(script.get("sections", [])):
        visuals = section.get("visuals", [])
        for j, visual_desc in enumerate(visuals):
            print(f"[ASSETS] Ищу: {visual_desc}")
            images = search_images(visual_desc, count=1, api_key=api_key)

            if images:
                ext = "jpg"
                filename = f"s{i:02d}_v{j:02d}_{ext}"
                save_path = os.path.join(assets_dir, filename)
                result = download_image(images[0]["url"], save_path)
                if result:
                    downloaded.append(result)
                    print(f"[ASSETS] ✓ {filename}")
            else:
                print(f"[ASSETS] ✗ Не найдено для: {visual_desc}")

    print(f"[ASSETS] Собрано {len(downloaded)} изображений")
    return downloaded


def create_text_slide(text: str, save_path: str,
                      width: int = 1920, height: int = 1080) -> str:
    """Создаёт слайд с текстом (fallback если нет изображений)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (width, height), color=(15, 15, 25))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
    except OSError:
        font = ImageFont.load_default()

    # Перенос текста
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > width - 200:
            lines.append(current_line)
            current_line = word
        else:
            current_line = test
    if current_line:
        lines.append(current_line)

    # Центрируем
    total_height = len(lines) * 60
    y = (height - total_height) // 2

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (width - bbox[2]) // 2
        draw.text((x, y), line, fill=(255, 255, 255), font=font)
        y += 60

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    img.save(save_path, "PNG")
    return save_path
