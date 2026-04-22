"""Flux via Replicate — cheap (~$0.003/img) and stable."""
from __future__ import annotations

import logging
from pathlib import Path

from src.core import config
from src.images.base import ImageProvider

log = logging.getLogger(__name__)


_ASPECT = {"16:9": "16:9", "9:16": "9:16", "1:1": "1:1"}


class FluxReplicateProvider(ImageProvider):
    name = "flux_replicate"

    def __init__(self) -> None:
        self.cfg = config.images().get("flux_replicate", {})
        self.token = config.env("REPLICATE_API_TOKEN")

    def generate(self, prompt: str, n: int, ratio: str, out_dir: Path) -> list[Path]:
        if not self.token:
            log.info("flux_replicate: no REPLICATE_API_TOKEN, skipping")
            return []

        import replicate
        import requests

        client = replicate.Client(api_token=self.token)
        model = self.cfg.get("model", "black-forest-labs/flux-schnell")
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []

        for i in range(n):
            try:
                outputs = client.run(
                    model,
                    input={
                        "prompt": prompt,
                        "aspect_ratio": _ASPECT.get(ratio, "16:9"),
                        "num_inference_steps": int(self.cfg.get("num_inference_steps", 4)),
                        "guidance": float(self.cfg.get("guidance", 3.5)),
                        "output_format": "webp",
                        "output_quality": 90,
                    },
                )
                # Replicate returns a list of file URLs or a single URL
                urls = outputs if isinstance(outputs, list) else [outputs]
                for j, url in enumerate(urls[: max(1, n)]):
                    r = requests.get(str(url), timeout=60)
                    r.raise_for_status()
                    out = out_dir / f"flux_{i}_{j}.webp"
                    out.write_bytes(r.content)
                    paths.append(out)
            except Exception as exc:
                log.warning("flux_replicate generation failed: %s", exc)
                break
        return paths
