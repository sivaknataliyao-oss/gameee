"""Free Microsoft Edge TTS — fallback / prototyping only.

Uses the reverse-engineered Edge read-aloud endpoint. Quality is ~ok for Russian.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.core import config
from src.tts.base import TTSProvider

log = logging.getLogger(__name__)


class EdgeTTS(TTSProvider):
    name = "edge_tts"

    def __init__(self) -> None:
        cfg = config.voices().get("voices", {}).get("edge_tts", {})
        self.voice = cfg.get("voice", "ru-RU-SvetlanaNeural")
        self.rate = cfg.get("rate", "+0%")

    def synthesize(self, text: str, out_path: Path) -> Path:
        import edge_tts

        async def _go() -> None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            communicate = edge_tts.Communicate(text=text, voice=self.voice, rate=self.rate)
            # Edge TTS returns MP3; we save as .mp3 then let ffmpeg transcode if needed.
            await communicate.save(str(out_path))

        asyncio.run(_go())
        log.info("edge tts ok: %s", out_path)
        return out_path
