"""Flux via Replicate — cheap (~$0.003/img) and stable."""
from __future__ import annotations

import logging
from pathlib import Path

from src.core import config, costs
from src.core.resilience import CircuitBreaker, retry
from src.images.base import ImageProvider

log = logging.getLogger(__name__)


_ASPECT = {"16:9": "16:9", "9:16": "9:16", "1:1": "1:1"}


_breaker = CircuitBreaker("flux_replicate", threshold=3, cooldown_sec=3600)
_UNIT_COST = 0.003  # flux-schnell per image, approx


class FluxReplicateProvider(ImageProvider):
    name = "flux_replicate"

    def __init__(self) -> None:
        self.cfg = config.images().get("flux_replicate", {})
        self.token = config.env("REPLICATE_API_TOKEN")
        self.cap_usd = float(config.images().get("router", {}).get("per_month_cap_usd", 0))

    @retry(attempts=3, initial=1.5, factor=2)
    def _run(self, client, model, params):
        return client.run(model, input=params)

    def generate(self, prompt: str, n: int, ratio: str, out_dir: Path) -> list[Path]:
        if not self.token:
            log.info("flux_replicate: no REPLICATE_API_TOKEN, skipping")
            return []

        # Budget gate: skip when monthly cap would be exceeded.
        if self.cap_usd and not costs.check_budget(
            "flux_replicate", _UNIT_COST * n, self.cap_usd,
        ):
            log.warning("flux_replicate budget cap hit (%.2f USD) — skipping", self.cap_usd)
            return []

        @_breaker
        def _call():
            import replicate
            import requests
            client = replicate.Client(api_token=self.token)
            model = self.cfg.get("model", "black-forest-labs/flux-schnell")
            out_dir.mkdir(parents=True, exist_ok=True)
            paths: list[Path] = []

            for i in range(n):
                outputs = self._run(client, model, {
                    "prompt": prompt,
                    "aspect_ratio": _ASPECT.get(ratio, "16:9"),
                    "num_inference_steps": int(self.cfg.get("num_inference_steps", 4)),
                    "guidance": float(self.cfg.get("guidance", 3.5)),
                    "output_format": "webp",
                    "output_quality": 90,
                })
                urls = outputs if isinstance(outputs, list) else [outputs]
                for j, url in enumerate(urls[: max(1, n)]):
                    r = requests.get(str(url), timeout=60)
                    r.raise_for_status()
                    out = out_dir / f"flux_{i}_{j}.webp"
                    out.write_bytes(r.content)
                    paths.append(out)
            return paths

        try:
            paths = _call()
        except Exception as exc:
            log.warning("flux_replicate failed: %s", exc)
            return []
        costs.track("flux_replicate", "image", len(paths), _UNIT_COST, {"prompt": prompt})
        return paths
