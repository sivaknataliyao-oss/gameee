"""Модуль для сохранения новостей."""

import json
import os
import sqlite3
from datetime import datetime, timezone


def save_json(articles: list[dict], path: str) -> None:
    """Сохраняет статьи в JSON-файл."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    existing = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)

    existing_links = {a["link"] for a in existing}
    new_articles = [a for a in articles if a["link"] not in existing_links]

    all_articles = existing + new_articles

    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"Сохранено {len(new_articles)} новых статей (всего: {len(all_articles)})")


def save_sqlite(articles: list[dict], path: str) -> None:
    """Сохраняет статьи в SQLite базу."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            link TEXT UNIQUE,
            summary TEXT,
            published TEXT,
            author TEXT,
            source TEXT,
            category TEXT,
            fetched_at TEXT
        )
    """)

    count = 0
    for article in articles:
        try:
            cursor.execute(
                """INSERT OR IGNORE INTO articles
                   (title, link, summary, published, author, source, category, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    article.get("title"),
                    article.get("link"),
                    article.get("summary"),
                    article.get("published"),
                    article.get("author"),
                    article.get("source"),
                    article.get("category"),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            if cursor.rowcount > 0:
                count += 1
        except sqlite3.Error as e:
            print(f"Ошибка записи: {e}")

    conn.commit()
    conn.close()
    print(f"Сохранено {count} новых статей в SQLite")


def save(articles: list[dict], storage_config: dict) -> None:
    """Сохраняет статьи в зависимости от конфигурации."""
    storage_type = storage_config.get("type", "json")
    path = storage_config.get("path", "output/news.json")

    if storage_type == "sqlite":
        if not path.endswith(".db"):
            path = path.rsplit(".", 1)[0] + ".db"
        save_sqlite(articles, path)
    else:
        save_json(articles, path)
