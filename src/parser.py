"""Модуль для парсинга и очистки контента."""

from bs4 import BeautifulSoup


def clean_html(raw_html: str) -> str:
    """Удаляет HTML-теги и возвращает чистый текст."""
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def process_articles(articles: list[dict]) -> list[dict]:
    """Очищает summary от HTML для каждой статьи."""
    for article in articles:
        if article.get("summary"):
            article["summary"] = clean_html(article["summary"])
    return articles
