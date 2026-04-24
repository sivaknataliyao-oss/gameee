"""Run all filters in order, returning (accept, reason)."""
from __future__ import annotations

from src.core import config
from src.core.models import Story
from src.core.storage import recent_simhashes
from src.filters import dedup, language, monetization, nsfw, quality


def accept(story: Story) -> tuple[bool, str]:
    cfg = config.filters()

    # 1) NSFW
    blocked, reason = nsfw.is_nsfw(story, cfg.get("nsfw", {}))
    if blocked:
        return False, f"nsfw:{reason}"

    # 2) Length (quality also checks it, but do a cheap early check)
    text = story.text or story.title
    if not quality.length_ok(text, cfg.get("length", {"min_chars": 0, "max_chars": 1_000_000})):
        return False, "length"

    # 3) Language
    lang, conf = language.detect(text)
    story.lang_detected = lang
    if not language.allowed(lang, conf, cfg.get("language", {})):
        return False, f"lang:{lang.value}@{conf:.2f}"

    # 4) Quality
    ok, q_reason = quality.quality_ok(text, cfg.get("length", {}) | cfg.get("quality", {}))
    if not ok:
        return False, f"quality:{q_reason}"

    # 5) Dedup — reject near-duplicates of stories seen in the recent window.
    dcfg = cfg.get("dedup", {}) or {}
    if dcfg.get("enabled", True):
        shingle = int(dcfg.get("shingle_size", 6))
        threshold = int(dcfg.get("simhash_threshold", 4))
        history = int(dcfg.get("history_days", 60))
        our_hash = dedup.simhash(text, k=shingle)
        object.__setattr__(story, "_simhash", our_hash)
        for sid, other in recent_simhashes(since_days=history):
            if sid == story.id:
                continue
            if dedup.hamming(our_hash, other) <= threshold:
                return False, f"dedup:~{sid}"

    # 6) Monetization pre-filter (LLM classifier). Fail-open if LLM unavailable.
    mcfg = cfg.get("monetization", {}) or {}
    if mcfg.get("enabled", True):
        min_conf = float(mcfg.get("min_confidence_to_block", 0.7))
        verdict = monetization.classify(text, title=story.title)
        if not verdict.friendly and verdict.confidence >= min_conf:
            return False, f"monetization:{verdict.risk_category}"

    return True, "ok"
