"""Playwright → ChatGPT UI image generation. Fragile, requires manual setup.

Steps to enable:
  1) python -m src.images.setup_auth --provider chatgpt
  2) log into chatgpt.com in the opened window
  3) session saved to ./.data/chatgpt_session.json

Risks:
  - OpenAI ToS generally forbids automated use of the consumer UI.
  - DOM selectors may change at any time.
  - Rate-limited per account.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from src.core import config
from src.images.base import ImageProvider

log = logging.getLogger(__name__)


class ChatGPTPlaywrightProvider(ImageProvider):
    name = "chatgpt_playwright"

    def __init__(self) -> None:
        self.cfg = config.images().get("chatgpt_playwright", {})
        self.session_path = Path(config.env("CHATGPT_SESSION_PATH", "./.data/chatgpt_session.json"))

    def generate(self, prompt: str, n: int, ratio: str, out_dir: Path) -> list[Path]:
        if not self.session_path.exists():
            log.info("chatgpt_playwright: no session at %s — run setup_auth", self.session_path)
            return []

        async def _run() -> list[Path]:
            from playwright.async_api import async_playwright
            out_dir.mkdir(parents=True, exist_ok=True)
            paths: list[Path] = []

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(storage_state=str(self.session_path))
                page = await context.new_page()
                try:
                    await page.goto(self.cfg.get("url", "https://chatgpt.com/"),
                                     timeout=int(self.cfg.get("timeout_sec", 120)) * 1000)
                    await page.wait_for_load_state("networkidle")

                    # Ask for an image. We nudge GPT to return one image per request to be safe.
                    full_prompt = (
                        f"Generate {n} photographic image(s) for this brief. "
                        f"Aspect ratio {ratio}. Prompt: {prompt}"
                    )
                    # Prompt textarea selector (subject to change):
                    ta = page.get_by_role("textbox")
                    await ta.fill(full_prompt)
                    await ta.press("Enter")
                    await page.wait_for_timeout(5000)

                    # Wait for image(s) to render
                    for _ in range(40):
                        imgs = await page.query_selector_all("img[alt*='Generated']")
                        if len(imgs) >= n:
                            break
                        await asyncio.sleep(2)

                    imgs = await page.query_selector_all("img[alt*='Generated']")
                    for i, img in enumerate(imgs[:n]):
                        src = await img.get_attribute("src")
                        if not src:
                            continue
                        # Download through the same context (cookies attached)
                        resp = await context.request.get(src)
                        if resp.ok:
                            data = await resp.body()
                            ext = ".png" if "png" in (resp.headers.get("content-type") or "") else ".jpg"
                            out = out_dir / f"chatgpt_{i}{ext}"
                            out.write_bytes(data)
                            paths.append(out)
                except Exception as exc:
                    log.warning("chatgpt_playwright error: %s", exc)
                finally:
                    await context.close()
                    await browser.close()
            return paths

        try:
            return asyncio.run(_run())
        except RuntimeError:
            # Nested loop? fall back to new loop
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_run())
            finally:
                loop.close()
