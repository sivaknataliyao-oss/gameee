"""OpenAI Images (gpt-image-1 / DALL-E). Commercial use explicitly allowed."""
from __future__ import annotations

import base64
import logging
from pathlib import Path

from src.core import config, costs
from src.core.resilience import CircuitBreaker, retry
from src.images.base import ImageProvider

log = logging.getLogger(__name__)

_breaker = CircuitBreaker("openai_images", threshold=3, cooldown_sec=1800)
# gpt-image-1 medium ~ $0.04/image; update as OpenAI changes pricing.
_UNIT_COST = 0.04


class OpenAIImagesProvider(ImageProvider):
    name = "openai_images"

    def __init__(self) -> None:
        self.cfg = config.images().get("openai_images", {})
        self.key = config.env("OPENAI_API_KEY")
        self.cap_usd = float(config.images().get("router", {}).get("per_month_cap_usd", 0))

    @_breaker
    @retry(attempts=2, initial=2.0, factor=2.0)
    def _call(self, client, model, prompt, n, size, quality):
        return client.images.generate(
            model=model, prompt=prompt, n=n, size=size, quality=quality,
        )

    def generate(self, prompt: str, n: int, ratio: str, out_dir: Path) -> list[Path]:
        if not self.key:
            log.info("openai_images: no OPENAI_API_KEY, skipping")
            return []

        if self.cap_usd and not costs.check_budget(
            "openai_images", _UNIT_COST * n, self.cap_usd,
        ):
            log.warning("openai_images budget cap hit (%.2f USD) — skipping", self.cap_usd)
            return []

        from openai import OpenAI
        client = OpenAI(api_key=self.key)
        model = self.cfg.get("model", "gpt-image-1")
        size = self.cfg.get("size_long" if ratio == "16:9" else "size_shorts", "1024x1024")
        quality = self.cfg.get("quality", "medium")

        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        try:
            resp = self._call(client, model, prompt, n, size, quality)
            for i, img in enumerate(resp.data):
                b64 = getattr(img, "b64_json", None)
                if not b64:
                    continue
                out = out_dir / f"openai_{i}.png"
                out.write_bytes(base64.b64decode(b64))
                paths.append(out)
        except Exception as exc:
            log.warning("openai_images failed: %s", exc)
        costs.track("openai_images", "image", len(paths), _UNIT_COST, {"prompt": prompt})
        return paths
