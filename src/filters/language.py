"""Language detection. Uses lingua when available, falls back to char ratios."""
from __future__ import annotations

from functools import lru_cache

from src.core.models import Lang

try:
    from lingua import Language, LanguageDetectorBuilder  # type: ignore
    _HAS_LINGUA = True
except Exception:  # pragma: no cover
    _HAS_LINGUA = False


@lru_cache
def _detector():
    if not _HAS_LINGUA:
        return None
    return (
        LanguageDetectorBuilder.from_languages(
            Language.ENGLISH, Language.RUSSIAN, Language.UKRAINIAN
        )
        .with_preloaded_language_models()
        .build()
    )


def detect(text: str) -> tuple[Lang, float]:
    if not text:
        return Lang.OTHER, 0.0

    det = _detector()
    if det is not None:
        confidences = det.compute_language_confidence_values(text)
        if confidences:
            best = max(confidences, key=lambda c: c.value)
            mapping = {
                Language.ENGLISH: Lang.EN,
                Language.RUSSIAN: Lang.RU,
                Language.UKRAINIAN: Lang.OTHER,  # we treat UA as non-target for now
            }
            return mapping.get(best.language, Lang.OTHER), float(best.value)

    # fallback: character-class ratios
    cyr = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in text if "a" <= c.lower() <= "z")
    total = cyr + lat
    if total == 0:
        return Lang.OTHER, 0.0
    if cyr / total > 0.6:
        return Lang.RU, cyr / total
    if lat / total > 0.6:
        return Lang.EN, lat / total
    return Lang.OTHER, max(cyr, lat) / total


def allowed(lang: Lang, conf: float, cfg: dict) -> bool:
    if conf < cfg.get("min_confidence", 0.75):
        return False
    return lang.value in cfg.get("allowed", ["ru", "en"])
