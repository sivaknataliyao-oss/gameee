"""Image cache keyed by SHA256(provider+prompt+ratio). Re-use within N days."""
from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path

from src.core import config


def key(provider: str, prompt: str, ratio: str) -> str:
    h = hashlib.sha256()
    h.update(provider.encode())
    h.update(b"\x00")
    h.update(ratio.encode())
    h.update(b"\x00")
    h.update(prompt.encode("utf-8"))
    return h.hexdigest()[:24]


def cache_dir() -> Path:
    d = Path(config.images().get("cache", {}).get("dir", "./.data/img_cache"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def lookup(k: str) -> list[Path]:
    max_age = 86400 * int(config.images().get("cache", {}).get("reuse_within_days", 30))
    folder = cache_dir() / k
    if not folder.exists():
        return []
    now = time.time()
    out = []
    for f in sorted(folder.iterdir()):
        if f.is_file() and now - f.stat().st_mtime < max_age:
            out.append(f)
    return out


def store(k: str, files: list[Path]) -> list[Path]:
    folder = cache_dir() / k
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for i, f in enumerate(files):
        dst = folder / f"{i:02d}{f.suffix.lower() or '.jpg'}"
        shutil.copy2(f, dst)
        out.append(dst)
    return out
