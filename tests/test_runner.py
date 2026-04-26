"""Stage protocol and runner."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.core.context import Context, RunOptions
from src.core.models import Lang, Metrics, Source, Story
from src.pipeline.runner import run
from src.pipeline.stages.base import BaseStage


def _ctx(tmp: Path) -> Context:
    story = Story(
        id="reddit:abc", source=Source.REDDIT, source_id="abc",
        permalink="https://example", title="t", text="x" * 400,
        lang_detected=Lang.RU, created_at=datetime.now(timezone.utc),
        metrics=Metrics(upvotes=1),
    )
    return Context(run_id=1, story_id="reddit:abc", run_dir=tmp,
                   story=story, opts=RunOptions())


class _FakeStage(BaseStage):
    def __init__(self, name: str, *, cached: bool = False,
                 raises: Exception | None = None) -> None:
        self.name = name
        self._cached = cached
        self._raises = raises
        self.run_calls = 0
        self.clear_calls = 0

    def run(self, ctx: Context) -> Context:
        self.run_calls += 1
        if self._raises is not None:
            raise self._raises
        ctx.images.append(Path(f"/tmp/{self.name}.png"))
        return ctx

    def is_cached(self, ctx: Context) -> bool:
        return self._cached

    def clear(self, ctx: Context) -> None:
        self.clear_calls += 1


def test_runner_executes_stages_in_order(tmp_path: Path, monkeypatch) -> None:
    a, b = _FakeStage("a"), _FakeStage("b")
    monkeypatch.setattr("src.pipeline.runner.STAGES", [a, b])
    out = run(_ctx(tmp_path))
    assert a.run_calls == 1 and b.run_calls == 1
    assert out.images == [Path("/tmp/a.png"), Path("/tmp/b.png")]


def test_runner_skips_cached_stage(tmp_path: Path, monkeypatch) -> None:
    a = _FakeStage("a", cached=True)
    b = _FakeStage("b")
    monkeypatch.setattr("src.pipeline.runner.STAGES", [a, b])
    out = run(_ctx(tmp_path))
    assert a.run_calls == 0
    assert b.run_calls == 1
    assert out.images == [Path("/tmp/b.png")]


def test_runner_force_clears_cache_and_runs_stage(tmp_path: Path, monkeypatch) -> None:
    a = _FakeStage("a", cached=True)
    monkeypatch.setattr("src.pipeline.runner.STAGES", [a])
    run(_ctx(tmp_path), force={"a"})
    assert a.clear_calls == 1
    assert a.run_calls == 1


def test_runner_from_stage_slices(tmp_path: Path, monkeypatch) -> None:
    a, b, c = _FakeStage("a"), _FakeStage("b"), _FakeStage("c")
    monkeypatch.setattr("src.pipeline.runner.STAGES", [a, b, c])
    run(_ctx(tmp_path), from_stage="b")
    assert a.run_calls == 0 and b.run_calls == 1 and c.run_calls == 1


def test_runner_to_stage_slices_inclusive(tmp_path: Path, monkeypatch) -> None:
    a, b, c = _FakeStage("a"), _FakeStage("b"), _FakeStage("c")
    monkeypatch.setattr("src.pipeline.runner.STAGES", [a, b, c])
    run(_ctx(tmp_path), to_stage="b")
    assert a.run_calls == 1 and b.run_calls == 1 and c.run_calls == 0


def test_runner_raises_and_marks_run_failed(tmp_path: Path, monkeypatch) -> None:
    bad = _FakeStage("bad", raises=RuntimeError("boom"))
    monkeypatch.setattr("src.pipeline.runner.STAGES", [bad])
    finished: list[tuple[int, str, str | None]] = []
    monkeypatch.setattr("src.pipeline.runner.finish_run",
                        lambda rid, st, err=None: finished.append((rid, st, err)))
    with pytest.raises(RuntimeError):
        run(_ctx(tmp_path))
    assert finished == [(1, "failed", "bad: RuntimeError('boom')")]


def test_runner_marks_run_ok_on_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.pipeline.runner.STAGES", [_FakeStage("a")])
    finished: list[tuple[int, str, str | None]] = []
    monkeypatch.setattr("src.pipeline.runner.finish_run",
                        lambda rid, st, err=None: finished.append((rid, st, err)))
    run(_ctx(tmp_path))
    assert finished == [(1, "ok", None)]


def test_runner_unknown_from_stage_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("src.pipeline.runner.STAGES", [_FakeStage("a")])
    with pytest.raises(ValueError, match="unknown stage"):
        run(_ctx(tmp_path), from_stage="missing")


def test_legacy_monolith_stage_wraps_process_one(tmp_path: Path, monkeypatch) -> None:
    """LegacyMonolithStage.run() invokes process_one and populates ctx outputs."""
    from src.core.models import RenderArtifacts
    from src.pipeline.stages.legacy import LegacyMonolithStage

    captured: list = []

    def fake_process_one(story, opts):
        captured.append((story.id, opts.research_mode))
        return RenderArtifacts(
            story_id=story.id,
            audio_long=str(tmp_path / "n.wav"),
            audio_chapters=[str(tmp_path / "s00.wav")],
            subtitles_ass=None,
            typewriter_png_dir=str(tmp_path / "tw"),
            slideshow_long_mp4=str(tmp_path / "long.mp4"),
            long_video_mp4=str(tmp_path / "long.mp4"),
            shorts_mp4=[str(tmp_path / "short_01.mp4")],
            tiktok_mp4=[str(tmp_path / "short_01.mp4")],
            thumbnail=str(tmp_path / "thumb.jpg"),
        )

    monkeypatch.setattr("src.pipeline.stages.legacy.process_one", fake_process_one)
    stage = LegacyMonolithStage()
    ctx = _ctx(tmp_path)
    out = stage.run(ctx)
    assert captured == [("reddit:abc", False)]
    assert out.long_video == Path(tmp_path / "long.mp4")
    assert out.shorts == [Path(tmp_path / "short_01.mp4")]
    assert out.thumbnail_variants == [Path(tmp_path / "thumb.jpg")]
    assert stage.name == "legacy_monolith"


def test_legacy_monolith_stage_returns_ctx_when_process_one_returns_none(
    tmp_path: Path, monkeypatch,
) -> None:
    from src.pipeline.stages.legacy import LegacyMonolithStage
    monkeypatch.setattr("src.pipeline.stages.legacy.process_one",
                        lambda story, opts: None)
    stage = LegacyMonolithStage()
    out = stage.run(_ctx(tmp_path))
    assert out.long_video is None
    assert out.shorts == []
