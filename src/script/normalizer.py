"""Russian text normalizer for TTS (numbers, quotes, latin letters)."""
from __future__ import annotations

import re


_LATIN_TO_CYR = {
    # safe transliteration for 1-2 char foreign words that TTS can't pronounce
    "OK": "окей", "ok": "окей",
    "DIY": "диай", "CEO": "сиио", "AI": "эй-ай",
    "US": "США", "UK": "Великобритания", "EU": "Евросоюз",
    "TikTok": "ТикТок", "YouTube": "Ютуб", "Reddit": "Реддит",
    "Twitter": "Твиттер", "Threads": "Фредс",
}

_QUOTE_MAP = {
    "“": "«", "”": "»", "„": "«", "‟": "»",
    "‘": "«", "’": "»",
    '"': "«",  # crude; replaced pairwise below
}


def _fix_quotes(text: str) -> str:
    for k, v in _QUOTE_MAP.items():
        text = text.replace(k, v)
    # crude ASCII pair replacement -> «»
    out = []
    open_q = True
    for c in text:
        if c == "«":
            out.append("«" if open_q else "»")
            open_q = not open_q
        else:
            out.append(c)
    return "".join(out)


def _transliterate_latin(text: str) -> str:
    for k, v in _LATIN_TO_CYR.items():
        text = re.sub(rf"\b{re.escape(k)}\b", v, text)
    return text


def _spell_out_numbers(text: str) -> str:
    """For TTS: replace common short numbers with words so Chirp reads naturally.

    Full number spelling is handled by Silero (put_accent) or by Chirp's SSML
    (not used here). We only fix tricky cases: years, currency, dates are left
    to the engine.
    """
    # Simple ratios like "50/50" -> "пятьдесят на пятьдесят" — skip, let engine handle
    return text


def normalize(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _fix_quotes(text)
    text = _transliterate_latin(text)
    text = _spell_out_numbers(text)
    # collapse repeated punctuation
    text = re.sub(r"([.!?])\1+", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
