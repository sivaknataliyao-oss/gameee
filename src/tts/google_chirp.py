"""Google Cloud TTS — Chirp 3 HD (Russian). Our primary TTS."""
from __future__ import annotations

import logging
from pathlib import Path

from src.core import config
from src.tts.base import TTSProvider

log = logging.getLogger(__name__)


class GoogleChirpTTS(TTSProvider):
    name = "google_chirp"

    def __init__(self) -> None:
        cfg = config.voices().get("voices", {}).get("google_chirp", {})
        self.voice = cfg.get("female_default", "ru-RU-Chirp3-HD-Kore")
        self.rate = float(cfg.get("speaking_rate", 1.0))

    def synthesize(self, text: str, out_path: Path) -> Path:
        from google.cloud import texttospeech

        client = texttospeech.TextToSpeechClient()
        input_ = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="ru-RU",
            name=self.voice,
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=24000,
            speaking_rate=self.rate,
        )
        resp = client.synthesize_speech(
            input=input_, voice=voice, audio_config=audio_config
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.audio_content)
        log.info("chirp tts ok: %s (%d bytes)", out_path, len(resp.audio_content))
        return out_path
