# Pipeline Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation layer for the stage-based pipeline (`Context` model, `Stage` protocol, `runner`), fix two known correctness bugs (scheduler race, O(N) dedup), add `cli health`, and switch logging to structured JSON — all without breaking the existing `process_one` flow.

**Architecture:** Introduce new modules in `src/core/` and `src/pipeline/` alongside the legacy `src/pipeline.py`. The runner wraps the unchanged `process_one` in a single `LegacyMonolithStage` so the externally visible behaviour is identical; Sprint 2 will replace that wrapper with real per-phase stages. All existing tests must continue to pass at every commit.

**Tech Stack:** Python 3.11, pydantic v2, sqlmodel, typer, rich, pytest. No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-04-24-sturdy-frame-and-content-upgrade-design.md` (sections §0–§6, §12).

---

## File Structure

**New files:**

| Path | Responsibility |
|---|---|
| `src/core/context.py` | `Context` pydantic model carrying per-story state through stages; `RunOptions`; placeholder types `SegmentAudio`, `ChapterRange`, `CritiqueResult`, `PlatformMetadata` for downstream sprints. |
| `src/core/logging.py` | `JsonFormatter`, `setup(level)`, `bind_log(**extras)` — structured JSON logging. |
| `src/core/configs.py` | `AppConfig` + per-section pydantic models; `AppConfig.load(brand)`; `ConfigError` with path-to-key. |
| `src/core/health.py` | `HealthSnapshot` aggregator; `last_hours(hours)` reads from `RunRow`, `ScheduledPostRow`, `costs.jsonl`, `events.jsonl`. |
| `src/pipeline/__init__.py` | Re-export `RunOptions`, `process_one`, `choose_profile` from `.legacy` to keep imports stable. |
| `src/pipeline/legacy.py` | The current `src/pipeline.py` content, moved verbatim. |
| `src/pipeline/stages/__init__.py` | Empty package marker. |
| `src/pipeline/stages/base.py` | `Stage` Protocol; `BaseStage` with default `is_cached=False` / `clear=noop`. |
| `src/pipeline/stages/legacy.py` | `LegacyMonolithStage` — wraps `process_one`; populates `ctx.long_video`, `ctx.shorts`, `ctx.thumbnail_variants`, `ctx.packages` from `RenderArtifacts`. |
| `src/pipeline/runner.py` | `STAGES` list (just legacy stage for now); `run(ctx, *, from_stage, to_stage, force)`. |
| `tests/test_context.py` | Context model tests. |
| `tests/test_logging.py` | JSON logging + `bind_log` tests. |
| `tests/test_configs.py` | `AppConfig.load` happy path + validation error. |
| `tests/test_runner.py` | Stage protocol + cache + force + error path tests with `FakeStage`. |
| `tests/test_scheduler_lock.py` | Two-thread enqueue race regression test. |
| `tests/test_storage_dedup_index.py` | `has_near_duplicate` happy path + short-circuit + batch boundary. |
| `tests/test_health.py` | `last_hours` aggregation test. |

**Modified files:**

| Path | Change |
|---|---|
| `src/pipeline.py` | Removed (moved to `src/pipeline/legacy.py`). |
| `src/cli.py` | Replace `_setup_logging`; call `AppConfig.load(brand)` in `_root`; add `health` command; switch `run` command to invoke `runner.run()`. |
| `src/publish/scheduler.py` | `_next_slot(platform, cadence, sess)` accepts a session; `enqueue` opens `BEGIN IMMEDIATE` for read-then-write atomicity; the legacy `<now → +1 day` hack replaced by `max(now, base+delta)` with preferred hour. |
| `src/core/storage.py` | `StoryRow.simhash` → `Field(index=True)`; `engine()` runs `CREATE INDEX IF NOT EXISTS`; new `has_near_duplicate(our_hash, *, threshold, since_days, batch)`. |
| `src/filters/pipeline.py` | Call `has_near_duplicate` instead of iterating `recent_simhashes`. |
| `tests/test_dedup_wired.py` | Monkeypatch `has_near_duplicate` instead of `recent_simhashes`. |

---

## Task 1: Define `Context` model and relocate `RunOptions`

Pydantic `Context` carries per-story state through stages. `RunOptions` moves out of `src/pipeline.py` so `core/` doesn't have to depend on `pipeline/`. Placeholder types (`SegmentAudio`, `ChapterRange`, `CritiqueResult`, `PlatformMetadata`) are defined here to lock interfaces for Sprints 2–3.

**Files:**
- Create: `src/core/context.py`
- Create: `tests/test_context.py`
- Modify: `src/pipeline.py` (top of file: remove `RunOptions` dataclass, import from new module)

- [ ] **Step 1.1: Write the failing test**

Create `tests/test_context.py`:

```python
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
```

- [ ] **Step 1.2: Run the test to confirm it fails**

```
pytest tests/test_context.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.core.context'` (or `ImportError` for `Context`).

- [ ] **Step 1.3: Implement `src/core/context.py`**

Create the file:

```python
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
```

- [ ] **Step 1.4: Run the test to confirm it now passes (except the legacy-alias check)**

```
pytest tests/test_context.py -v
```

Expected: `test_run_options_importable_from_legacy_alias` still fails because `src.pipeline.RunOptions` is the old dataclass instance — different identity. The other tests pass.

- [ ] **Step 1.5: Update `src/pipeline.py` to import `RunOptions` from the new location**

In `src/pipeline.py`, replace the `@dataclass` block at lines 55–64 with a re-export:

```python
# RunOptions moved to src/core/context.py; re-export for backward compatibility.
from src.core.context import RunOptions  # noqa: F401
```

Delete the now-unused `from dataclasses import dataclass` import at the top of the file (line 18) only if no other dataclass remains in the file (use grep to check).

- [ ] **Step 1.6: Run the full test suite**

```
pytest -x -q
```

Expected: all tests pass, including `test_run_options_importable_from_legacy_alias` and the existing `test_pipeline_timing.py`.

- [ ] **Step 1.7: Commit**

```
git add src/core/context.py src/pipeline.py tests/test_context.py
git commit -m "feat(core): introduce Context model and relocate RunOptions"
```

---

## Task 2: Structured JSON logging

`src/core/logging.py` provides a `JsonFormatter` that emits one JSON object per log record (with `ts`, `level`, `msg`, `name`, plus any `extra` fields), `setup(level)` to install it on the root logger, and `bind_log(**kv)` to return a `LoggerAdapter` that injects the given fields into every record without touching call-sites.

**Files:**
- Create: `src/core/logging.py`
- Create: `tests/test_logging.py`
- Modify: `src/cli.py:46-51` (`_setup_logging`)

- [ ] **Step 2.1: Write the failing test**

Create `tests/test_logging.py`:

