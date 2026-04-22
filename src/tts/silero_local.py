"""Silero v5_ru — local, CPU-friendly, with built-in stress + yo handling."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from src.core import config
from src.tts.base import TTSProvider

log = logging.getLogger(__name__)


@lru_cache
def _load_model():
    import torch  # noqa: F401 (side-effect: ensures torch is present)
    cfg = config.voices().get("voices", {}).get("silero_local", {})
    model_id = cfg.get("model_id", "v5_ru")
    # Silero ships via torch.hub. This is the official load pattern.
    model, _ = torch.hub.load(
        repo_or_dir="snakers4/silero-models",
        model="silero_tts",
        language="ru",
        speaker=model_id,
        trust_repo=True,
    )
    return model, cfg


class SileroLocalTTS(TTSProvider):
    name = "silero_local"

    def synthesize(self, text: str, out_path: Path) -> Path:
        import soundfile as sf

        model, cfg = _load_model()
        sample_rate = int(cfg.get("sample_rate", 48000))
        speaker = cfg.get("speaker", "kseniya")

        audio = model.apply_tts(
            text=text,
            speaker=speaker,
            sample_rate=sample_rate,
            put_accent=bool(cfg.get("put_accent", True)),
            put_yo=bool(cfg.get("put_yo", True)),
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), audio.cpu().numpy(), sample_rate, subtype="PCM_16")
        log.info("silero tts ok: %s", out_path)
        return out_path
