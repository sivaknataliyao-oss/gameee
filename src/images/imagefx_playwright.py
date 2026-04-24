"""Playwright → Google Labs ImageFX (Imagen). Fragile, requires manual setup.

Steps:
  1) python -m src.images.setup_auth --provider imagefx
  2) log in to your Google account at labs.google/fx/tools/image-fx
  3) session saved to ./.data/imagefx_session.json
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.core import config
from src.images.base import ImageProvider

log = logging.getLogger(__name__)


class ImageFXPlaywrightProvider(ImageProvider):
    name = "imagefx_playwright"

    def __init__(self) -> None:
        self.cfg = config.images().get("imagefx_playwright", {})
        self.session_path = Path(config.env("IMAGEFX_SESSION_PATH", "./.data/imagefx_session.json"))

    def generate(self, prompt: str, n: int, ratio: str, out_dir: Path) -> list[Path]:
        if not self.session_path.exists():
            log.info("imagefx_playwright: no session, run setup_auth first")
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
                    await page.goto(
                        self.cfg.get("url", "https://labs.google/fx/tools/image-fx"),
                        timeout=int(self.cfg.get("timeout_sec", 120)) * 1000,
                    )
                    await page.wait_for_load_state("networkidle")

                    ta = page.locator("textarea").first
                    await ta.fill(prompt)
                    # Generate button (subject to change):
                    gen = page.get_by_role("button", name=lambda s: bool(s and "Create" in s))
                    await gen.first.click()
                    await page.wait_for_timeout(8000)

                    # Collect image urls — ImageFX typically renders 4 per call.
                    for _ in range(30):
                        imgs = await page.query_selector_all("img[alt*='Generated image']")
                        if len(imgs) >= n:
                            break
                        await asyncio.sleep(2)

                    imgs = await page.query_selector_all("img[alt*='Generated image']")
                    for i, img in enumerate(imgs[:n]):
                        src = await img.get_attribute("src")
                        if not src:
                            continue
                        resp = await context.request.get(src)
                        if resp.ok:
                            out = out_dir / f"imagefx_{i}.png"
                            out.write_bytes(await resp.body())
                            paths.append(out)
                except Exception as exc:
                    log.warning("imagefx_playwright error: %s", exc)
                finally:
                    await context.close()
                    await browser.close()
            return paths

        try:
            return asyncio.run(_run())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_run())
            finally:
                loop.close()
