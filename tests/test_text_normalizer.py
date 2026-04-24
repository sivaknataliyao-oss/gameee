import pytest

from src.tts.text_normalizer import normalize_for_tts


# Tests require num2words for the Russian transformations to produce words.
pytest.importorskip("num2words")


def test_plain_number_is_spelled():
    assert "сорок два" in normalize_for_tts("Ему было 42 года")
    # single digits left alone
    assert "5" in normalize_for_tts("У меня 5")


def test_currency_dollar_before_number():
    out = normalize_for_tts("Я потратил $250 на ужин")
    assert "двести пятьдесят" in out
    assert "долларов" in out


def test_currency_code_after_number():
    out = normalize_for_tts("1 200 руб за чашку")
    assert "тысяча двести" in out
    assert "рубль" in out or "рубля" in out or "рублей" in out


def test_percent():
    out = normalize_for_tts("Скидка 25%")
    assert "двадцать пять" in out
    assert "процентов" in out


def test_date_dd_mm_yyyy():
    out = normalize_for_tts("Случилось 25.04.2026 вечером")
    assert "апреля" in out
    assert "тысяч" in out  # year spelled
    assert "25.04.2026" not in out


def test_date_iso():
    out = normalize_for_tts("Событие: 2026-04-25")
    assert "апреля" in out
    assert "2026-04-25" not in out


def test_time_with_minutes():
    out = normalize_for_tts("Встреча в 9:30 утра")
    assert "9:30" not in out
    assert "девять" in out
    assert "тридцать" in out


def test_time_with_leading_zero_minutes():
    out = normalize_for_tts("Поезд в 17:05")
    assert "17:05" not in out
    assert "ноль" in out


def test_ordinal_hyphen_form():
    out = normalize_for_tts("Он занял 21-е место")
    assert "21-е" not in out
    assert "двадцать первый" in out or "двадцать первое" in out


def test_idempotent():
    first = normalize_for_tts("В 2020 было $100, 50%, 25.04.2026.")
    second = normalize_for_tts(first)
    assert first == second