```python
"""Structured JSON logging."""
import io
import json
import logging

from src.core.logging import JsonFormatter, bind_log, setup


def _capture(level: str = "INFO") -> tuple[logging.Logger, io.StringIO]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(f"test.{id(buf)}")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
    return logger, buf


def test_json_formatter_basic_record() -> None:
    logger, buf = _capture()
    logger.info("hello world")
    rec = json.loads(buf.getvalue().strip())
    assert rec["msg"] == "hello world"
    assert rec["level"] == "INFO"
    assert rec["name"].startswith("test.")
    assert "ts" in rec and rec["ts"].endswith("Z")


def test_json_formatter_includes_extras() -> None:
    logger, buf = _capture()
    logger.info("stage_ok", extra={"story_id": "reddit:abc", "duration_ms": 42})
    rec = json.loads(buf.getvalue().strip())
    assert rec["story_id"] == "reddit:abc"
    assert rec["duration_ms"] == 42


def test_bind_log_injects_fields() -> None:
    logger, buf = _capture()
    adapter = bind_log(logger, story_id="reddit:abc", stage="script_llm")
    adapter.info("stage_ok", duration_ms=100)
    rec = json.loads(buf.getvalue().strip())
    assert rec["story_id"] == "reddit:abc"
    assert rec["stage"] == "script_llm"
    assert rec["duration_ms"] == 100
    assert rec["msg"] == "stage_ok"


def test_bind_log_extra_kwargs_override_bound_fields() -> None:
    """bind_log fields can be overridden per-call by passing the same key in extras."""
    logger, buf = _capture()
    adapter = bind_log(logger, stage="A")
    adapter.info("x", stage="B")
    rec = json.loads(buf.getvalue().strip())
    assert rec["stage"] == "B"


def test_setup_replaces_root_handlers(capsys) -> None:
    setup(level="INFO")
    logging.getLogger().info("plain")
    out = capsys.readouterr().out.strip()
    rec = json.loads(out)
    assert rec["msg"] == "plain"


def test_exception_serialized() -> None:
    logger, buf = _capture()
    try:
        raise ValueError("boom")
    except ValueError:
        logger.error("caught", exc_info=True)
    rec = json.loads(buf.getvalue().strip())
    assert "ValueError: boom" in rec["exc_info"]
```

- [ ] **Step 2.2: Run the test to confirm it fails**

```
pytest tests/test_logging.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.core.logging'`.

- [ ] **Step 2.3: Implement `src/core/logging.py`**

```python
"""Structured JSON logging with bound-field LoggerAdapter."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# Standard LogRecord attributes we don't want to leak into the JSON output as
# "extras". Anything not in this set goes into the record verbatim.
_STD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
                .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            out["exc_info"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k in _STD_ATTRS or k.startswith("_"):
                continue
            try:
                json.dumps(v)
                out[k] = v
            except TypeError:
                out[k] = repr(v)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup(level: str | int = "INFO") -> None:
    """Replace root logger handlers with a single JSON stdout handler."""
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(level)


class _BoundAdapter(logging.LoggerAdapter):
    """LoggerAdapter that merges bound fields with per-call kwargs."""

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        extra = dict(self.extra or {})
        # Per-call kwargs (other than reserved logging args) override bound fields.
        reserved = {"exc_info", "stack_info", "stacklevel", "extra"}
        for key in list(kwargs.keys()):
            if key in reserved:
                continue
            extra[key] = kwargs.pop(key)
        kwargs["extra"] = extra
        return msg, kwargs


def bind_log(logger: logging.Logger | None = None, **fields: Any) -> _BoundAdapter:
    """Return a LoggerAdapter that injects `fields` into every record."""
    return _BoundAdapter(logger or logging.getLogger(), fields)
```

- [ ] **Step 2.4: Run the test to confirm it passes**

```
pytest tests/test_logging.py -v
```

Expected: all six tests pass.

- [ ] **Step 2.5: Wire `setup()` into `cli.py::_setup_logging`**

Replace the body of `_setup_logging` in `src/cli.py:46-51` with:

```python
def _setup_logging() -> None:
    import os
    from src.core.logging import setup
    setup(level=os.getenv("GAMEEE_LOG_LEVEL", "INFO"))
```

Remove the now-unused top-level `import logging` if no other code in `src/cli.py` references it (use grep to check first).

- [ ] **Step 2.6: Run the full test suite**

```
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 2.7: Commit**

```
git add src/core/logging.py src/cli.py tests/test_logging.py
git commit -m "feat(core): structured JSON logging with bound-field adapter"
```

---

## Task 3: Config validation with `AppConfig`

A new `src/core/configs.py` module loads the same YAML files (`sources`, `filters`, `voices`, `images`, `channel`, `audio`) and validates them against pydantic models. The legacy dict-based `src.core.config.sources()` etc. continue to work; we only add a fail-fast validation layer at CLI startup so typos in YAML produce a clear error instead of a downstream `KeyError`.

The submodels deliberately use `extra="allow"` so unknown sub-keys don't break loading — we only enforce the keys we actively depend on. Tightening can come later, file by file.

**Files:**
- Create: `src/core/configs.py`
- Create: `tests/test_configs.py`
- Modify: `src/cli.py` (call `AppConfig.load(brand)` in `_root` callback after `set_active_brand`)

- [ ] **Step 3.1: Write the failing test**

Create `tests/test_configs.py`:

```python
"""AppConfig validation."""
import pytest

from src.core.configs import AppConfig, ConfigError


def test_load_default_brand_succeeds() -> None:
    cfg = AppConfig.load("default")
    # Sample fields actually used by the codebase today.
    assert cfg.filters.dedup.enabled is True
    assert cfg.filters.dedup.simhash_threshold >= 1
    assert cfg.filters.dedup.history_days >= 1
    assert isinstance(cfg.filters.length.min_chars, int)


def test_load_unknown_brand_falls_back_to_defaults() -> None:
    cfg = AppConfig.load("nonexistent_brand_xyz")
    # Should still load — overlay simply doesn't exist.
    assert cfg.filters.dedup.enabled is True


def test_invalid_overlay_raises_config_error(tmp_path, monkeypatch) -> None:
    """A wrong-typed value in a brand overlay should raise ConfigError with a path."""
    import src.core.config as legacy_config
    bad_brand = tmp_path / "brands" / "broken"
    bad_brand.mkdir(parents=True)
    # simhash_threshold must be int; provide a string.
    (bad_brand / "filters.yaml").write_text(
        "dedup:\n  simhash_threshold: 'not-an-int'\n", encoding="utf-8"
    )
    monkeypatch.setattr(legacy_config, "BRANDS_DIR", tmp_path / "brands")
    legacy_config._base_yaml.cache_clear()
    for fn in (legacy_config.sources, legacy_config.filters, legacy_config.voices,
               legacy_config.images, legacy_config.channel, legacy_config.audio):
        fn.cache_clear()
    with pytest.raises(ConfigError) as ei:
        AppConfig.load("broken")
    msg = str(ei.value)
    assert "filters" in msg and "simhash_threshold" in msg


