"""Per-video performance rows fetched from YouTube Analytics."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, Session, SQLModel, select

from src.core.storage import engine, session


class VideoMetricsRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    story_id: str = Field(index=True)
    platform: str = "youtube"
    video_id: str = Field(index=True)
    views: int = 0
    watch_minutes: float = 0.0
    average_view_percentage: float = 0.0
    ctr: float = 0.0
    subscribers_gained: int = 0
    likes: int = 0
    dislikes: int = 0
    comments: int = 0
    pulled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _ensure() -> None:
    SQLModel.metadata.create_all(engine())


def upsert(row: VideoMetricsRow) -> None:
    _ensure()
    with session() as s:
        q = select(VideoMetricsRow).where(
            VideoMetricsRow.video_id == row.video_id,
            VideoMetricsRow.platform == row.platform,
        )
        existing = s.exec(q).first()
        if existing is None:
            s.add(row)
        else:
            for f in ("views", "watch_minutes", "average_view_percentage",
                      "ctr", "subscribers_gained", "likes", "dislikes",
                      "comments", "pulled_at"):
                setattr(existing, f, getattr(row, f))


def all_for_story(story_id: str) -> list[VideoMetricsRow]:
    _ensure()
    with Session(engine()) as s:
        q = select(VideoMetricsRow).where(VideoMetricsRow.story_id == story_id)
        return list(s.exec(q))


def latest() -> list[VideoMetricsRow]:
    _ensure()
    with Session(engine()) as s:
        q = select(VideoMetricsRow).order_by(VideoMetricsRow.pulled_at.desc()).limit(200)
        return list(s.exec(q))
