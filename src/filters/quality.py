"""Quality gates: length, uppercase ratio, emoji spam, PII redaction."""
from __future__ import annotations

import re


_EMOJI = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F02F]", re.UNICODE
)
_PHONE = re.compile(r"(?:\+?\d[\s\-()]*){9,15}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def length_ok(text: str, cfg: dict) -> bool:
    n = len(text)
    return cfg["min_chars"] <= n <= cfg["max_chars"]


def uppercase_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    up = sum(1 for c in letters if c.isupper())
    return up / len(letters)


def emoji_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(_EMOJI.findall(text)) / max(1, len(text))


def redact_pii(text: str) -> str:
    text = _PHONE.sub("[номер удалён]", text)
    text = _EMAIL.sub("[email removed]", text)
    return text


def quality_ok(text: str, cfg: dict) -> tuple[bool, str]:
    if not length_ok(text, cfg):
        return False, "length"
    if uppercase_ratio(text) > cfg.get("max_uppercase_ratio", 0.3):
        return False, "uppercase"
    if emoji_ratio(text) > cfg.get("max_emoji_ratio", 0.15):
        return False, "emoji"
    return True, ""
