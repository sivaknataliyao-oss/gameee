"""Story scoring: growth velocity + long-form potential."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from src.core.models import Metrics, Source, Story


def _age_minutes(created_at: datetime) -> float:
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return max(1.0, (now - created_at).total_seconds() / 60.0)


def growth_score(source: Source, m: Metrics, created_at: datetime) -> float:
    """Normalized velocity score. Higher = more 'on fire'."""
    age = _age_minutes(created_at)
    # Clamp age: don't reward very fresh posts too much (noise)
    age = max(age, 10.0)

    if source == Source.REDDIT:
        vel = (m.upvotes + 2 * m.comments) / age
        ratio = m.upvote_ratio or 0.9
        return vel * ratio
    if source == Source.TWITTER:
        vel = (m.favorites + 3 * m.retweets) / age
        return vel
    if source == Source.THREADS:
        vel = (m.favorites + 2 * m.reposts + m.comments) / age
        return vel
    return 0.0


# -------- Long-form potential --------

# Markers that suggest multi-act story structure
_STORY_BEATS_RU = [
    "но тогда", "однако", "неожиданно", "через год", "через неделю",
    "утром", "вечером", "оказалось", "спустя", "в итоге", "и вот",
]
_STORY_BEATS_EN = [
    "but then", "however", "suddenly", "a year later", "a week later",
    "in the morning", "turns out", "eventually", "in the end",
    "and that's when", "meanwhile",
]


def long_form_potential(story: Story) -> float:
    """
    Heuristic 0..1 estimate (LLM can override in script stage).
    Favors: multi-beat structure, length, dialogue, concrete details.
    """
    text = (story.text or "").lower()
    if not text:
        return 0.0

    score = 0.0

    # Length proxy: ~500 chars/minute of speech in Russian.
    length_factor = min(len(text) / 5000.0, 1.0)  # saturates at ~10min
    score += 0.35 * length_factor

    # Story beats
    beats = sum(1 for m in (_STORY_BEATS_RU + _STORY_BEATS_EN) if m in text)
    score += 0.25 * min(beats / 6.0, 1.0)

    # Dialogue presence (rough proxy)
    dialogue = text.count("— ") + text.count(" — ") + text.count('"')
    score += 0.15 * min(dialogue / 10.0, 1.0)

    # Numbers / specifics -> grounded narrative
    digits = sum(c.isdigit() for c in text)
    score += 0.10 * min(digits / 40.0, 1.0)

    # Engagement on source
    m = story.metrics
    engagement = math.log1p(m.upvotes + m.favorites + m.comments * 2)
    score += 0.15 * min(engagement / 12.0, 1.0)

    return min(score, 1.0)
