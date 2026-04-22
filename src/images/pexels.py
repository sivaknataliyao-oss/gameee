"""Pexels stock photos. Free, commercial OK, lightning fast."""
from __future__ import annotations

import logging
from pathlib import Path

import requests

from src.core import config
from src.images.base import ImageProvider

log = logging.getLogger(__name__)


class PexelsProvider(ImageProvider):
    name = "pexels"

    def __init__(self) -> None:
        self.api_key = config.env("PEXELS_API_KEY")
        self.cfg = config.images().get("pexels", {})

    def generate(self, prompt: str, n: int, ratio: str, out_dir: Path) -> list[Path]:
        if not self.api_key:
            log.info("pexels: no PEXELS_API_KEY, skipping")
            return []
        orientation = (
            self.cfg.get("orientation_for_long", "landscape")
            if ratio == "16:9"
            else self.cfg.get("orientation_for_shorts", "portrait")
        )
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": self.api_key},
            params={
                "query": prompt,
                "per_page": self.cfg.get("per_page", 20),
                "orientation": orientation,
                "size": "large",
            },
            timeout=15,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: list[Path] = []
        for i, ph in enumerate(photos[:n]):
            url = ph["src"].get("large2x") or ph["src"].get("original")
            if not url:
                continue
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            out = out_dir / f"pexels_{ph['id']}.jpg"
            out.write_bytes(resp.content)
            paths.append(out)
        log.info("pexels: got %d/%d for %r", len(paths), n, prompt)
        return paths
