"""Pipeline orchestration. Public API re-exported from the legacy monolith
during Sprint 1; Sprint 2 will replace these names with per-stage modules.
"""
from src.pipeline.legacy import (
    RunOptions,
    _chapter_ranges_from_segments,
    choose_profile,
    process_one,
)

__all__ = ["RunOptions", "choose_profile", "process_one"]
