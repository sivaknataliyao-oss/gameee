from datetime import datetime, timezone

from src.core.models import Lang, Metrics, Source, Story
from src.filters import dedup, quality


def test_quality_length_and_uppercase():
    ok, _ = quality.quality_ok("A" * 600, {"min_chars": 100, "max_chars": 10000,
                                           "max_uppercase_ratio": 0.3, "max_emoji_ratio": 0.15})
    assert not ok  # all upper, blocked

    ok2, _ = quality.quality_ok("Привет" * 200, {"min_chars": 100, "max_chars": 10000,
                                                  "max_uppercase_ratio": 0.3, "max_emoji_ratio": 0.15})
    assert ok2


def test_redact_pii_removes_phone_email():
    text = "Звоните +7 999 111 22 33 или пишите john.doe@example.com"
    red = quality.redact_pii(text)
    assert "+7" not in red
    assert "@example.com" not in red


def test_simhash_similar_texts():
    a = dedup.simhash("Он пришёл домой и увидел дневник на столе")
    b = dedup.simhash("Он пришёл домой и увидел дневник на столе.")
    c = dedup.simhash("В космосе нет звука и давления")
    assert dedup.hamming(a, b) < dedup.hamming(a, c)
