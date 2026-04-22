"""Reddit adapter using asyncpraw (OAuth). Respects 100 QPM cap."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable

import asyncpraw

from src.core import config
from src.core.models import Lang, Metrics, Source, Story
from src.core.scoring import growth_score, long_form_potential
from src.sources.base import SourceAdapter

log = logging.getLogger(__name__)


def _detect_lang_cheap(text: str) -> Lang:
    if not text:
        return Lang.OTHER
    cyr = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in text if "a" <= c.lower() <= "z")
    if cyr > lat * 0.5:
        return Lang.RU
    if lat > 50:
        return Lang.EN
    return Lang.OTHER


class RedditAdapter(SourceAdapter):
    name = "reddit"

    def __init__(self) -> None:
        self.cfg = config.sources().get("reddit", {})
        self._client: asyncpraw.Reddit | None = None
        self._semaphore = asyncio.Semaphore(3)  # ~1.5 QPS, well under 100 QPM

    async def _reddit(self) -> asyncpraw.Reddit:
        if self._client is None:
            self._client = asyncpraw.Reddit(
                client_id=config.env("REDDIT_CLIENT_ID"),
                client_secret=config.env("REDDIT_CLIENT_SECRET"),
                user_agent=config.env("REDDIT_USER_AGENT", "gameee/0.1"),
                username=config.env("REDDIT_USERNAME"),
                password=config.env("REDDIT_PASSWORD"),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def fetch(self, limit: int = 100) -> list[Story]:
        if not self.cfg.get("enabled", True):
            return []

        reddit = await self._reddit()
        out: list[Story] = []
        subs: Iterable[dict] = self.cfg.get("subreddits", [])

        for sub in subs:
            name = sub["name"]
            sorts = sub.get("sort", ["new"])
            min_up = sub.get("min_upvotes", 0)

            for sort in sorts:
                try:
                    async with self._semaphore:
                        subreddit = await reddit.subreddit(name)
                        listing = self._listing(subreddit, sort, limit)
                        async for post in listing:
                            if post.stickied or post.over_18 and self.cfg.get(
                                "block_over_18", True
                            ):
                                continue
                            if post.score < min_up:
                                continue
                            text = (post.selftext or "") or post.title
                            lang = _detect_lang_cheap(text)
                            s = Story(
                                id=f"reddit:{post.id}",
                                source=Source.REDDIT,
                                source_id=post.id,
                                permalink=f"https://reddit.com{post.permalink}",
                                author=(post.author.name if post.author else None),
                                title=post.title,
                                text=post.selftext or "",
                                lang_detected=lang,
                                nsfw=bool(post.over_18),
                                created_at=datetime.fromtimestamp(
                                    post.created_utc, tz=timezone.utc
                                ),
                                metrics=Metrics(
                                    upvotes=int(post.score),
                                    comments=int(post.num_comments),
                                    upvote_ratio=float(post.upvote_ratio or 0),
                                ),
                            )
                            s.growth_score = growth_score(s.source, s.metrics, s.created_at)
                            s.long_form_potential = long_form_potential(s)
                            out.append(s)
                except Exception as exc:  # one sub/sort shouldn't kill the scan
                    log.warning("reddit fetch %s/%s failed: %s", name, sort, exc)
                    continue

        return out

    @staticmethod
    def _listing(subreddit, sort: str, limit: int):
        sort = sort.lower()
        if sort == "new":
            return subreddit.new(limit=limit)
        if sort == "rising":
            return subreddit.rising(limit=limit)
        if sort == "top":
            return subreddit.top(limit=limit)
        return subreddit.hot(limit=limit)
