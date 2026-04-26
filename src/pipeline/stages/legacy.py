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
