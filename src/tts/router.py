"""Router that tries providers in order and caches results."""
from __future__ import annotations

import logging
from pathlib import Path

from src.core import config
from src.tts import cache
from src.tts.base import TTSProvider

log = logging.getLogger(__name__)


def _build(name: str) -> TTSProvider:
    if name == "google_chirp":
        from src.tts.google_chirp import GoogleChirpTTS
        return GoogleChirpTTS()
    if name == "silero_local":
        from src.tts.silero_local import SileroLocalTTS
        return SileroLocalTTS()
    if name == "openai_tts":
        from src.tts.openai_tts import OpenAITTS
        return OpenAITTS()
    if name == "edge_tts":
        from src.tts.edge_tts import EdgeTTS
        return EdgeTTS()
    raise KeyError(f"unknown TTS provider: {name}")


class TTSRouter:
    def __init__(self) -> None:
        cfg = config.voices().get("router", {})
        self.chain: list[str] = [cfg.get("primary", "google_chirp"), *cfg.get("fallback_chain", [])]
        self.use_cache = config.voices().get("cache", {}).get("enabled", True)

    def synthesize(self, text: str, out_path: Path, voice_hint: str | None = None) -> Path:
        for provider_name in self.chain:
            try:
                provider = _build(provider_name)
                voice_id = voice_hint or provider_name
                k = cache.key(provider_name, voice_id, text)

                if self.use_cache:
                    suffix = ".mp3" if provider_name == "edge_tts" else ".wav"
                    hit = cache.lookup(k, suffix=suffix)
                    if hit is not None:
                        log.info("tts cache hit: %s", k)
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_bytes(hit.read_bytes())
                        return out_path

                provider.synthesize(text, out_path)
                if self.use_cache:
                    cache.store(k, out_path, suffix=out_path.suffix)
                return out_path
            except Exception as exc:
                log.warning("tts provider %s failed: %s", provider_name, exc)
                continue

        raise RuntimeError("all TTS providers failed; check credentials or install silero")
