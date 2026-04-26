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
