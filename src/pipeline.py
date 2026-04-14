"""Главный модуль новостного пайплайна."""

import argparse
from pathlib import Path

import yaml

from .fetcher import fetch_all_sources
from .filters import filter_by_keywords
from .parser import process_articles
from .storage import save

DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "sources.yaml"


def load_config(config_path: str) -> dict:
    """Загружает конфигурацию из YAML-файла."""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run(config_path: str | None = None) -> None:
    """Запускает пайплайн: сбор → очистка → фильтрация → сохранение."""
    path = config_path or str(DEFAULT_CONFIG)
    config = load_config(path)

    print("=== Новостной пайплайн ===")
    print(f"Источников: {len(config['sources'])}")

    # 1. Сбор
    print("\n[1/3] Сбор новостей...")
    articles = fetch_all_sources(config["sources"])
    print(f"Всего собрано: {len(articles)}")

    # 2. Очистка и парсинг
    print("\n[2/3] Очистка контента...")
    articles = process_articles(articles)

    # 3. Фильтрация
    keywords = config.get("filters", {}).get("keywords", [])
    if keywords:
        print(f"\n[3/3] Фильтрация по ключевым словам: {keywords}")
        articles = filter_by_keywords(articles, keywords)
        print(f"После фильтрации: {len(articles)}")
    else:
        print("\n[3/3] Фильтрация не настроена, пропускаем")

    # 4. Сохранение
    storage_config = config.get("storage", {"type": "json", "path": "output/news.json"})
    save(articles, storage_config)

    print("\nГотово!")


def main():
    parser = argparse.ArgumentParser(description="Новостной пайплайн")
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Путь к файлу конфигурации (по умолчанию: config/sources.yaml)",
    )
    args = parser.parse_args()
    run(args.config)


if __name__ == "__main__":
    main()
