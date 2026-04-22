"""OpenAI gpt-4o-mini-tts — emotional Russian TTS with prompt control."""
from __future__ import annotations

import logging
from pathlib import Path

from src.core import config
from src.tts.base import TTSProvider

log = logging.getLogger(__name__)


class OpenAITTS(TTSProvider):
    name = "openai_tts"

    def __init__(self) -> None:
        cfg = config.voices().get("voices", {}).get("openai_tts", {})
        self.model = cfg.get("model", "gpt-4o-mini-tts")
        self.voice = cfg.get("voice", "coral")
        self.instructions = cfg.get("instructions", "")

    def synthesize(self, text: str, out_path: Path) -> Path:
        from openai import OpenAI

        client = OpenAI(api_key=config.env("OPENAI_API_KEY"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with client.audio.speech.with_streaming_response.create(
            model=self.model,
            voice=self.voice,
            input=text,
            instructions=self.instructions,
            response_format="wav",
        ) as resp:
            resp.stream_to_file(str(out_path))
        log.info("openai tts ok: %s", out_path)
        return out_path
