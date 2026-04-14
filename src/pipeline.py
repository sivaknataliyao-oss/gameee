"""Главный модуль новостного пайплайна.

Полный flow: новость → сценарий → озвучка → видео → YouTube

Запуск:
    python -m src.pipeline                      # полный пайплайн
    python -m src.pipeline --step fetch          # только сбор новостей
    python -m src.pipeline --step script         # только генерация сценария
    python -m src.pipeline --step render         # только рендер видео
    python -m src.pipeline --step upload         # только загрузка на YouTube
    python -m src.pipeline --dry-run             # прогон без публикации
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .fetcher import fetch_all_sources
from .filters import filter_by_keywords
from .parser import process_articles
from .scriptwriter import generate_script_playwright, save_script
from .tts import synthesize_google_cloud, script_to_narration
from .assets import collect_visuals, create_text_slide
from .thumbnail import create_thumbnail
from .renderer import render_video
from .uploader import upload_to_youtube

DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "sources.yaml"


def load_config(config_path: str) -> dict:
    """Загружает конфигурацию из YAML-файла."""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def create_run_dir(base: str = "runs") -> str:
    """Создаёт директорию для текущего прогона."""
    now = datetime.now(timezone.utc)
    date_dir = now.strftime("%Y-%m-%d")
    run_name = now.strftime("run_%H%M%SZ")
    run_dir = os.path.join(base, date_dir, run_name)
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def select_best_story(articles: list[dict]) -> dict | None:
    """Выбирает лучшую новость для видео."""
    if not articles:
        return None
    # Приоритет: самая свежая с наиболее длинным summary
    scored = sorted(articles, key=lambda a: len(a.get("summary", "")), reverse=True)
    return scored[0]


def step_fetch(config: dict) -> list[dict]:
    """Шаг 1: Сбор и фильтрация новостей."""
    print("\n" + "=" * 50)
    print("[1/7] СБОР НОВОСТЕЙ")
    print("=" * 50)

    articles = fetch_all_sources(config["sources"])
    print(f"Собрано: {len(articles)}")

    articles = process_articles(articles)

    keywords = config.get("filters", {}).get("keywords", [])
    if keywords:
        articles = filter_by_keywords(articles, keywords)
        print(f"После фильтрации: {len(articles)}")

    return articles


def step_select(articles: list[dict], run_dir: str) -> dict:
    """Шаг 2: Выбор главной новости."""
    print("\n" + "=" * 50)
    print("[2/7] ВЫБОР НОВОСТИ")
    print("=" * 50)

    story = select_best_story(articles)
    if not story:
        raise RuntimeError("Нет подходящих новостей!")

    print(f"Выбрано: {story['title']}")

    # Сохраняем
    story_path = os.path.join(run_dir, "story.json")
    with open(story_path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)

    return story


def step_script(story: dict, run_dir: str) -> dict:
    """Шаг 3: Генерация сценария."""
    print("\n" + "=" * 50)
    print("[3/7] ГЕНЕРАЦИЯ СЦЕНАРИЯ")
    print("=" * 50)

    script = generate_script_playwright(story)
    save_script(script, run_dir)

    total_words = sum(len(s.get("text", "").split()) for s in script.get("sections", []))
    estimated_minutes = total_words / 150
    print(f"Слов: {total_words}, ~{estimated_minutes:.1f} мин")

    return script


def step_tts(script: dict, run_dir: str, config: dict) -> str:
    """Шаг 4: Озвучка."""
    print("\n" + "=" * 50)
    print("[4/7] ОЗВУЧКА (TTS)")
    print("=" * 50)

    narration = script_to_narration(script)
    audio_path = os.path.join(run_dir, "narration.mp3")

    tts_config = config.get("tts", {})
    voice = tts_config.get("voice", "en-US-Wavenet-D")

    audio_path = synthesize_google_cloud(narration, audio_path, voice=voice)
    return audio_path


def step_assets(script: dict, run_dir: str, config: dict) -> list[str]:
    """Шаг 5: Сбор визуальных ассетов."""
    print("\n" + "=" * 50)
    print("[5/7] СБОР ИЗОБРАЖЕНИЙ")
    print("=" * 50)

    pexels_key = config.get("pexels", {}).get("api_key") or os.environ.get("PEXELS_API_KEY")
    images = collect_visuals(script, run_dir, api_key=pexels_key)

    # Если изображений недостаточно — создаём текстовые слайды
    sections = script.get("sections", [])
    if len(images) < len(sections):
        slides_dir = os.path.join(run_dir, "assets")
        os.makedirs(slides_dir, exist_ok=True)
        for i, section in enumerate(sections):
            if i >= len(images):
                slide_path = os.path.join(slides_dir, f"text_slide_{i:03d}.png")
                create_text_slide(section.get("heading", f"Section {i+1}"), slide_path)
                images.append(slide_path)

    return images


def step_render(script: dict, audio_path: str, images: list[str],
                run_dir: str) -> tuple[str, str]:
    """Шаг 6: Рендер видео + thumbnail."""
    print("\n" + "=" * 50)
    print("[6/7] РЕНДЕР ВИДЕО")
    print("=" * 50)

    video_path = os.path.join(run_dir, "video.mp4")
    video_path = render_video(script, audio_path, images, video_path)

    # Thumbnail
    thumb_path = os.path.join(run_dir, "thumbnail.jpg")
    bg_image = images[0] if images else None
    create_thumbnail(script.get("title", "News Update"), bg_image, thumb_path)

    return video_path, thumb_path


def step_upload(script: dict, video_path: str, thumb_path: str,
                config: dict, dry_run: bool = False) -> dict:
    """Шаг 7: Загрузка на YouTube."""
    print("\n" + "=" * 50)
    print("[7/7] ПУБЛИКАЦИЯ НА YOUTUBE")
    print("=" * 50)

    if dry_run:
        print("[DRY RUN] Пропуск загрузки")
        return {"status": "dry_run", "video_path": video_path}

    yt_config = config.get("youtube", {})

    result = upload_to_youtube(
        video_path=video_path,
        title=script.get("title", "News Update"),
        description=script.get("description", ""),
        tags=script.get("tags", ["news", "politics"]),
        thumbnail_path=thumb_path,
        privacy=yt_config.get("privacy", "public"),
        credentials_path=yt_config.get("credentials", "client_secret.json"),
        token_path=yt_config.get("token", "youtube_token.pickle"),
    )

    # Сохраняем результат
    upload_path = os.path.join(os.path.dirname(video_path), "upload.json")
    with open(upload_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def _find_latest_run() -> str | None:
    """Находит последний run-каталог с артефактами."""
    runs_dir = Path("runs")
    if not runs_dir.exists():
        return None
    # Ищем самый свежий run с script.json
    candidates = sorted(runs_dir.glob("*/run_*"), reverse=True)
    for d in candidates:
        if (d / "script.json").exists():
            return str(d)
    return None


def run(config_path: str | None = None, step: str | None = None,
        dry_run: bool = False) -> None:
    """Запускает полный пайплайн или отдельный шаг.

    --step fetch   : только сбор новостей
    --step script  : fetch + select + script
    --step render  : всё до рендера (включая рендер)
    --step upload  : только загрузка (из последнего прогона)
    без --step     : полный пайплайн
    """
    path = config_path or str(DEFAULT_CONFIG)
    config = load_config(path)

    print("╔══════════════════════════════════════╗")
    print("║   NEWS VIDEO PIPELINE                ║")
    print("║   новость → сценарий → видео → YT    ║")
    print("╚══════════════════════════════════════╝")

    # Если --step upload — берём данные из последнего прогона
    if step == "upload":
        last_run = _find_latest_run()
        if not last_run:
            raise RuntimeError("Нет предыдущего прогона для загрузки. Запусти полный пайплайн.")

        print(f"\nЗагрузка из прогона: {last_run}")
        script_path = os.path.join(last_run, "script.json")
        video_path = os.path.join(last_run, "video.mp4")
        thumb_path = os.path.join(last_run, "thumbnail.jpg")

        if not os.path.exists(video_path):
            raise RuntimeError(f"Видео не найдено: {video_path}")

        with open(script_path, encoding="utf-8") as f:
            script = json.load(f)

        step_upload(script, video_path, thumb_path, config, dry_run)
        return

    run_dir = create_run_dir()
    print(f"\nРабочая папка: {run_dir}")

    # 1. Fetch
    articles = step_fetch(config)

    if step == "fetch":
        from .storage import save
        save(articles, config.get("storage", {"type": "json", "path": "output/news.json"}))
        print("\nГотово! (только сбор)")
        return

    # 2. Select
    story = step_select(articles, run_dir)

    # 3. Script
    script = step_script(story, run_dir)

    if step == "script":
        print("\nГотово! (до генерации сценария)")
        return

    # 4. TTS
    audio_path = step_tts(script, run_dir, config)

    # 5. Assets
    images = step_assets(script, run_dir, config)

    # 6. Render
    video_path, thumb_path = step_render(script, audio_path, images, run_dir)

    if step == "render":
        print(f"\nГотово! Видео: {video_path}")
        return

    # 7. Upload
    result = step_upload(script, video_path, thumb_path, config, dry_run)

    print("\n" + "=" * 50)
    print("PIPELINE ЗАВЕРШЁН")
    print("=" * 50)
    print(f"Папка: {run_dir}")
    if "url" in result:
        print(f"YouTube: {result['url']}")
    print("Готово!")


def main():
    parser = argparse.ArgumentParser(description="News Video Pipeline")
    parser.add_argument("--config", "-c", default=None, help="Путь к конфигу")
    parser.add_argument("--step", "-s", choices=["fetch", "script", "render", "upload"],
                        default=None, help="Выполнить только конкретный шаг")
    parser.add_argument("--dry-run", action="store_true", help="Без публикации на YouTube")
    args = parser.parse_args()
    run(args.config, args.step, args.dry_run)


if __name__ == "__main__":
    main()
