"""Twitter/X adapter via twscrape (no official API)."""
from __future__ import annotations

import logging
from datetime import timezone

from src.core import config
from src.core.models import Lang, Metrics, Source, Story
from src.core.scoring import growth_score, long_form_potential
from src.sources.base import SourceAdapter
from src.sources.reddit import _detect_lang_cheap

log = logging.getLogger(__name__)


class TwitterAdapter(SourceAdapter):
    name = "twitter"

    def __init__(self) -> None:
        self.cfg = config.sources().get("twitter", {})
        self._api = None

    async def _api_get(self):
        if self._api is None:
            try:
                from twscrape import API
            except ImportError as e:  # pragma: no cover
                raise RuntimeError("Install twscrape: pip install twscrape") from e
            self._api = API(config.env("TWSCRAPE_DB", "./.data/twscrape.db"))
        return self._api

    async def fetch(self, limit: int = 100) -> list[Story]:
        if not self.cfg.get("enabled", True):
            return []
        api = await self._api_get()
        out: list[Story] = []

        for query in self.cfg.get("queries", []):
            try:
                async for tweet in api.search(query, limit=limit):
                    story = self._to_story(tweet)
                    if story:
                        out.append(story)
            except Exception as exc:
                log.warning("twitter search %r failed: %s", query, exc)

        for handle in self.cfg.get("accounts", []):
            try:
                user = await api.user_by_login(handle.lstrip("@"))
                if not user:
                    continue
                async for tweet in api.user_tweets(user.id, limit=limit):
                    story = self._to_story(tweet)
                    if story:
                        out.append(story)
            except Exception as exc:
                log.warning("twitter user %s failed: %s", handle, exc)

        return out

    @staticmethod
    def _to_story(tweet) -> Story | None:
        text = (getattr(tweet, "rawContent", "") or getattr(tweet, "content", "") or "").strip()
        if not text:
            return None

        created = getattr(tweet, "date", None)
        if created is None:
            return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        user = getattr(tweet, "user", None)
        handle = getattr(user, "username", None) if user else None

        m = Metrics(
            favorites=int(getattr(tweet, "likeCount", 0) or 0),
            retweets=int(getattr(tweet, "retweetCount", 0) or 0),
            comments=int(getattr(tweet, "replyCount", 0) or 0),
            views=int(getattr(tweet, "viewCount", 0) or 0),
        )
        tweet_id = str(getattr(tweet, "id", ""))
        story = Story(
            id=f"twitter:{tweet_id}",
            source=Source.TWITTER,
            source_id=tweet_id,
            permalink=getattr(tweet, "url", "") or f"https://x.com/{handle}/status/{tweet_id}",
            author=handle,
            title=(text[:120] + "...") if len(text) > 120 else text,
            text=text,
            lang_detected=_detect_lang_cheap(text),
            created_at=created,
            metrics=m,
        )
        story.growth_score = growth_score(story.source, story.metrics, story.created_at)
        story.long_form_potential = long_form_potential(story)
        return story
