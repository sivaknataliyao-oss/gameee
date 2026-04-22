"""Run all filters in order, returning (accept, reason)."""
from __future__ import annotations

from src.core import config
from src.core.models import Lang, Story
from src.filters import language, nsfw, quality


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

    return True, "ok"
