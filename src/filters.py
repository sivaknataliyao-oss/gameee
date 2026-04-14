"""Модуль для фильтрации новостей по ключевым словам."""


def filter_by_keywords(articles: list[dict], keywords: list[str]) -> list[dict]:
    """Фильтрует статьи — оставляет только содержащие ключевые слова."""
    if not keywords:
        return articles

    keywords_lower = [kw.lower() for kw in keywords]
    filtered = []

    for article in articles:
        text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
        if any(kw in text for kw in keywords_lower):
            filtered.append(article)

    return filtered