def test_config_error_message_lists_all_failures(tmp_path, monkeypatch) -> None:
    import src.core.config as legacy_config
    bad = tmp_path / "brands" / "many_errors"
    bad.mkdir(parents=True)
    (bad / "filters.yaml").write_text(
        "dedup:\n  simhash_threshold: 'bad'\n  history_days: 'also bad'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(legacy_config, "BRANDS_DIR", tmp_path / "brands")
    legacy_config._base_yaml.cache_clear()
    for fn in (legacy_config.sources, legacy_config.filters, legacy_config.voices,
               legacy_config.images, legacy_config.channel, legacy_config.audio):
        fn.cache_clear()
    with pytest.raises(ConfigError) as ei:
        AppConfig.load("many_errors")
    msg = str(ei.value)
    assert "simhash_threshold" in msg
    assert "history_days" in msg
```

- [ ] **Step 3.2: Run the test to confirm it fails**

```
pytest tests/test_configs.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.core.configs'`.

- [ ] **Step 3.3: Implement `src/core/configs.py`**

```python
"""Validated application configuration.

`AppConfig.load(brand)` reads the same YAML files as the dict-based
`src.core.config` accessors and runs them through pydantic models so
typos and wrong types are caught at CLI startup with a clear path-to-key
error instead of a downstream KeyError or AttributeError.

Models use `extra='allow'` to avoid breaking on YAML keys we don't yet
model — only the fields we actively depend on are constrained.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core import config as _legacy


class ConfigError(ValueError):
    """Raised when a config file fails validation."""


class _Lax(BaseModel):
    model_config = ConfigDict(extra="allow")


class DedupCfg(_Lax):
    enabled: bool = True
    shingle_size: int = 6
    simhash_threshold: int = 4
    history_days: int = 60


class LengthCfg(_Lax):
    min_chars: int = 0
    max_chars: int = 1_000_000


class FiltersConfig(_Lax):
    dedup: DedupCfg = Field(default_factory=DedupCfg)
    length: LengthCfg = Field(default_factory=LengthCfg)


class SourcesConfig(_Lax):
    pass


class VoicesRouterCfg(_Lax):
    primary: str | None = None
    fallback_chain: list[str] = Field(default_factory=list)


class VoicesConfig(_Lax):
    router: VoicesRouterCfg = Field(default_factory=VoicesRouterCfg)


class ImagesConfig(_Lax):
    pass


class ChannelConfig(_Lax):
    pass


class AudioConfig(_Lax):
    pass


_SECTION_LOADERS = {
    "sources": ("sources.yaml", SourcesConfig),
    "filters": ("filters.yaml", FiltersConfig),
    "voices": ("voices.yaml", VoicesConfig),
    "images": ("images.yaml", ImagesConfig),
    "channel": ("channel.yaml", ChannelConfig),
    "audio": ("audio.yaml", AudioConfig),
}


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: SourcesConfig
    filters: FiltersConfig
    voices: VoicesConfig
    images: ImagesConfig
    channel: ChannelConfig
    audio: AudioConfig

    @classmethod
    def load(cls, brand: str = "default") -> "AppConfig":
        prev = _legacy.active_brand()
        try:
            _legacy.set_active_brand(brand)
            raw: dict[str, dict[str, Any]] = {
                key: _legacy._read_yaml(filename)
                for key, (filename, _model) in _SECTION_LOADERS.items()
            }
        finally:
            _legacy.set_active_brand(prev)

        errors: list[str] = []
        validated: dict[str, BaseModel] = {}
        for key, (_, model) in _SECTION_LOADERS.items():
            try:
                validated[key] = model.model_validate(raw[key])
            except ValidationError as e:
                for err in e.errors():
                    path = ".".join(str(p) for p in (key, *err["loc"]))
                    errors.append(f"  - {path}: {err['msg']} (got: {err.get('input')!r})")
        if errors:
            raise ConfigError(
                "Config validation failed:\n" + "\n".join(errors)
            )
        return cls(**validated)
```

- [ ] **Step 3.4: Run the test to confirm it passes**

```
pytest tests/test_configs.py -v
```

Expected: all four tests pass.

- [ ] **Step 3.5: Wire validation into the CLI startup**

In `src/cli.py`, modify the `_root` callback (around line 34) to validate after `set_active_brand`:

```python
@app.callback()
def _root(
    brand: str = typer.Option(
        "default", "--brand", "-b",
        help="Brand overlay to apply (see config/brands/). Default = base configs only.",
    ),
) -> None:
    if brand:
        from src.core.config import set_active_brand
        set_active_brand(brand)
    from src.core.configs import AppConfig, ConfigError
    try:
        AppConfig.load(brand)
    except ConfigError as exc:
        console.print(f"[red]config error[/red]\n{exc}")
        raise typer.Exit(code=2)
```

- [ ] **Step 3.6: Run the full test suite**

```
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 3.7: Smoke-test the CLI**

```
python -m src.cli --help
```

Expected: help output prints normally (no `config error`).

- [ ] **Step 3.8: Commit**

```
git add src/core/configs.py src/cli.py tests/test_configs.py
git commit -m "feat(core): AppConfig validation at CLI startup"
```

---

## Task 4: Pipeline package, `Stage` protocol, `runner.run`

Convert `src/pipeline.py` (a single module) into `src/pipeline/` (a package), preserving all existing behaviour by moving the file verbatim into `src/pipeline/legacy.py` and re-exporting its public names from `src/pipeline/__init__.py`. Add the new `Stage` protocol, the `runner.run()` entrypoint, and a `LegacyMonolithStage` that wraps `process_one`. Switch `cli.py::run` to call the runner. The end of this task: every existing test still passes; `cli run` exercises the new runner; the runner currently has exactly one stage (the legacy wrapper) — Sprint 2 will replace it with real per-phase stages.

**Files:**
- Move: `src/pipeline.py` → `src/pipeline/legacy.py`
- Create: `src/pipeline/__init__.py`, `src/pipeline/runner.py`, `src/pipeline/stages/__init__.py`, `src/pipeline/stages/base.py`, `src/pipeline/stages/legacy.py`
- Create: `tests/test_runner.py`
- Modify: `src/cli.py` (the `run` command)

### Subtask 4A — Repackage without behaviour change

- [ ] **Step 4.1: Move `pipeline.py` into a package using a temporary rename**

The destination directory shares the source file's name, so do it in two `git mv` steps:

```
git mv src/pipeline.py src/_pipeline_tmp.py
mkdir src/pipeline
git mv src/_pipeline_tmp.py src/pipeline/legacy.py
```

- [ ] **Step 4.2: Create `src/pipeline/__init__.py` re-exporting the public API**

```python
"""Pipeline orchestration. Public API re-exported from the legacy monolith
during Sprint 1; Sprint 2 will replace these names with per-stage modules.
"""
from src.pipeline.legacy import RunOptions, choose_profile, process_one

__all__ = ["RunOptions", "choose_profile", "process_one"]
```

- [ ] **Step 4.3: Run the full test suite to confirm the move was transparent**

```
pytest -x -q
```

Expected: identical results to before the move (no new failures). Existing imports `from src.pipeline import RunOptions, process_one` continue to work.

- [ ] **Step 4.4: Commit the refactor on its own**

```
git add src/pipeline tests
git commit -m "refactor: convert src/pipeline.py to a package (legacy module unchanged)"
```

### Subtask 4B — `Stage` protocol and `runner`

- [ ] **Step 4.5: Write the failing test**

Create `tests/test_runner.py`:

```python
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
```

- [ ] **Step 4.6: Run the test to confirm it fails**

```
pytest tests/test_runner.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.pipeline.runner'`.

- [ ] **Step 4.7: Implement `src/pipeline/stages/__init__.py` and `src/pipeline/stages/base.py`**

Create empty `src/pipeline/stages/__init__.py` (zero bytes — package marker).

Create `src/pipeline/stages/base.py`:

```python
"""Stage protocol shared by every pipeline phase."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.core.context import Context


@runtime_checkable
class Stage(Protocol):
    name: str

    def run(self, ctx: Context) -> Context: ...
    def is_cached(self, ctx: Context) -> bool: ...
    def clear(self, ctx: Context) -> None: ...


class BaseStage:
    """Default implementations: never cached, no-op clear. Subclasses set `name`
    and override `run` (and optionally `is_cached` / `clear`)."""

    name: str = "base"

    def run(self, ctx: Context) -> Context:  # pragma: no cover - abstract
        raise NotImplementedError

    def is_cached(self, ctx: Context) -> bool:
        return False

    def clear(self, ctx: Context) -> None:
        return None
```

- [ ] **Step 4.8: Implement `src/pipeline/runner.py`**

```python
"""Runs registered Stages in order against a Context."""
from __future__ import annotations

import time
from typing import Iterable

from src.core.context import Context
from src.core.logging import bind_log
from src.core.storage import finish_run
from src.pipeline.stages.base import Stage

# Populated as stages are extracted in Sprint 2. For now, the runner is wired
# to a single LegacyMonolithStage (see src/pipeline/stages/legacy.py).
STAGES: list[Stage] = []


def _slice(stages: list[Stage], from_stage: str | None,
           to_stage: str | None) -> Iterable[Stage]:
    names = [s.name for s in stages]
    start = 0
    end = len(stages)
    if from_stage is not None:
        if from_stage not in names:
            raise ValueError(f"unknown stage: {from_stage}")
        start = names.index(from_stage)
    if to_stage is not None:
        if to_stage not in names:
            raise ValueError(f"unknown stage: {to_stage}")
        end = names.index(to_stage) + 1
    return stages[start:end]


def run(
    ctx: Context,
    *,
    from_stage: str | None = None,
    to_stage: str | None = None,
    force: set[str] | frozenset[str] = frozenset(),
) -> Context:
    """Execute STAGES against `ctx`, honouring caching and slice bounds.

    Stages whose `name` is in `force` have their cache cleared first.
    On any stage exception, marks the run as failed and re-raises.
    """
    for stage in _slice(STAGES, from_stage, to_stage):
        log = bind_log(story_id=ctx.story_id, stage=stage.name, brand=ctx.brand)
        if stage.name in force:
            stage.clear(ctx)
        if stage.is_cached(ctx):
            log.info("cache_hit")
            continue
        t0 = time.monotonic()
        try:
            ctx = stage.run(ctx)
        except Exception as exc:
            log.error(
                "stage_failed",
                error=repr(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
            finish_run(ctx.run_id, "failed", f"{stage.name}: {exc!r}")
            raise
        log.info(
            "stage_ok",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    finish_run(ctx.run_id, "ok")
    return ctx
```

- [ ] **Step 4.9: Run the test to confirm it passes**

```
pytest tests/test_runner.py -v
```

Expected: all eight tests pass.

### Subtask 4C — `LegacyMonolithStage` wraps `process_one`

- [ ] **Step 4.10: Write the failing test**

Append to `tests/test_runner.py`:

```python
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
```

- [ ] **Step 4.11: Run the test to confirm it fails**

```
pytest tests/test_runner.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.pipeline.stages.legacy'`.

- [ ] **Step 4.12: Implement `src/pipeline/stages/legacy.py`**

```python
"""Single-stage adapter that delegates to the legacy `process_one` monolith.

Lets the new runner drive the existing pipeline byte-for-byte during Sprint 1.
Sprint 2 will replace this with one stage per phase.
"""
from __future__ import annotations

from pathlib import Path

from src.core.context import Context
from src.pipeline.legacy import process_one
from src.pipeline.stages.base import BaseStage


class LegacyMonolithStage(BaseStage):
    name = "legacy_monolith"

    def run(self, ctx: Context) -> Context:
        artifacts = process_one(ctx.story, ctx.opts)
        if artifacts is None:
            return ctx
        ctx.long_video = Path(artifacts.long_video_mp4) if artifacts.long_video_mp4 else None
        ctx.shorts = [Path(p) for p in artifacts.shorts_mp4]
        ctx.thumbnail_variants = [Path(artifacts.thumbnail)] if artifacts.thumbnail else []
        return ctx
```

- [ ] **Step 4.13: Run the test to confirm it passes**

```
pytest tests/test_runner.py -v
```

Expected: ten tests pass.

### Subtask 4D — Wire CLI `run` to the new runner

- [ ] **Step 4.14: Modify `src/cli.py::run` to use `runner.run()`**

In `src/cli.py`, replace the body of the `run` command (currently around lines 141–174) with:

```python
@app.command()
def run(
    story_id: str | None = typer.Option(None, help="specific story id; else pick top unused"),
    research: bool = typer.Option(False, "--research/--no-research",
                                  help="bypass rights gate for internal rendering only"),
    profile: str = typer.Option("auto", help="short | long | auto"),
    publish: bool = typer.Option(False, help="upload long video to YouTube"),
    from_stage: str | None = typer.Option(None, "--from", help="resume from this stage"),
    to_stage: str | None = typer.Option(None, "--to", help="stop after this stage"),
    force: list[str] = typer.Option([], "--force", help="clear cache for these stages (repeatable)"),
) -> None:
    """Render one story end-to-end via the stage runner."""
    _setup_logging()
    if story_id:
        row = get_story(story_id)
    else:
        candidates = top_unused(limit=50)
        row = None
        for c in candidates:
            if research or is_cleared(c.id):
                row = c
                break
    if not row:
        console.print("[red]no eligible story[/red]")
        raise typer.Exit(code=1)

    story = _row_to_story(row)
    opts = RunOptions(
        research_mode=research,
        publish_youtube=publish,
        profile={"short": LengthProfile.SHORT, "long": LengthProfile.LONG}.get(
            profile, LengthProfile.SHORT
        ),
    )

    from datetime import datetime, timezone
    from src.core.config import runs_dir
    from src.core.context import Context
    from src.core.storage import start_run
    from src.pipeline import runner
    from src.pipeline.stages.legacy import LegacyMonolithStage

    run_dir = (runs_dir() / datetime.now(timezone.utc).strftime("%Y-%m-%d")
               / story.id.replace(":", "_"))
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = start_run(story.id, run_dir)
    ctx = Context(run_id=run_id, story_id=story.id, brand=os.getenv("GAMEEE_BRAND", "default"),
                  run_dir=run_dir, story=story, opts=opts)

    # Sprint 1: only the legacy wrapper stage is registered.
    if not runner.STAGES:
        runner.STAGES = [LegacyMonolithStage()]

    try:
        out = runner.run(ctx, from_stage=from_stage, to_stage=to_stage,
                         force=set(force))
    except Exception as exc:
        console.print(f"[red]pipeline failed: {exc}[/red]")
        raise typer.Exit(code=1)

    console.print({
        "story_id": out.story_id,
        "long_video": str(out.long_video) if out.long_video else None,
        "shorts": [str(p) for p in out.shorts],
        "thumbnail_variants": [str(p) for p in out.thumbnail_variants],
    })
```

(The legacy `process_one` is no longer called directly from CLI — only via the stage. The legacy artifact-printing path is replaced by the dict above.)

- [ ] **Step 4.15: Run the full test suite**

```
pytest -x -q
```

Expected: all tests pass — including any pre-existing tests that imported `RunOptions` / `process_one` from `src.pipeline`.

- [ ] **Step 4.16: Smoke-test the CLI**

```
python -m src.cli run --help
```

Expected: help text includes new `--from`, `--to`, `--force` options.

- [ ] **Step 4.17: Commit**

```
git add src/pipeline tests/test_runner.py src/cli.py
git commit -m "feat(pipeline): Stage protocol, runner, and legacy-wrapping stage"
```

---

## Task 5: Scheduler — `BEGIN IMMEDIATE` lock + cleaner `_next_slot`

The current `enqueue` reads `last_planned` in one session and inserts in another. Two concurrent calls can read the same `last_planned` and produce identical slots. We open a single `BEGIN IMMEDIATE` transaction that read-locks the database for the lookup-and-insert, so the second caller blocks on the lock and observes the first row. We also retire the `<now → +1 day` patch in `_next_slot`: if `base + delta` is in the past, we just take `max(now, base + delta)` and snap to the preferred hour.

**Files:**
- Modify: `src/publish/scheduler.py:64-111`
- Create: `tests/test_scheduler_lock.py`

- [ ] **Step 5.1: Write the failing test**

Create `tests/test_scheduler_lock.py`:

```python
"""Scheduler enqueue must produce non-colliding slots even under concurrent calls."""
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.publish import scheduler


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setenv("GAMEEE_DB", str(db))
    # Reset the cached engine so it reopens against the new path.
    import src.core.storage as storage
    monkeypatch.setattr(storage, "_engine", None)
    yield


def test_enqueue_two_threads_no_collision(fresh_db, monkeypatch) -> None:
    """Two concurrent enqueue() calls on the same platform must produce distinct slots."""
    barrier = threading.Barrier(2)
    results: list = []
    errors: list[Exception] = []

    def worker(story_id: str) -> None:
        try:
            barrier.wait(timeout=2)
            row = scheduler.enqueue(
                story_id, "youtube_shorts",
                Path("/tmp/v.mp4"), "title", "desc", ["x"],
            )
            results.append(row.planned_for)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=("reddit:a",))
    t2 = threading.Thread(target=worker, args=("reddit:b",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors, errors
    assert len(results) == 2
    assert results[0] != results[1], (
        f"slot collision: both rows planned for {results[0]}"
    )


def test_enqueue_serial_calls_advance_by_cadence(fresh_db) -> None:
    a = scheduler.enqueue("reddit:a", "youtube_shorts",
                          Path("/tmp/a.mp4"), "t", "d", [])
    b = scheduler.enqueue("reddit:b", "youtube_shorts",
                          Path("/tmp/b.mp4"), "t", "d", [])
    delta = b.planned_for - a.planned_for
    cadence = scheduler.cadence_from_config()
    assert delta == timedelta(hours=cadence.youtube_shorts_hours)


def test_next_slot_does_not_double_step_when_base_is_past(fresh_db, monkeypatch) -> None:
    """Old code added +1 day if `base + delta < now`. New code: snap to today's
    preferred hour or tomorrow's if that's already past."""
    a = scheduler.enqueue("reddit:a", "youtube",
                          Path("/tmp/a.mp4"), "t", "d", [])
    cadence = scheduler.cadence_from_config()
    now = datetime.now(timezone.utc)
    expected_lower_bound = now + timedelta(days=cadence.long_youtube_days) - timedelta(hours=24)
    assert a.planned_for >= expected_lower_bound
    # And not absurdly far in the future.
    assert a.planned_for <= now + timedelta(days=cadence.long_youtube_days + 2)
```

- [ ] **Step 5.2: Run the test to confirm it fails**

```
pytest tests/test_scheduler_lock.py -v
```

Expected: `test_enqueue_two_threads_no_collision` may fail intermittently OR pass on a fast machine. To force a reproducible failure, add the slow-down monkeypatch below to `_next_slot` and re-run; for now, accept that we're proving the *fix* by ensuring the test is reliably green afterwards. Run it 5× to spot-check stability:

```
for i in 1 2 3 4 5; do pytest tests/test_scheduler_lock.py::test_enqueue_two_threads_no_collision -q || echo FAIL_$i; done
```

If the test never fails on this machine without the fix, that's fine — the lock still removes a real production race. Proceed.

- [ ] **Step 5.3: Refactor `_next_slot` to accept a session and `enqueue` to wrap in `BEGIN IMMEDIATE`**

Replace `src/publish/scheduler.py:64-111` with:

```python
def _next_slot(platform: str, cadence: Cadence, sess: Session) -> datetime:
    """Next slot after the latest planned post on that platform.

    `sess` must already be inside a write transaction (BEGIN IMMEDIATE) so the
    read-then-insert is atomic across concurrent callers.
    """
    q = (
        select(ScheduledPostRow)
        .where(ScheduledPostRow.platform == platform)
        .order_by(ScheduledPostRow.planned_for.desc())
        .limit(1)
    )
    last = sess.exec(q).first()

    now = datetime.now(timezone.utc)
    if platform == "youtube":
        delta = timedelta(days=cadence.long_youtube_days)
    elif platform == "youtube_shorts":
        delta = timedelta(hours=cadence.youtube_shorts_hours)
    elif platform == "tiktok":
        delta = timedelta(hours=cadence.tiktok_hours)
    else:
        delta = timedelta(hours=cadence.instagram_hours)

    base = last.planned_for if last else now
    candidate = max(now, base + delta)
    candidate = candidate.replace(
        hour=cadence.preferred_hour_utc, minute=0, second=0, microsecond=0
    )
    if candidate < now:
        candidate = candidate + timedelta(days=1)
    return candidate


def enqueue(story_id: str, platform: str, video_path: Path, title: str,
            description: str, hashtags: list[str]) -> ScheduledPostRow:
    """Plan a post in a slot that won't collide with concurrent enqueues."""
    import json as _json
    from sqlalchemy import text as _text
    _ensure_table()
    cadence = cadence_from_config()
    with Session(engine()) as s:
        s.connection().execute(_text("BEGIN IMMEDIATE"))
        slot = _next_slot(platform, cadence, s)
        row = ScheduledPostRow(
            story_id=story_id,
            platform=platform,
            video_path=str(video_path),
            title=title,
            description=description,
            hashtags_json=_json.dumps(hashtags, ensure_ascii=False),
            planned_for=slot,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
    log.info("enqueued %s for %s at %s", platform, story_id, slot.isoformat())
    return row
```

- [ ] **Step 5.4: Run the test to confirm it passes**

```
pytest tests/test_scheduler_lock.py -v
```

Expected: all three tests pass. Run the parallel test 5 more times to confirm stability:

```
for i in 1 2 3 4 5; do pytest tests/test_scheduler_lock.py::test_enqueue_two_threads_no_collision -q; done
```

- [ ] **Step 5.5: Run the full test suite**

```
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 5.6: Commit**

```
git add src/publish/scheduler.py tests/test_scheduler_lock.py
git commit -m "fix(scheduler): use BEGIN IMMEDIATE to prevent slot collisions"
```

---

## Task 6: Dedup index + `has_near_duplicate`

`StoryRow.simhash` already exists but is unindexed; the current dedup path pulls all simhashes for the last 60 days into Python and Hamming-compares one by one. With a real corpus this becomes O(N) per ingest. We add a SQL index on the column and a `has_near_duplicate(our_hash, ...)` helper that scans in batches and short-circuits on the first match. The `filters/pipeline.accept` call site is replaced. The existing `recent_simhashes` helper stays for now (no other callers need migration in this sprint), but the comparison work moves out of Python.

**Files:**
- Modify: `src/core/storage.py:35` (index), `src/core/storage.py:73-80` (engine creates index), append `has_near_duplicate`
- Modify: `src/filters/pipeline.py:42-46`
- Modify: `tests/test_dedup_wired.py:35,54` (monkeypatch new function)
- Create: `tests/test_storage_dedup_index.py`

- [ ] **Step 6.1: Write the failing test**

Create `tests/test_storage_dedup_index.py`:

```python
"""Index on StoryRow.simhash + has_near_duplicate batch lookup."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import text


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setenv("GAMEEE_DB", str(db))
    import src.core.storage as storage
    monkeypatch.setattr(storage, "_engine", None)
    yield


def _insert_story(sid: str, simhash: int | None,
                  fetched_at: datetime | None = None) -> None:
    from src.core.storage import StoryRow, session
    row = StoryRow(
        id=sid, source="reddit", source_id=sid.split(":")[-1],
        permalink="https://example", author=None,
        title="t", text="x" * 400, lang_detected="ru",
        nsfw=False, created_at=datetime.now(timezone.utc),
        fetched_at=fetched_at or datetime.now(timezone.utc),
        simhash=simhash, used=False,
    )
    with session() as s:
        s.add(row)


def test_simhash_index_is_created(fresh_db) -> None:
    from src.core.storage import engine
    eng = engine()
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")
        ).fetchall()
    names = [r[0] for r in rows]
    assert "ix_storyrow_simhash" in names


def test_has_near_duplicate_returns_existing_id(fresh_db) -> None:
    from src.core.storage import has_near_duplicate
    target = 0xDEAD_BEEF_DEAD_BEEF
    _insert_story("reddit:a", target)
    found = has_near_duplicate(target, threshold=4, since_days=60)
    assert found == "reddit:a"


def test_has_near_duplicate_returns_none_for_unrelated(fresh_db) -> None:
    from src.core.storage import has_near_duplicate
    _insert_story("reddit:a", 0x0000_0000_0000_0001)
    out = has_near_duplicate(0xFFFF_FFFF_FFFF_FFFE, threshold=4, since_days=60)
    assert out is None


def test_has_near_duplicate_short_circuits_on_first_match(fresh_db, monkeypatch) -> None:
    """Once a match is found, no further batches are loaded."""
    from src.core.storage import has_near_duplicate
    for i in range(50):
        _insert_story(f"reddit:{i}", i)            # tiny simhashes, won't match
    _insert_story("reddit:hit", 0xABCD_0000_ABCD_0000)
    found = has_near_duplicate(0xABCD_0000_ABCD_0000, threshold=0,
                               since_days=60, batch=10)
    assert found == "reddit:hit"


def test_has_near_duplicate_respects_since_days_window(fresh_db) -> None:
    from src.core.storage import has_near_duplicate
    long_ago = datetime.now(timezone.utc) - timedelta(days=120)
    _insert_story("reddit:old", 0xDEAD, fetched_at=long_ago)
    out = has_near_duplicate(0xDEAD, threshold=0, since_days=30)
    assert out is None


def test_has_near_duplicate_skips_null_simhash_rows(fresh_db) -> None:
    from src.core.storage import has_near_duplicate
    _insert_story("reddit:null", None)
    _insert_story("reddit:hit", 0xCAFE)
    out = has_near_duplicate(0xCAFE, threshold=0, since_days=60)
    assert out == "reddit:hit"
```

- [ ] **Step 6.2: Run the test to confirm it fails**

```
pytest tests/test_storage_dedup_index.py -v
```

Expected: `test_simhash_index_is_created` fails (no such index); `has_near_duplicate` tests fail with `ImportError`.

- [ ] **Step 6.3: Add the index + `has_near_duplicate` to `src/core/storage.py`**

Edit line 35 in `src/core/storage.py` from:

```python
    simhash: int | None = None    # 64-bit fingerprint for dedup; None = not computed
```

to:

```python
    simhash: int | None = Field(default=None, index=True)
```

Edit `engine()` at lines 73–80 to create the index after `create_all`:

```python
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
```

(`Field(index=True)` covers fresh DBs; the explicit `CREATE INDEX IF NOT EXISTS` covers existing DBs that were created before this change. Both are idempotent.)

Append the new helper at the end of `src/core/storage.py` (after `metrics_to_json`):

```python
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
```

- [ ] **Step 6.4: Run the test to confirm it passes**

```
pytest tests/test_storage_dedup_index.py -v
```

Expected: all six tests pass.

- [ ] **Step 6.5: Switch `filters/pipeline.py` to the new helper**

Replace the dedup block in `src/filters/pipeline.py:34-46`:

```python
    # 5) Dedup — reject near-duplicates of stories seen in the recent window.
    dcfg = cfg.get("dedup", {}) or {}
    if dcfg.get("enabled", True):
        shingle = int(dcfg.get("shingle_size", 6))
        threshold = int(dcfg.get("simhash_threshold", 4))
        history = int(dcfg.get("history_days", 60))
        our_hash = dedup.simhash(text, k=shingle)
        object.__setattr__(story, "_simhash", our_hash)
        from src.core.storage import has_near_duplicate
        match = has_near_duplicate(
            our_hash, threshold=threshold, since_days=history,
        )
        if match and match != story.id:
            return False, f"dedup:~{match}"
```

Drop the now-unused `from src.core.storage import recent_simhashes` import at the top of the file.

- [ ] **Step 6.6: Update `tests/test_dedup_wired.py` to monkeypatch the new helper**

Replace the two `monkeypatch.setattr(fp, "recent_simhashes", ...)` calls (around lines 35 and 54) with:

```python
    monkeypatch.setattr("src.core.storage.has_near_duplicate",
                        lambda our_hash, threshold=4, since_days=60, batch=500:
                            "reddit:first" if abs(our_hash - existing_hash) < 1_000_000_000 else None)
```

For `test_accept_allows_unrelated_story`, swap to:

```python
    monkeypatch.setattr("src.core.storage.has_near_duplicate",
                        lambda our_hash, threshold=4, since_days=60, batch=500: None)
```

(We can't reuse the simhash-comparison logic the way `recent_simhashes` did because the monkeypatch replaces the helper itself; instead the fakes encode the test's intent directly.)

- [ ] **Step 6.7: Run the full test suite**

```
pytest -x -q
```

Expected: all tests pass — including `test_dedup_wired.py` and the new `test_storage_dedup_index.py`.

- [ ] **Step 6.8: Commit**

```
git add src/core/storage.py src/filters/pipeline.py tests/test_storage_dedup_index.py tests/test_dedup_wired.py
git commit -m "perf(filters): index simhash and short-circuit dedup lookup"
```

---

## Task 7: `cli health` command

`src/core/health.py` aggregates four data sources for an operations dashboard:

1. `RunRow` (SQLite) — runs in the window, grouped by `status`; top errors.
2. `ScheduledPostRow` (SQLite) — pending posts per platform; overdue count.
3. `costs.jsonl` — spend per provider in the window.
4. `events.jsonl` — counts of `failed_no_images`, `blocked`, etc., in the window.

`cli health` prints a Rich table; `cli health --json` dumps the snapshot for cron-style alerts.

**Files:**
- Create: `src/core/health.py`
- Create: `tests/test_health.py`
- Modify: `src/cli.py` (add `health` command)

- [ ] **Step 7.1: Write the failing test**

Create `tests/test_health.py`:

```python
"""HealthSnapshot aggregation."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def fresh_env(tmp_path: Path, monkeypatch) -> Path:
    db = tmp_path / "test.db"
    monkeypatch.setenv("GAMEEE_DB", str(db))
    monkeypatch.setenv("GAMEEE_RUNS", str(tmp_path / "runs"))
    import src.core.storage as storage
    monkeypatch.setattr(storage, "_engine", None)
    return tmp_path


def _add_run(story_id: str, status: str, when: datetime,
             error: str | None = None) -> None:
    from src.core.storage import RunRow, session
    with session() as s:
        s.add(RunRow(
            story_id=story_id, status=status, started_at=when,
            finished_at=when + timedelta(seconds=30), error=error,
        ))


def _add_scheduled(platform: str, when: datetime, status: str = "planned") -> None:
    from src.publish.scheduler import ScheduledPostRow, _ensure_table
    from src.core.storage import session
    _ensure_table()
    with session() as s:
        s.add(ScheduledPostRow(
            story_id="reddit:x", platform=platform,
            video_path="/tmp/v.mp4", title="t", description="d",
            planned_for=when, status=status,
        ))


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def test_last_hours_counts_runs_by_status(fresh_env) -> None:
    from src.core.health import last_hours
    now = datetime.now(timezone.utc)
    _add_run("reddit:a", "ok", now - timedelta(hours=1))
    _add_run("reddit:b", "ok", now - timedelta(hours=2))
    _add_run("reddit:c", "failed", now - timedelta(hours=3), error="tts:timeout")
    _add_run("reddit:d", "blocked", now - timedelta(hours=80))   # outside window
    snap = last_hours(24)
    assert snap.runs["ok"] == 2
    assert snap.runs["failed"] == 1
    assert "blocked" not in snap.runs


def test_last_hours_collects_top_errors(fresh_env) -> None:
    from src.core.health import last_hours
    now = datetime.now(timezone.utc)
    for i in range(3):
        _add_run(f"reddit:{i}", "failed", now, error="tts:timeout")
    _add_run("reddit:x", "failed", now, error="image:no_provider")
    snap = last_hours(24)
    assert snap.top_errors[0] == ("tts:timeout", 3)
    assert ("image:no_provider", 1) in snap.top_errors


def test_last_hours_pending_per_platform(fresh_env) -> None:
    from src.core.health import last_hours
    now = datetime.now(timezone.utc)
    _add_scheduled("youtube_shorts", now + timedelta(hours=2))
    _add_scheduled("youtube_shorts", now + timedelta(hours=26))
    _add_scheduled("tiktok", now + timedelta(hours=3))
    snap = last_hours(24)
    assert snap.pending["youtube_shorts"] == 2
    assert snap.pending["tiktok"] == 1


def test_last_hours_overdue_count(fresh_env) -> None:
    from src.core.health import last_hours
    now = datetime.now(timezone.utc)
    _add_scheduled("youtube_shorts", now - timedelta(hours=2))
    _add_scheduled("tiktok", now + timedelta(hours=3))
    snap = last_hours(24)
    assert snap.overdue == 1


def test_last_hours_spend_from_costs_jsonl(fresh_env) -> None:
    from src.core.health import last_hours
    now = datetime.now(timezone.utc)
    runs_dir = fresh_env / "runs"
    costs = runs_dir.parent / "costs.jsonl"
    _append_jsonl(costs, {
        "ts": now.isoformat(), "provider": "gemini", "operation": "llm",
        "units": 1, "unit_cost_usd": 0.01, "cost_usd": 0.01, "meta": {},
    })
    _append_jsonl(costs, {
        "ts": (now - timedelta(hours=2)).isoformat(), "provider": "gemini",
        "operation": "llm", "units": 1, "unit_cost_usd": 0.01,
        "cost_usd": 0.02, "meta": {},
    })
    _append_jsonl(costs, {
        "ts": (now - timedelta(hours=72)).isoformat(),  # outside 24h window
        "provider": "gemini", "operation": "llm", "units": 1,
        "unit_cost_usd": 0.01, "cost_usd": 0.99, "meta": {},
    })
    snap = last_hours(24)
    assert round(snap.spend["gemini"], 4) == 0.03


def test_last_hours_event_counts(fresh_env) -> None:
    from src.core.health import last_hours
    now = datetime.now(timezone.utc)
    runs_dir = fresh_env / "runs"
    events = runs_dir.parent / "events.jsonl"
    for _ in range(2):
        _append_jsonl(events, {
            "ts": now.isoformat(), "story_id": "x",
            "event": "blocked", "data": {},
        })
    _append_jsonl(events, {
        "ts": now.isoformat(), "story_id": "x",
        "event": "failed_no_images", "data": {},
    })
    snap = last_hours(24)
    assert snap.events["blocked"] == 2
    assert snap.events["failed_no_images"] == 1


def test_last_hours_to_dict_is_json_serialisable(fresh_env) -> None:
    from src.core.health import last_hours
    snap = last_hours(24)
    payload = snap.model_dump_json()
    json.loads(payload)   # round-trips
```

- [ ] **Step 7.2: Run the test to confirm it fails**

```
pytest tests/test_health.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.core.health'`.

- [ ] **Step 7.3: Implement `src/core/health.py`**

```python
"""Operational health snapshot aggregating runs, schedules, costs, events."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from src.core.config import runs_dir
from src.core.storage import RunRow, engine


class HealthSnapshot(BaseModel):
    window_hours: int
    runs: dict[str, int] = Field(default_factory=dict)
    top_errors: list[tuple[str, int]] = Field(default_factory=list)
    pending: dict[str, int] = Field(default_factory=dict)
    overdue: int = 0
    spend: dict[str, float] = Field(default_factory=dict)
    events: dict[str, int] = Field(default_factory=dict)


def _read_jsonl_in_window(path: Path, cutoff: datetime) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts = rec.get("ts")
            if not ts:
                continue
            try:
                when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if when >= cutoff:
                out.append(rec)
    return out


def last_hours(hours: int = 24) -> HealthSnapshot:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    snap = HealthSnapshot(window_hours=hours)

    with Session(engine()) as s:
        rows = list(s.exec(
            select(RunRow).where(RunRow.started_at >= cutoff)
        ))
    snap.runs = dict(Counter(r.status for r in rows))
    err_counter = Counter(r.error for r in rows if r.error)
    snap.top_errors = err_counter.most_common(5)

    # ScheduledPostRow lives in the publish module; import lazily to avoid
    # forcing schedule code to load when not needed.
    from src.publish.scheduler import ScheduledPostRow, _ensure_table
    _ensure_table()
    now = datetime.now(timezone.utc)
    pending: Counter[str] = Counter()
    overdue = 0
    with Session(engine()) as s:
        for row in s.exec(
            select(ScheduledPostRow).where(ScheduledPostRow.status == "planned")
        ):
            pending[row.platform] += 1
            if row.planned_for < now:
                overdue += 1
    snap.pending = dict(pending)
    snap.overdue = overdue

    base = runs_dir().parent
    spend: dict[str, float] = {}
    for rec in _read_jsonl_in_window(base / "costs.jsonl", cutoff):
        provider = rec.get("provider", "?")
        spend[provider] = spend.get(provider, 0.0) + float(rec.get("cost_usd", 0.0))
    snap.spend = spend

    events: Counter[str] = Counter()
    for rec in _read_jsonl_in_window(base / "events.jsonl", cutoff):
        events[rec.get("event", "?")] += 1
    snap.events = dict(events)

    return snap
```

- [ ] **Step 7.4: Run the test to confirm it passes**

```
pytest tests/test_health.py -v
```

Expected: all seven tests pass.

- [ ] **Step 7.5: Add the `cli health` command**

Append to `src/cli.py` (right above the `if __name__ == "__main__":` line):

```python
@app.command("health")
def health_cmd(
    hours: int = typer.Option(24, help="Window size"),
    as_json: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Show a health snapshot: runs, schedule pending, spend, events."""
    _setup_logging()
    from src.core.health import last_hours
    snap = last_hours(hours)
    if as_json:
        console.print_json(snap.model_dump_json())
        return

    runs_table = Table(title=f"Runs (last {hours}h)")
    runs_table.add_column("status")
    runs_table.add_column("count", justify="right")
    for status, count in sorted(snap.runs.items()):
        runs_table.add_row(status, str(count))
    console.print(runs_table)

    if snap.top_errors:
        err_table = Table(title="Top errors")
        err_table.add_column("error")
        err_table.add_column("count", justify="right")
        for err, count in snap.top_errors:
            err_table.add_row(err[:80], str(count))
        console.print(err_table)

    sched_table = Table(title=f"Schedule (overdue: {snap.overdue})")
    sched_table.add_column("platform")
    sched_table.add_column("pending", justify="right")
    for platform, count in sorted(snap.pending.items()):
        sched_table.add_row(platform, str(count))
    console.print(sched_table)

    if snap.spend:
        spend_table = Table(title=f"Spend (last {hours}h)")
        spend_table.add_column("provider")
        spend_table.add_column("USD", justify="right")
        for provider, usd in sorted(snap.spend.items(), key=lambda kv: -kv[1]):
            spend_table.add_row(provider, f"${usd:.4f}")
        console.print(spend_table)

    if snap.events:
        ev_table = Table(title=f"Events (last {hours}h)")
        ev_table.add_column("event")
        ev_table.add_column("count", justify="right")
        for ev, count in sorted(snap.events.items(), key=lambda kv: -kv[1]):
            ev_table.add_row(ev, str(count))
        console.print(ev_table)
```

- [ ] **Step 7.6: Run the full test suite**

```
pytest -x -q
```

Expected: all tests pass.

- [ ] **Step 7.7: Smoke-test the CLI command**

```
python -m src.cli health --hours 72
python -m src.cli health --json
```

Expected: tables render (or "no rows" placeholders) without errors; `--json` prints valid JSON.

- [ ] **Step 7.8: Commit**

```
git add src/core/health.py src/cli.py tests/test_health.py
git commit -m "feat(cli): add health command with runs/schedule/spend/events snapshot"
```

---

## Task 8: Final integration check

This task is verification, not new code. It confirms that the foundation is intact end-to-end before declaring Plan 1 complete.

- [ ] **Step 8.1: Run the full test suite from a clean cache**

```
pytest -x -q --cache-clear
```

Expected: every test passes. Note any new tests added during this plan should be in: `test_context.py`, `test_logging.py`, `test_configs.py`, `test_runner.py`, `test_scheduler_lock.py`, `test_storage_dedup_index.py`, `test_health.py`.

- [ ] **Step 8.2: Verify the CLI surface is intact**

```
python -m src.cli --help
python -m src.cli run --help
python -m src.cli health --help
python -m src.cli schedule
python -m src.cli costs
```

Expected: all commands respond without traceback. `schedule` and `costs` may print "no rows" placeholders — that's fine.

- [ ] **Step 8.3: Verify config errors are surfaced**

Temporarily corrupt a brand overlay to confirm validation fires:

```
mkdir -p config/brands/_smoketest
printf 'dedup:\n  simhash_threshold: not-an-int\n' > config/brands/_smoketest/filters.yaml
python -m src.cli --brand _smoketest --help
```

Expected: command exits non-zero with `config error` message naming `simhash_threshold`. Now clean up:

```
rm -rf config/brands/_smoketest
```

- [ ] **Step 8.4: Verify runner stage list**

```
python -c "from src.pipeline.runner import STAGES; from src.pipeline.stages.legacy import LegacyMonolithStage; print([type(s).__name__ for s in [LegacyMonolithStage()]])"
```

Expected output: `['LegacyMonolithStage']`. (We don't import `STAGES` after lazy population to avoid pulling in pipeline deps.)

- [ ] **Step 8.5: No-op final commit if needed, then push**

If any docstrings or imports drifted during the plan, commit them now:

```
git status
# if anything is dirty:
git add -A && git commit -m "chore: tidy after pipeline-foundation plan"
```

Push the branch:

```
git push -u origin claude/design-framework-structure-ZCQBr
```

Expected: push succeeds. Plan 1 is complete.

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| §1.1 `Context` model | Task 1 |
| §1.2 `Stage` protocol | Task 4 (Subtask 4B) |
| §1.3 `runner.py` with caching/force/error | Task 4 (Subtask 4B) |
| §1.4 `process_one` legacy wrapper | Task 4 (Subtask 4C) |
| §2 Structured logging (`JsonFormatter`, `bind_log`) | Task 2 |
| §3 `AppConfig` validation | Task 3 |
| §4 Scheduler `BEGIN IMMEDIATE` | Task 5 |
| §6 Dedup index + `has_near_duplicate` | Task 6 |
| §5 Health dashboard CLI | Task 7 |
| §12.4 Sprint 1 ordering — keep `process_one` working | Task 4 (Subtask 4C); Task 8 |

Sprint 1 items 1–6 from §12.4 are all covered. Tasks beyond Sprint 1 (`§7` script_critique, `§8`–`§11` content upgrades) are explicitly out of scope for this plan.

**2. Placeholder scan**

Searched for: `TBD`, `TODO`, `implement later`, `appropriate error handling`, `add validation`, `Similar to Task`. None present. Every step shows the actual code or exact command.

**3. Type consistency**

- `Context` field names referenced across tasks: `run_id`, `story_id`, `brand`, `run_dir`, `story`, `opts`, `processed`, `chapter_ranges`, `long_video`, `shorts`, `thumbnail_variants`, `images` — defined in Task 1, used in Tasks 4 and 7 with identical names.
- `Stage` protocol attribute `name` and methods `run`, `is_cached`, `clear` — defined in Task 4 (Subtask 4B), used by `LegacyMonolithStage` in Subtask 4C and the tests in `test_runner.py`.
- `RunOptions` — defined in Task 1, re-imported via `src.pipeline` shim in Task 4 (so existing `from src.pipeline import RunOptions` keeps working).
- `has_near_duplicate(our_hash, *, threshold, since_days, batch)` — signature defined in Task 6 step 6.3, monkeypatched with the same kwargs in step 6.6.
- `HealthSnapshot.runs / pending / overdue / spend / events / top_errors / window_hours` — defined in Task 7 step 7.3 and asserted with the same names in step 7.1.
- `_next_slot(platform, cadence, sess)` — defined in Task 5 step 5.3; the old caller in `enqueue` is updated in the same step.

**4. Behaviour preservation**

- `src/pipeline.py → src/pipeline/legacy.py` is a verbatim move; `src/pipeline/__init__.py` re-exports the public names so any code doing `from src.pipeline import RunOptions, process_one, choose_profile` continues to work unchanged.
- `recent_simhashes` stays in `src/core/storage.py` even though no production code calls it after Task 6 — that's intentional, so external scripts/notebooks aren't broken. (Removal is fair game in Sprint 2 if it's still unused.)
- `cli.py::run` no longer prints `RenderArtifacts.model_dump_json` — it prints a smaller summary dict instead. Documented in step 4.14.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-25-pipeline-foundation-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
