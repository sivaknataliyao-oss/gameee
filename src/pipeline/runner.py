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
        forced = stage.name in force
        if forced:
            stage.clear(ctx)
        if not forced and stage.is_cached(ctx):
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
