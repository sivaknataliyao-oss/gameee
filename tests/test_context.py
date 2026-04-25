"""Tests for Context model and RunOptions location."""
from datetime import datetime, timezone
from pathlib import Path

from src.core.context import (
    ChapterRange,
    Context,
    CritiqueResult,
    PlatformMetadata,
    RunOptions,
    SegmentAudio,
)
from src.core.models import LengthProfile, Lang, Metrics, Source, Story


def _story() -> Story:
    return Story(
        id="reddit:abc",
        source=Source.REDDIT,
        source_id="abc",
        permalink="https://example",
        title="t",
        text="x" * 400,
        lang_detected=Lang.RU,
        created_at=datetime.now(timezone.utc),
        metrics=Metrics(upvotes=1),
    )


def test_context_minimal_construction(tmp_path: Path) -> None:
    ctx = Context(
        run_id=1,
        story_id="reddit:abc",
        run_dir=tmp_path,
        story=_story(),
        opts=RunOptions(),
    )
    assert ctx.brand == "default"
    assert ctx.intro_offset_sec == 0.0
    assert ctx.shorts == []
    assert ctx.thumbnail_variants == []
    assert ctx.processed is None


def test_context_progressive_fill(tmp_path: Path) -> None:
    ctx = Context(
        run_id=1, story_id="reddit:abc", run_dir=tmp_path,
        story=_story(), opts=RunOptions(),
    )
    ctx.chapter_ranges = [ChapterRange(start=0.0, end=12.5, hook="hook 1")]
    ctx.long_video = tmp_path / "long.mp4"
    assert ctx.chapter_ranges[0].end == 12.5
    # round-trip JSON for cache marshaling later
    payload = ctx.model_dump_json()
    restored = Context.model_validate_json(payload)
    assert restored.chapter_ranges[0].hook == "hook 1"


def test_run_options_defaults_match_legacy() -> None:
    opts = RunOptions()
    assert opts.research_mode is False
    assert opts.publish_youtube is False
    assert opts.tiktok_package is True
    assert opts.enqueue_schedule is True
    assert opts.ab_test_first_short is True
    assert opts.intro_stinger is True
    assert opts.loop_hook is True
    assert opts.profile == LengthProfile.SHORT


def test_segment_audio_and_critique_models() -> None:
    sa = SegmentAudio(kind="hook", index=0, text="привет",
                      path="/tmp/a.wav", duration_sec=2.5)
    assert sa.duration_sec == 2.5

    cr = CritiqueResult(
        issues=[{"kind": "filler", "location": "[CHAPTER_2]", "note": "tighten"}],
        revised_script_with_markers="[HOOK]...",
        revised_title_variants=None,
    )
    assert cr.issues[0]["kind"] == "filler"
    assert cr.revised_title_variants is None


def test_platform_metadata_per_platform_keys() -> None:
    pm = PlatformMetadata(
        youtube_long={"title": "T", "description": "D", "hashtags": ["x"]},
        youtube_shorts={"title": "T", "description": "D", "hashtags": ["x"]},
        tiktok={"caption": "c", "hashtags": ["x"]},
        instagram={"caption": "c", "hashtags": ["x"]},
    )
    assert pm.tiktok["caption"] == "c"


def test_run_options_importable_from_legacy_alias() -> None:
    """Existing code does `from src.pipeline import RunOptions` — must still work."""
    from src.pipeline import RunOptions as Legacy
    assert Legacy is RunOptions
