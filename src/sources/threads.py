"""Threads.net adapter via Playwright. Uses saved storage_state.json session.

Public Threads has no read API; we drive a real browser.
Run `python -m src.images.setup_auth --provider threads` or our setup script
to establish a session, then flip `enabled: true` in sources.yaml.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core import config
from src.core.models import Lang, Metrics, Source, Story
from src.core.scoring import growth_score, long_form_potential
from src.sources.base import SourceAdapter
from src.sources.reddit import _detect_lang_cheap

log = logging.getLogger(__name__)


class ThreadsAdapter(SourceAdapter):
    name = "threads"

    def __init__(self) -> None:
        self.cfg = config.sources().get("threads", {})
        self.session_path = Path(
            config.env("THREADS_SESSION_PATH", "./.data/threads_session.json")
        )

    async def fetch(self, limit: int = 50) -> list[Story]:
        if not self.cfg.get("enabled", False):
            return []
        if not self.session_path.exists():
            log.warning("threads session not found: %s — run setup_auth first", self.session_path)
            return []

        from playwright.async_api import async_playwright

        out: list[Story] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=str(self.session_path))
            page = await context.new_page()

            for handle in self.cfg.get("users", []):
                handle = handle.lstrip("@")
                try:
                    await page.goto(f"https://www.threads.net/@{handle}", timeout=30_000)
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                    # Scroll a few times to load feed items.
                    for _ in range(3):
                        await page.mouse.wheel(0, 4000)
                        await asyncio.sleep(1.0)
                    data = await self._extract_posts(page, limit)
                    for p in data:
                        out.append(self._to_story(p, author=handle))
                except Exception as exc:
                    log.warning("threads @%s failed: %s", handle, exc)

            for tag in self.cfg.get("hashtags", []):
                tag = tag.lstrip("#")
                try:
                    await page.goto(f"https://www.threads.net/tag/{tag}", timeout=30_000)
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                    for _ in range(3):
                        await page.mouse.wheel(0, 4000)
                        await asyncio.sleep(1.0)
                    data = await self._extract_posts(page, limit)
                    for p in data:
                        out.append(self._to_story(p, author=None))
                except Exception as exc:
                    log.warning("threads #%s failed: %s", tag, exc)

            await context.close()
            await browser.close()
        return out

    @staticmethod
    async def _extract_posts(page, limit: int) -> list[dict[str, Any]]:
        # Threads embeds structured data in <script type="application/json">.
        # We collect "pk", "caption.text", timestamps, like/reply counts.
        js = """
        () => {
          const scripts = Array.from(document.querySelectorAll('script'));
          const out = [];
          const seen = new Set();
          for (const s of scripts) {
            const t = s.textContent || '';
            const matches = t.matchAll(/"pk":"(\\d+)"[^}]*?"caption":\\{"text":"((?:[^"\\\\]|\\\\.)*)"/g);
            for (const m of matches) {
              const id = m[1];
              if (seen.has(id)) continue;
              seen.add(id);
              let text = m[2].replace(/\\\\n/g, '\\n').replace(/\\\\"/g, '"');
              out.push({id, text});
            }
          }
          return out;
        }
        """
        try:
            raw = await page.evaluate(js)
        except Exception:
            raw = []
        return raw[:limit]

    @staticmethod
    def _to_story(p: dict, author: str | None) -> Story:
        now = datetime.now(timezone.utc)
        text = p.get("text", "") or ""
        story = Story(
            id=f"threads:{p.get('id','')}",
            source=Source.THREADS,
            source_id=str(p.get("id", "")),
            permalink=(
                f"https://www.threads.net/@{author}/post/{p.get('id','')}" if author else
                f"https://www.threads.net/t/{p.get('id','')}"
            ),
            author=author,
            title=(text[:120] + "...") if len(text) > 120 else text,
            text=text,
            lang_detected=_detect_lang_cheap(text),
            created_at=now,  # precise timestamp requires extra DOM parse
            metrics=Metrics(),
        )
        story.growth_score = growth_score(story.source, story.metrics, story.created_at, story.title)
        story.long_form_potential = long_form_potential(story)
        return story
