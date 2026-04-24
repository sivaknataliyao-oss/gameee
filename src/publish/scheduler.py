"""Publishing scheduler: spread renders across days instead of burst-posting.

Uses a `ScheduledPostRow` table. Plans are generated right after rendering,
and a `dispatch` loop picks due items and publishes them.

Cadence defaults (override in config/channel.yaml -> schedule):
    long_youtube: one per 7 days
    youtube_shorts: one per 24 hours
    tiktok:        one per 24 hours (prepared packages; actual upload is manual)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, select

from src.core import config
from src.core.storage import engine, session

log = logging.getLogger(__name__)


class ScheduledPostRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    story_id: str = Field(index=True)
    platform: str                        # youtube | youtube_shorts | tiktok | instagram
    video_path: str
    title: str
    description: str
    hashtags_json: str = "[]"
    planned_for: datetime
    status: str = "planned"              # planned | ready | uploaded | failed | skipped
    uploaded_at: datetime | None = None
    error: str | None = None


def _ensure_table() -> None:
    SQLModel.metadata.create_all(engine())


@dataclass
class Cadence:
    long_youtube_days: int = 7
    youtube_shorts_hours: int = 24
    tiktok_hours: int = 24
    instagram_hours: int = 48
    preferred_hour_utc: int = 15         # ~6pm Moscow / ~10am NYC


def cadence_from_config() -> Cadence:
    s = config.channel().get("schedule", {})
    return Cadence(
        long_youtube_days=int(s.get("long_youtube_days", 7)),
        youtube_shorts_hours=int(s.get("youtube_shorts_hours", 24)),
        tiktok_hours=int(s.get("tiktok_hours", 24)),
        instagram_hours=int(s.get("instagram_hours", 48)),
        preferred_hour_utc=int(s.get("preferred_hour_utc", 15)),
    )


def _next_slot(platform: str, cadence: Cadence) -> datetime:
    """Next slot after the latest planned post on that platform."""
    _ensure_table()
    with Session(engine()) as s:
        q = select(ScheduledPostRow).where(ScheduledPostRow.platform == platform).order_by(
            ScheduledPostRow.planned_for.desc()
        ).limit(1)
        last = s.exec(q).first()

    now = datetime.now(timezone.utc)
    if platform == "youtube":
        delta = timedelta(days=cadence.long_youtube_days)
    elif platform == "youtube_shorts":
        delta = timedelta(hours=cadence.youtube_shorts_hours)
    elif platform == "tiktok":
        delta = timedelta(hours=cadence.tiktok_hours)
    else:
        delta = timedelta(hours=cadence.instagram_hours)

    base = (last.planned_for if last else now)
    if base < now:
        base = now
    slot = base + delta
    slot = slot.replace(hour=cadence.preferred_hour_utc, minute=0, second=0, microsecond=0)
    if slot < now:
        slot += timedelta(days=1)
    return slot


def enqueue(story_id: str, platform: str, video_path: Path, title: str,
            description: str, hashtags: list[str]) -> ScheduledPostRow:
    import json as _json
    _ensure_table()
    slot = _next_slot(platform, cadence_from_config())
    row = ScheduledPostRow(
        story_id=story_id,
        platform=platform,
        video_path=str(video_path),
        title=title,
        description=description,
        hashtags_json=_json.dumps(hashtags, ensure_ascii=False),
        planned_for=slot,
    )
    with session() as s:
        s.add(row)
        s.flush()
    log.info("enqueued %s for %s at %s", platform, story_id, slot.isoformat())
    return row


def due_posts(now: datetime | None = None) -> list[ScheduledPostRow]:
    _ensure_table()
    now = now or datetime.now(timezone.utc)
    with Session(engine()) as s:
        q = select(ScheduledPostRow).where(
            ScheduledPostRow.status == "planned",
            ScheduledPostRow.planned_for <= now,
        ).order_by(ScheduledPostRow.planned_for.asc())
        return list(s.exec(q))


def mark_uploaded(row_id: int, ok: bool, error: str | None = None) -> None:
    with session() as s:
        row = s.get(ScheduledPostRow, row_id)
        if not row:
            return
        row.status = "uploaded" if ok else "failed"
        row.error = error
        row.uploaded_at = datetime.now(timezone.utc)


def pending_summary() -> dict[str, int]:
    _ensure_table()
    out: dict[str, int] = {}
    with Session(engine()) as s:
        for row in s.exec(select(ScheduledPostRow).where(ScheduledPostRow.status == "planned")):
            out[row.platform] = out.get(row.platform, 0) + 1
    return out
