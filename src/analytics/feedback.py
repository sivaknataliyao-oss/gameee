"""Compute engagement priors from historical metrics and apply to scoring.

Idea: a story whose keywords overlap with previously-successful videos gets a
small multiplier on growth_score, so we learn "romance cliffhanger" > "petty"
on this particular channel.

The prior is a `keyword_weight`: EWMA of avg_view_percentage over videos that
contain the keyword (or tone) in their metadata.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from src.analytics.metrics_store import VideoMetricsRow
from src.core.config import runs_dir
from src.core.storage import StoryRow, engine

log = logging.getLogger(__name__)


def _prior_path() -> Path:
    return runs_dir().parent / "engagement_priors.json"


def recompute_priors() -> dict[str, float]:
    """Walk video metrics, join to source stories' keywords, build a weight map."""
    with Session(engine()) as s:
        metrics = list(s.exec(select(VideoMetricsRow)))
        stories = {r.id: r for r in s.exec(select(StoryRow))}

    kw_scores: dict[str, list[float]] = defaultdict(list)
    for m in metrics:
        if not m.story_id or m.story_id not in stories:
            continue
        # avg_view_percentage is a decent thin proxy; 1.0 would mean full watch.
        score = max(0.0, min(m.average_view_percentage / 100.0, 1.0))
        # Pull keywords from story title/text (we don't persist ProcessedStory yet,
        # so use title tokens as a coarse topical signal).
        title = stories[m.story_id].title.lower()
        for tok in title.split():
            tok = "".join(ch for ch in tok if ch.isalnum())
            if len(tok) >= 4:
                kw_scores[tok].append(score)

    # EWMA-style collapse: mean × log(1 + count) to reward consistency.
    import math
    priors: dict[str, float] = {}
    for kw, scores in kw_scores.items():
        m = sum(scores) / len(scores)
        priors[kw] = float(m * math.log1p(len(scores)))

    _prior_path().parent.mkdir(parents=True, exist_ok=True)
    _prior_path().write_text(
        json.dumps({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "priors": priors,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("recomputed priors for %d keywords", len(priors))
    return priors


def load_priors() -> dict[str, float]:
    if not _prior_path().exists():
        return {}
    try:
        data = json.loads(_prior_path().read_text(encoding="utf-8"))
        return dict(data.get("priors") or {})
    except Exception:
        return {}


def prior_multiplier(title: str, text: str = "") -> float:
    """Multiplier in [0.75, 1.50] based on matching keywords."""
    priors = load_priors()
    if not priors:
        return 1.0
    sample = (title + " " + text).lower()
    matched: list[float] = []
    for kw, w in priors.items():
        if kw in sample:
            matched.append(w)
    if not matched:
        return 1.0
    avg = sum(matched) / len(matched)
    # Clamp to sane range so we never drop a genuinely-fresh story to zero.
    return max(0.75, min(1.5, 1.0 + (avg - 0.5) * 0.6))
