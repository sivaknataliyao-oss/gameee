"""NSFW + toxicity filter: cheap keyword pass, safe default."""
from __future__ import annotations

from src.core.models import Story


def is_nsfw(story: Story, cfg: dict) -> tuple[bool, str]:
    """Return (blocked, reason)."""
    if cfg.get("block_source_flag", True) and story.nsfw:
        return True, "source_nsfw_flag"

    text = f"{story.title}\n{story.text}".lower()
    for kw in cfg.get("block_keywords_ru", []) + cfg.get("block_keywords_en", []):
        if kw.lower() in text:
            return True, f"keyword:{kw}"

    return False, ""
