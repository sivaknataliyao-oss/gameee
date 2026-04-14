"""Тесты для новостного пайплайна."""

from src.filters import filter_by_keywords
from src.parser import clean_html


def test_clean_html():
    raw = "<p>Hello <b>world</b></p>"
    assert clean_html(raw) == "Hello world"


def test_clean_html_empty():
    assert clean_html("") == ""


def test_filter_by_keywords_match():
    articles = [
        {"title": "Python 3.13 released", "summary": "New features"},
        {"title": "Football match results", "summary": "Sports news"},
    ]
    result = filter_by_keywords(articles, ["Python"])
    assert len(result) == 1
    assert result[0]["title"] == "Python 3.13 released"


def test_filter_by_keywords_case_insensitive():
    articles = [{"title": "AI Revolution", "summary": "Machine learning"}]
    result = filter_by_keywords(articles, ["ai"])
    assert len(result) == 1


def test_filter_by_keywords_empty():
    articles = [{"title": "Test", "summary": "Test"}]
    result = filter_by_keywords(articles, [])
    assert len(result) == 1
