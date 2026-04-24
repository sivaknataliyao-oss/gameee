"""Typed models — the vocabulary of the whole pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source(str, Enum):
    REDDIT = "reddit"
    TWITTER = "twitter"
    THREADS = "threads"


class RightsStatus(str, Enum):
    NONE = "none"
    ASKED = "asked"
    GRANTED = "granted"
    DENIED = "denied"
    TIMEOUT = "timeout"
    NOT_REQUIRED = "not_required"  # e.g. user's own content


class Lang(str, Enum):
    RU = "ru"
    EN = "en"
    OTHER = "other"


class LengthProfile(str, Enum):
    SHORT = "short"   # 5–10 min long-form
    LONG = "long"     # 15–25 min long-form


class Metrics(BaseModel):
    upvotes: int = 0
    comments: int = 0
    awards: int = 0
    favorites: int = 0    # twitter
    retweets: int = 0
    reposts: int = 0      # threads
    views: int = 0
    upvote_ratio: float | None = None


class Story(BaseModel):
    id: str                      # stable hash, e.g. "reddit:t3_xxxxx"
    source: Source
    source_id: str               # platform-native id
    permalink: str
    author: str | None = None
    title: str = ""
    text: str = ""
    lang_detected: Lang = Lang.OTHER
    nsfw: bool = False
    created_at: datetime
    fetched_at: datetime = Field(default_factory=_utcnow)
    metrics: Metrics = Field(default_factory=Metrics)
    growth_score: float = 0.0
    long_form_potential: float = 0.0


class Scene(BaseModel):
    """A visually coherent group: one key image + several variations on it."""

    label: str                   # human-readable, e.g. "night-desk-diary"
    prompts: list[str]           # 3–5 related prompts (same subject, varied angle/light)
    chapter_index: int = 0       # which chapter this scene belongs to (0 = intro)


class ProcessedStory(BaseModel):
    """Output of src/script/llm.py — everything needed for rendering."""

    story_id: str
    title_variants: list[str]
    selected_title: str
    hook: str
    cleaned_text: str            # may be translation if source was EN
    script_with_markers: str     # contains [HOOK]/[CHAPTER_N]/[CLIFFHANGER_N]/[OUTRO]
    chapters: list["Chapter"]
    keywords: list[str]
    scenes: list[Scene] = []     # preferred over flat image_prompts
    image_prompts: list[str]     # kept for backward compat / fallback
    tone: str = "neutral"
    estimated_minutes: float = 0.0
    profile: LengthProfile = LengthProfile.SHORT


class Chapter(BaseModel):
    index: int
    hook: str                    # 1–3s opener, used for shorts
    body: str
    cliffhanger: str = ""


class Permission(BaseModel):
    story_id: str
    author: str | None
    status: RightsStatus = RightsStatus.NONE
    asked_at: datetime | None = None
    responded_at: datetime | None = None
    text: str = ""               # full permission/denial text
    evidence_url: str | None = None


class RenderArtifacts(BaseModel):
    story_id: str
    audio_long: Optional[str] = None           # absolute path
    audio_chapters: list[str] = []
    subtitles_ass: Optional[str] = None
    typewriter_png_dir: Optional[str] = None
    slideshow_long_mp4: Optional[str] = None
    long_video_mp4: Optional[str] = None
    shorts_mp4: list[str] = []
    tiktok_mp4: list[str] = []
    thumbnail: Optional[str] = None


class UploadResult(BaseModel):
    platform: str                # youtube | instagram | tiktok
    video_id: str | None = None
    url: str | None = None
    scheduled_for: datetime | None = None
    status: str = "pending"      # pending | uploaded | failed | manual


Chapter.model_rebuild()
ProcessedStory.model_rebuild()
