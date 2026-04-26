"""SQLite persistence via SQLModel. Stories, permissions, runs, uploads."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import BigInteger
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, Session, SQLModel, create_engine, select

from src.core.config import db_path
from src.core.models import RightsStatus, Source


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UInt64(TypeDecorator):
    """Store unsigned 64-bit integers in SQLite as signed int64 (two's complement)."""

    impl = BigInteger
    cache_ok = True

    _MASK = 0xFFFF_FFFF_FFFF_FFFF
    _SIGN = 0x8000_0000_0000_0000

    def process_bind_param(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        v = int(value) & self._MASK
        # Convert to signed int64 for storage
        if v >= self._SIGN:
            v -= (self._MASK + 1)
        return v

    def process_result_value(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        # Convert back to unsigned
        return int(value) & self._MASK


class StoryRow(SQLModel, table=True):
    id: str = Field(primary_key=True)
    source: str
    source_id: str
    permalink: str
    author: str | None = None
    title: str
    text: str
    lang_detected: str = "other"
    nsfw: bool = False
    created_at: datetime
    fetched_at: datetime = Field(default_factory=_utcnow)
    metrics_json: str = "{}"
    growth_score: float = 0.0
    long_form_potential: float = 0.0
    simhash: int | None = Field(default=None, index=True, sa_type=UInt64)
    used: bool = False            # marked after successful publish
    blocked_reason: str | None = None


class PermissionRow(SQLModel, table=True):
    story_id: str = Field(primary_key=True)
    author: str | None = None
    status: str = RightsStatus.NONE.value
    asked_at: datetime | None = None
    responded_at: datetime | None = None
    text: str = ""
    evidence_url: str | None = None


class UploadRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    story_id: str
    platform: str
    video_id: str | None = None
    url: str | None = None
    status: str = "pending"
    created_at: datetime = Field(default_factory=_utcnow)


class RunRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    story_id: str
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None
    status: str = "running"
    artifacts_dir: str | None = None
    error: str | None = None


_engine = None


def engine():
    global _engine
    if _engine is None:
        p = db_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{p}", echo=False)
        SQLModel.metadata.create_all(_engine)
        from sqlalchemy import text
        with _engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_storyrow_simhash "
                "ON storyrow (simhash)"
            ))
            conn.commit()
    return _engine


@contextmanager
def session() -> Iterator[Session]:
    with Session(engine()) as s:
        yield s
        s.commit()


# -------- Story helpers --------

def upsert_story(row: StoryRow) -> None:
    with session() as s:
        existing = s.get(StoryRow, row.id)
        if existing is None:
            s.add(row)
        else:
            # refresh volatile fields
            for f in ("metrics_json", "growth_score", "long_form_potential",
                      "text", "title", "simhash"):
                setattr(existing, f, getattr(row, f))


def recent_simhashes(since_days: int = 60) -> list[tuple[str, int]]:
    """Return (story_id, simhash) for non-null simhashes fetched in the window."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    with session() as s:
        q = select(StoryRow.id, StoryRow.simhash).where(
            StoryRow.simhash.is_not(None),
            StoryRow.fetched_at >= cutoff,
        )
        return [(sid, int(h)) for sid, h in s.exec(q) if h is not None]


def get_story(story_id: str) -> StoryRow | None:
    with session() as s:
        return s.get(StoryRow, story_id)


def top_unused(limit: int = 20, min_score: float = 1.0, source: Source | None = None) -> list[StoryRow]:
    with session() as s:
        q = select(StoryRow).where(StoryRow.used == False, StoryRow.growth_score >= min_score)  # noqa: E712
        if source is not None:
            q = q.where(StoryRow.source == source.value)
        q = q.order_by(StoryRow.growth_score.desc()).limit(limit)
        return list(s.exec(q))


def mark_used(story_id: str) -> None:
    with session() as s:
        row = s.get(StoryRow, story_id)
        if row:
            row.used = True


def block_story(story_id: str, reason: str) -> None:
    with session() as s:
        row = s.get(StoryRow, story_id)
        if row:
            row.blocked_reason = reason


# -------- Permissions --------

def get_permission(story_id: str) -> PermissionRow | None:
    with session() as s:
        return s.get(PermissionRow, story_id)


def upsert_permission(row: PermissionRow) -> None:
    with session() as s:
        existing = s.get(PermissionRow, row.story_id)
        if existing is None:
            s.add(row)
        else:
            for f in ("author", "status", "asked_at", "responded_at", "text", "evidence_url"):
                v = getattr(row, f)
                if v is not None:
                    setattr(existing, f, v)


# -------- Runs / uploads --------

def start_run(story_id: str, artifacts_dir: Path) -> int:
    row = RunRow(story_id=story_id, artifacts_dir=str(artifacts_dir))
    with session() as s:
        s.add(row)
        s.flush()
        return row.id  # type: ignore


def finish_run(run_id: int, status: str, error: str | None = None) -> None:
    with session() as s:
        row = s.get(RunRow, run_id)
        if row:
            row.status = status
            row.finished_at = _utcnow()
            row.error = error


def add_upload(story_id: str, platform: str, status: str = "pending",
               video_id: str | None = None, url: str | None = None) -> None:
    with session() as s:
        s.add(UploadRow(story_id=story_id, platform=platform, status=status,
                        video_id=video_id, url=url))


def metrics_to_json(m: dict) -> str:
    return json.dumps(m, ensure_ascii=False, default=str)


def has_near_duplicate(
    our_hash: int,
    *,
    threshold: int = 4,
    since_days: int = 60,
    batch: int = 500,
) -> str | None:
    """Return the id of a stored story whose simhash is within `threshold`
    Hamming distance of `our_hash`, scanning the last `since_days` days in
    pages of `batch` rows. Short-circuits on first match, so the average
    case is O(K) where K is the page containing the duplicate.
    """
    from datetime import timedelta
    from src.filters.dedup import hamming
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    offset = 0
    while True:
        with session() as s:
            q = (
                select(StoryRow.id, StoryRow.simhash)
                .where(
                    StoryRow.simhash.is_not(None),
                    StoryRow.fetched_at >= cutoff,
                )
                .order_by(StoryRow.fetched_at.desc())
                .offset(offset)
                .limit(batch)
            )
            rows = list(s.exec(q))
        if not rows:
            return None
        for sid, h in rows:
            if h is None:
                continue
            if hamming(our_hash, int(h)) <= threshold:
                return sid
        offset += batch
