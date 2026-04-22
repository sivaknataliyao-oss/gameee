"""Registry of available source adapters."""
from __future__ import annotations

from src.sources.base import SourceAdapter
from src.sources.reddit import RedditAdapter
from src.sources.threads import ThreadsAdapter
from src.sources.twitter import TwitterAdapter


def all_adapters() -> list[SourceAdapter]:
    return [RedditAdapter(), TwitterAdapter(), ThreadsAdapter()]


def by_name(name: str) -> SourceAdapter:
    m = {a.name: a for a in all_adapters()}
    if name not in m:
        raise KeyError(f"Unknown source: {name}. Available: {list(m)}")
    return m[name]
