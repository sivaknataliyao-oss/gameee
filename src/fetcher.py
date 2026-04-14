"""Модуль для сбора новостей из RSS-лент."""

import feedparser
import requests


def fetch_feed(url: str, timeout: int = 15) -> list[dict]:
    """Загружает и парсит RSS-ленту, возвращает список статей."""
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    feed = feedparser.parse(response.text)

    articles = []
    for entry in feed.entries:
        article = {
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "summary": entry.get("summary", ""),
            "published": entry.get("published", ""),
            "author": entry.get("author", ""),
        }
        articles.append(article)

    return articles


def fetch_all_sources(sources: list[dict]) -> list[dict]:
    """Собирает новости из всех источников."""
    all_articles = []
    for source in sources:
        try:
            articles = fetch_feed(source["url"])
            for article in articles:
                article["source"] = source["name"]
                article["category"] = source.get("category", "general")
            all_articles.extend(articles)
            print(f"[OK] {source['name']}: {len(articles)} статей")
        except Exception as e:
            print(f"[ОШИБКА] {source['name']}: {e}")

    return all_articles
