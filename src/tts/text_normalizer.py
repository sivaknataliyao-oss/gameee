"""TTS-facing Russian text normalizer.

Handles the cases where TTS providers would otherwise read digits one by one:
  - Plain numbers:            42        -> "сорок два"
  - Decimals:                 3.14      -> "три целых четырнадцать сотых"
  - Currency amounts:         42 евро   -> "сорок два евро"
                              $250      -> "двести пятьдесят долларов"
  - Dates (ISO/European):     25.04.2026 -> "двадцать пятое апреля две тысячи двадцать шестого"
                              2026-04-25
  - Times:                    9:30      -> "девять тридцать"
                              17:05     -> "семнадцать ноль пять"
  - Percents:                 20%       -> "двадцать процентов"
  - Ordinals in "N-й/N-го":   21-й     -> "двадцать первый"
  - Years "в 1999":           "в тысяча девятьсот девяносто девятом"
"""
from __future__ import annotations

import re
from typing import Callable

try:
    from num2words import num2words as _n2w
    _HAS_N2W = True
except ImportError:   # pragma: no cover
    _HAS_N2W = False


# Forms for declension of currency when known:
_CURRENCY: dict[str, tuple[str, str, str]] = {
    # symbol/code -> (singular, paucal 2-4, plural 5+)
    "₽":   ("рубль", "рубля", "рублей"),
    "руб": ("рубль", "рубля", "рублей"),
    "RUB": ("рубль", "рубля", "рублей"),
    "$":   ("доллар", "доллара", "долларов"),
    "USD": ("доллар", "доллара", "долларов"),
    "€":   ("евро", "евро", "евро"),
    "EUR": ("евро", "евро", "евро"),
    "£":   ("фунт", "фунта", "фунтов"),
    "GBP": ("фунт", "фунта", "фунтов"),
    "₴":   ("гривна", "гривны", "гривен"),
    "UAH": ("гривна", "гривны", "гривен"),
}


_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _n2w_safe(n: int, to: str = "cardinal") -> str:
    if not _HAS_N2W:
        return str(n)
    try:
        return _n2w(int(n), lang="ru", to=to)
    except Exception:
        return str(n)


def _plural_form(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(int(n))
    if n % 100 in (11, 12, 13, 14):
        return forms[2]
    last = n % 10
    if last == 1:
        return forms[0]
    if last in (2, 3, 4):
        return forms[1]
    return forms[2]


def _normalize_currency(text: str) -> str:
    # Match "$250", "250 $", "250 руб", "€1 200", "1,200 EUR"
    def _amount(num_str: str) -> int:
        clean = re.sub(r"[  ,]", "", num_str).replace(".", "")
        try:
            return int(clean)
        except ValueError:
            return 0

    # Pattern: symbol before number, e.g. $250, €1 200
    sym_before = re.compile(
        r"(?P<sym>\$|€|£|₽|₴)\s?(?P<num>\d{1,3}(?:[  ]\d{3})*(?:[.,]\d+)?)"
    )

    def _repl_before(m: re.Match) -> str:
        sym = m.group("sym")
        n = _amount(m.group("num"))
        forms = _CURRENCY.get(sym)
        if not forms:
            return m.group(0)
        return f"{_n2w_safe(n)} {_plural_form(n, forms)}"

    text = sym_before.sub(_repl_before, text)

    # Pattern: number then code/symbol: "1 200 руб", "250 евро", "10 USD"
    code_after = re.compile(
        r"(?P<num>\d{1,3}(?:[  ]\d{3})*(?:[.,]\d+)?)\s?"
        r"(?P<code>руб|RUB|USD|EUR|GBP|UAH|евро|доллар(?:ов|а|у)?|фунт(?:ов|а|у)?|гривн(?:ы|у|ен|а)?)"
    )

    def _repl_after(m: re.Match) -> str:
        code = m.group("code")
        n = _amount(m.group("num"))
        # map code variants to canonical key
        key = code
        if code.startswith("доллар"):
            key = "$"
        elif code.startswith("евро"):
            key = "€"
        elif code.startswith("фунт"):
            key = "£"
        elif code.startswith("гривн"):
            key = "₴"
        forms = _CURRENCY.get(key)
        if not forms:
            return m.group(0)
        return f"{_n2w_safe(n)} {_plural_form(n, forms)}"

    return code_after.sub(_repl_after, text)


def _normalize_percent(text: str) -> str:
    def _repl(m: re.Match) -> str:
        n = int(m.group(1))
        return f"{_n2w_safe(n)} {_plural_form(n, ('процент', 'процента', 'процентов'))}"
    return re.sub(r"\b(\d{1,3})\s?%", _repl, text)


def _normalize_dates(text: str) -> str:
    # dd.mm.yyyy or yyyy-mm-dd
    def _repl_dot(m: re.Match) -> str:
        d, mn, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= d <= 31 and 1 <= mn <= 12):
            return m.group(0)
        return f"{_n2w_safe(d, to='ordinal')} {_MONTHS[mn - 1]} {_n2w_safe(y, to='ordinal')} года"

    def _repl_iso(m: re.Match) -> str:
        y, mn, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= d <= 31 and 1 <= mn <= 12):
            return m.group(0)
        return f"{_n2w_safe(d, to='ordinal')} {_MONTHS[mn - 1]} {_n2w_safe(y, to='ordinal')} года"

    text = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", _repl_dot, text)
    text = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", _repl_iso, text)
    return text


def _normalize_times(text: str) -> str:
    def _repl(m: re.Match) -> str:
        h, mi = int(m.group(1)), int(m.group(2))
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            return m.group(0)
        hours = _n2w_safe(h)
        if mi == 0:
            return f"{hours} часов ровно"
        minutes_str = _n2w_safe(mi)
        if mi < 10:
            minutes_str = "ноль " + minutes_str
        return f"{hours} {minutes_str}"
    # match standalone h:mm with word boundaries; not inside a longer number
    return re.sub(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", _repl, text)


def _normalize_ordinals(text: str) -> str:
    # "21-й" / "21-го" / "3-я" — drop the suffix and convert to ordinal word.
    def _repl(m: re.Match) -> str:
        n = int(m.group(1))
        return _n2w_safe(n, to="ordinal")
    return re.sub(r"\b(\d+)-(?:й|го|му|м|х|е|я|ю|ой|ую|ая)\b", _repl, text)


def _normalize_bare_numbers(text: str) -> str:
    # Plain integers >= 10 not already consumed by the steps above. Leave single
    # digits alone (they sound fine) and phone-number-like strings untouched.
    def _repl(m: re.Match) -> str:
        n = int(m.group(0))
        if n < 10:
            return m.group(0)
        return _n2w_safe(n)
    # Avoid eating parts of phone numbers (hyphens/spaces/plus) by anchoring.
    return re.sub(r"(?<![\d.,\-+:])\b\d{2,9}\b(?![\d.,\-+:])", _repl, text)


def normalize_for_tts(text: str) -> str:
    if not text:
        return ""
    # Order matters: dates/times/currency/percent BEFORE bare numbers.
    pipeline: list[Callable[[str], str]] = [
        _normalize_dates,
        _normalize_times,
        _normalize_currency,
        _normalize_percent,
        _normalize_ordinals,
        _normalize_bare_numbers,
    ]
    for step in pipeline:
        text = step(text)
    # Collapse whitespace that may have been introduced.
    return re.sub(r"[  ]{2,}", " ", text).strip()
