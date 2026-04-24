"""Google Cloud TTS — Chirp 3 HD (Russian). Our primary TTS."""
from __future__ import annotations

import logging
from pathlib import Path

from src.core import config, costs
from src.core.resilience import CircuitBreaker, retry
from src.tts.base import TTSProvider

log = logging.getLogger(__name__)

_breaker = CircuitBreaker("google_chirp", threshold=3, cooldown_sec=600)
# Chirp 3 HD: $30/1M chars; 1M chars/month free. We charge $0 until the free
# tier is gone — cost tracker is still useful to know remaining free quota.
_PER_CHAR = 30.0 / 1_000_000
_FREE_CHARS_PER_MONTH = 1_000_000


class GoogleChirpTTS(TTSProvider):
    name = "google_chirp"

    def __init__(self) -> None:
        cfg = config.voices().get("voices", {}).get("google_chirp", {})
        self.voice = cfg.get("female_default", "ru-RU-Chirp3-HD-Kore")
        self.rate = float(cfg.get("speaking_rate", 1.0))

    @_breaker
    @retry(attempts=3, initial=1.5, factor=2.0)
    def _synth(self, client, input_, voice, audio_config):
        return client.synthesize_speech(
            input=input_, voice=voice, audio_config=audio_config,
        )

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
        resp = self._synth(client, input_, voice, audio_config)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.audio_content)

        # Account only paid chars (anything past the monthly free tier).
        used_this_month = int(
            costs.monthly_spend("google_chirp") / max(_PER_CHAR, 1e-12)
        )
        paid_chars = max(0, (used_this_month + len(text)) - _FREE_CHARS_PER_MONTH)
        new_paid = min(len(text), paid_chars)
        costs.track("google_chirp", "chars", float(new_paid), _PER_CHAR,
                    {"voice": self.voice, "total_chars": len(text)})

        log.info("chirp tts ok: %s (%d bytes)", out_path, len(resp.audio_content))
        return out_path
