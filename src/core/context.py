"""Per-story state passed through pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.core.models import LengthProfile, ProcessedStory, Story


@dataclass
class RunOptions:
    research_mode: bool = False
    publish_youtube: bool = False
    tiktok_package: bool = True
    enqueue_schedule: bool = True
    ab_test_first_short: bool = True
    intro_stinger: bool = True
    loop_hook: bool = True
    profile: LengthProfile = LengthProfile.SHORT


class SegmentAudio(BaseModel):
    """One TTS segment paired with its measured duration."""
    kind: str                       # "hook" | "chapter" | "outro"
    index: int
    text: str
    path: Path
    duration_sec: float


class ChapterRange(BaseModel):
    """Time window of a chapter inside the final narration timeline."""
    start: float
    end: float
    hook: str = ""


class CritiqueResult(BaseModel):
    """Output of the (future) self-critique stage."""
    issues: list[dict[str, str]] = Field(default_factory=list)
    revised_script_with_markers: str | None = None
    revised_title_variants: list[str] | None = None


class PlatformMetadata(BaseModel):
    """Per-platform titles / captions / hashtags from the LLM."""
    youtube_long: dict[str, Any] | None = None
    youtube_shorts: dict[str, Any] | None = None
    tiktok: dict[str, Any] | None = None
    instagram: dict[str, Any] | None = None


class Context(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: int
    story_id: str
    brand: str = "default"
    run_dir: Path
    story: Story
    opts: RunOptions

    # Progressively filled by stages:
    processed: ProcessedStory | None = None
    critique: CritiqueResult | None = None
    segments_audio: list[SegmentAudio] = Field(default_factory=list)
    chapter_ranges: list[ChapterRange] = Field(default_factory=list)
    narration_final: Path | None = None
    images: list[Path] = Field(default_factory=list)
    long_video: Path | None = None
    intro_offset_sec: float = 0.0
    thumbnail_variants: list[Path] = Field(default_factory=list)
    shorts: list[Path] = Field(default_factory=list)
    ab_short_variants: list[tuple[str, Path]] = Field(default_factory=list)
    platform_metadata: PlatformMetadata | None = None
    packages: list[Path] = Field(default_factory=list)
