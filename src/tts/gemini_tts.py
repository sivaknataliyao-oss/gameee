"""Gemini 2.5 TTS provider — supports multi-speaker for dialogue segments.

Gemini TTS returns raw PCM audio; we wrap it in a WAV container so downstream
ffmpeg stages work without special-casing.

Two modes, auto-detected from input text:
  1. single-speaker: plain narration. Uses `narrator_voice` with style hint.
  2. multi-speaker: text contains `Рассказчик:` / `Герой:` / other `Имя:`
     line prefixes. Up to 2 speakers per request (Gemini limit). Any
     non-narrator character is normalized to the dialogue voice.
"""
from __future__ import annotations

import logging
import re
import struct
import wave
from pathlib import Path

from src.core import config, costs
from src.core.resilience import CircuitBreaker, retry
from src.tts.base import TTSProvider

log = logging.getLogger(__name__)

# "Имя: " at line start (Cyrillic or Latin capital + letters, colon, space/EOL).
_SPEAKER_RE = re.compile(r"^([A-ZА-ЯЁ][A-Za-zА-Яа-яЁё]{1,30}):\s*", re.MULTILINE)

# Rough cost guess for Gemini 2.5 Flash TTS output tokens.
# 1 audio token ≈ 1 PCM frame at 24 kHz; treat ~24k tokens/sec ⇒ adjust later
# if Google publishes exact rates.
_OUT_COST_PER_1M = 10.0
_IN_COST_PER_1M = 0.50

_breaker = CircuitBreaker("gemini_tts", threshold=3, cooldown_sec=600)

NARRATOR = "Рассказчик"


def has_dialogue(text: str) -> bool:
    """Return True if the text uses `Имя:` speaker prefixes on multiple lines."""
    matches = _SPEAKER_RE.findall(text or "")
    distinct = {m for m in matches}
    return len(distinct) >= 2 or (len(matches) >= 2 and matches[0] != matches[1])


def _normalize_speakers(text: str) -> tuple[str, set[str]]:
    """Collapse every non-narrator speaker name into a single "Герой" handle.

    Gemini TTS caps multi-speaker at 2 voices, so we pick Narrator + Hero.
    Returns (normalized_text, {unique_speakers_detected}).
    """
    speakers: set[str] = set()

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        speakers.add(name)
        if name.lower() in {"narrator", NARRATOR.lower(), "рассказчик"}:
            return f"{NARRATOR}: "
        return "Герой: "

    out = _SPEAKER_RE.sub(_sub, text)
    return out, speakers


class GeminiTTS(TTSProvider):
    name = "gemini_tts"

    def __init__(self) -> None:
        self.cfg = config.voices().get("voices", {}).get("gemini_tts", {})
        self.model = self.cfg.get("model", "gemini-2.5-flash-preview-tts")
        self.narrator_voice = self.cfg.get("narrator_voice", "Kore")
        self.dialogue_voice = self.cfg.get("dialogue_voice", "Charon")
        self.style_hint = self.cfg.get("style_hint", "")

    def synthesize(self, text: str, out_path: Path) -> Path:
        key = config.env("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        multi = has_dialogue(text)
        contents = text
        if multi:
            contents, _speakers = _normalize_speakers(text)

        # Build speech_config
        if multi:
            speech_config = types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=[
                        types.SpeakerVoiceConfig(
                            speaker=NARRATOR,
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=self.narrator_voice,
                                ),
                            ),
                        ),
                        types.SpeakerVoiceConfig(
                            speaker="Герой",
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=self.dialogue_voice,
                                ),
                            ),
                        ),
                    ],
                ),
            )
        else:
            speech_config = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.narrator_voice,
                    ),
                ),
            )

        # Style hint glued onto the contents (Gemini TTS uses this to steer tone).
        final_text = f"{self.style_hint}\n\n{contents}".strip() if self.style_hint else contents

        @_breaker
        @retry(attempts=3, initial=1.5, factor=2.0)
        def _call():
            return client.models.generate_content(
                model=self.model,
                contents=final_text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=speech_config,
                ),
            )

        resp = _call()
        pcm = _extract_pcm(resp)
        sample_rate = 24000     # Gemini TTS emits 24kHz mono PCM16 LE
        _write_wav(out_path, pcm, sample_rate=sample_rate)

        # Cost tracking (rough — exact tokens come in usage_metadata when available)
        try:
            usage = getattr(resp, "usage_metadata", None)
            if usage:
                costs.track(
                    "gemini_tts", "in_tokens",
                    float(usage.prompt_token_count or 0), _IN_COST_PER_1M / 1_000_000,
                    {"model": self.model, "multi": multi},
                )
                costs.track(
                    "gemini_tts", "out_tokens",
                    float(getattr(usage, "candidates_token_count", 0) or 0),
                    _OUT_COST_PER_1M / 1_000_000,
                    {"model": self.model, "multi": multi},
                )
        except Exception:
            pass

        log.info("gemini_tts ok: %s (multi=%s, %d bytes)", out_path, multi, len(pcm))
        return out_path


def _extract_pcm(resp) -> bytes:
    try:
        parts = resp.candidates[0].content.parts
        for p in parts:
            data = getattr(getattr(p, "inline_data", None), "data", None)
            if data:
                return data if isinstance(data, (bytes, bytearray)) else bytes(data)
    except Exception as exc:
        raise RuntimeError(f"no audio in Gemini TTS response: {exc}") from exc
    raise RuntimeError("no inline_data in Gemini TTS response")


def _write_wav(path: Path, pcm: bytes, *, sample_rate: int = 24000,
               channels: int = 1, sampwidth: int = 2) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
