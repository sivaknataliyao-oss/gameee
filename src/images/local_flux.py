"""Local Flux on GPU (diffusers). Optional. Activated only if model_path is set."""
from __future__ import annotations

import logging
from pathlib import Path

from src.core import config
from src.images.base import ImageProvider

log = logging.getLogger(__name__)


class LocalFluxProvider(ImageProvider):
    name = "local_flux"

    def __init__(self) -> None:
        self.cfg = config.images().get("local_flux", {})
        self._pipe = None

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import FluxPipeline

        model_path = self.cfg.get("model_path") or ""
        if not model_path:
            raise RuntimeError("local_flux.model_path empty; skipping local inference")

        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        pipe = FluxPipeline.from_pretrained(model_path, torch_dtype=dtype)
        pipe.to(self.cfg.get("device", "cuda") if torch.cuda.is_available() else "cpu")
        self._pipe = pipe
        return pipe

    def generate(self, prompt: str, n: int, ratio: str, out_dir: Path) -> list[Path]:
        if not self.cfg.get("model_path"):
            log.info("local_flux: no model_path, skipping")
            return []

        try:
            pipe = self._load()
        except Exception as exc:
            log.warning("local_flux load failed: %s", exc)
            return []

        out_dir.mkdir(parents=True, exist_ok=True)
        h, w = (1080, 1920) if ratio == "16:9" else (1920, 1080)
        if ratio == "9:16":
            w, h = 1080, 1920

        paths: list[Path] = []
        for i in range(n):
            try:
                result = pipe(prompt=prompt, height=h, width=w, num_inference_steps=4)
                img = result.images[0]
                out = out_dir / f"localflux_{i}.png"
                img.save(out)
                paths.append(out)
            except Exception as exc:
                log.warning("local_flux inference failed: %s", exc)
                break
        return paths
