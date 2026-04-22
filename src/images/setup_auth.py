"""Interactive login to persist a Playwright storage_state for UI scrapers.

Usage:
    python -m src.images.setup_auth --provider chatgpt
    python -m src.images.setup_auth --provider imagefx
    python -m src.images.setup_auth --provider threads

Opens a real browser, you log in manually, the script saves cookies + localStorage.
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from src.core import config

PROVIDERS = {
    "chatgpt": (
        "https://chatgpt.com/",
        config.env("CHATGPT_SESSION_PATH", "./.data/chatgpt_session.json"),
    ),
    "imagefx": (
        "https://labs.google/fx/tools/image-fx",
        config.env("IMAGEFX_SESSION_PATH", "./.data/imagefx_session.json"),
    ),
    "threads": (
        "https://www.threads.net/login",
        config.env("THREADS_SESSION_PATH", "./.data/threads_session.json"),
    ),
}


async def _setup(url: str, path: str) -> None:
    from playwright.async_api import async_playwright

    Path(path).parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url)
        print(f"[setup_auth] log into {url} in the opened window.")
        print("[setup_auth] when done, press Enter in this terminal...")
        await asyncio.get_event_loop().run_in_executor(None, input)
        await context.storage_state(path=path)
        await browser.close()
        print(f"[setup_auth] saved session: {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=list(PROVIDERS))
    args = ap.parse_args()
    url, path = PROVIDERS[args.provider]
    asyncio.run(_setup(url, path))


if __name__ == "__main__":
    main()
