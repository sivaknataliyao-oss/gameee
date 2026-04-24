"""Router that tries image providers in chain order with cache + budget cap."""
from __future__ import annotations

import logging
from pathlib import Path

from src.core import config
from src.images import cache
from src.images.base import ImageProvider

log = logging.getLogger(__name__)


def _build(name: str) -> ImageProvider:
    if name == "pexels":
        from src.images.pexels import PexelsProvider
        return PexelsProvider()
    if name == "flux_replicate":
        from src.images.flux_replicate import FluxReplicateProvider
        return FluxReplicateProvider()
    if name == "openai_images":
        from src.images.openai_images import OpenAIImagesProvider
        return OpenAIImagesProvider()
    if name == "chatgpt_playwright":
        from src.images.chatgpt_playwright import ChatGPTPlaywrightProvider
        return ChatGPTPlaywrightProvider()
    if name == "imagefx_playwright":
        from src.images.imagefx_playwright import ImageFXPlaywrightProvider
        return ImageFXPlaywrightProvider()
    if name == "local_flux":
        from src.images.local_flux import LocalFluxProvider
        return LocalFluxProvider()
    raise KeyError(f"unknown image provider: {name}")


def _styled(prompt: str) -> str:
    s = config.images().get("style", {})
    parts = [s.get("prefix", ""), prompt, s.get("suffix", "")]
    return ", ".join([p for p in parts if p])


class ImageRouter:
    def __init__(self) -> None:
        self.chain: list[str] = config.images().get("router", {}).get(
            "chain", ["pexels", "flux_replicate", "openai_images"]
        )
        self.use_cache = config.images().get("cache", {}).get("enabled", True)

    def generate(self, prompt: str, n: int, ratio: str, out_dir: Path) -> list[Path]:
        styled = _styled(prompt)

        if self.use_cache:
            # Cache key uses styled prompt so we don't mix styles.
            k = cache.key("chain", styled, ratio)
            hits = cache.lookup(k)
            if len(hits) >= n:
                log.info("image cache hit: %s (%d files)", k, len(hits))
                return hits[:n]

        remaining = n
        collected: list[Path] = []
        for provider_name in self.chain:
            if remaining <= 0:
                break
            try:
                provider = _build(provider_name)
                got = provider.generate(styled, remaining, ratio, out_dir)
                collected.extend(got)
                remaining -= len(got)
                if got:
                    log.info("images: %s produced %d", provider_name, len(got))
            except Exception as exc:
                log.warning("image provider %s failed: %s", provider_name, exc)
                continue

        if self.use_cache and collected:
            cache.store(cache.key("chain", styled, ratio), collected)

        return collected
