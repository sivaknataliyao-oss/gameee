"""Content-addressed TTS cache. Key = SHA256(provider+voice+text)."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from src.core import config


def key(provider: str, voice: str, text: str) -> str:
    h = hashlib.sha256()
    h.update(provider.encode())
    h.update(b"\x00")
    h.update(voice.encode())
    h.update(b"\x00")
    h.update(text.encode("utf-8"))
    return h.hexdigest()[:24]


def cache_dir() -> Path:
    d = Path(config.voices().get("cache", {}).get("dir", "./.data/tts_cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def lookup(k: str, suffix: str = ".wav") -> Path | None:
    p = cache_dir() / (k + suffix)
    return p if p.exists() else None


def store(k: str, src: Path, suffix: str = ".wav") -> Path:
    dst = cache_dir() / (k + suffix)
    shutil.copy2(src, dst)
    return dst
