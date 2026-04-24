"""Pick background music and SFX and mix into narration with side-chain ducking."""
from __future__ import annotations

import fnmatch
import logging
import random
import subprocess
from pathlib import Path

from src.core import config

log = logging.getLogger(__name__)


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(r.stdout.strip() or 0)


def pick_music(duration_sec: float) -> Path | None:
    cfg = config.audio().get("music", {})
    if not cfg.get("enabled", True):
        return None
    music_dir = Path(cfg.get("dir", "assets/music"))
    if not music_dir.exists():
        return None
    candidates = [p for p in music_dir.iterdir()
                  if p.suffix.lower() in {".mp3", ".wav", ".ogg", ".m4a", ".flac"}]
    if not candidates:
        return None
    # Prefer tracks long enough to avoid visible loop seams.
    long_enough = [p for p in candidates if _probe_duration(p) >= duration_sec * 0.8]
    pool = long_enough or candidates
    return random.choice(pool)


def pick_sfx(pattern: str) -> Path | None:
    cfg = config.audio().get("sfx", {})
    if not cfg.get("enabled", True):
        return None
    sfx_dir = Path(cfg.get("dir", "assets/sfx"))
    if not sfx_dir.exists():
        return None
    names = [p for p in sfx_dir.iterdir() if p.is_file()]
    matches = [p for p in names if fnmatch.fnmatch(p.name.lower(), pattern.lower())]
    if not matches:
        return None
    return random.choice(matches)


def mix_with_music(voice_wav: Path, out_wav: Path,
                   music_path: Path | None = None) -> Path:
    """Mix voice with background music, ducked via sidechain compression.

    If `music_path` is None, auto-picks one from config audio.music.dir.
    If no music available, just copies voice to out_wav (no-op).
    """
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    voice_dur = _probe_duration(voice_wav)

    if music_path is None:
        music_path = pick_music(voice_dur)
    if music_path is None:
        # Nothing to mix — passthrough.
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(voice_wav), "-c", "copy", str(out_wav)],
            check=True, capture_output=True,
        )
        return out_wav

    cfg = config.audio().get("music", {})
    music_base = float(cfg.get("music_base_db", -22))
    ratio = float(cfg.get("duck_ratio", 8))
    thresh = float(cfg.get("duck_threshold_db", -30))
    attack = int(cfg.get("duck_attack_ms", 5))
    release = int(cfg.get("duck_release_ms", 350))
    fade_in = float(cfg.get("fade_in_sec", 2.0))
    fade_out = float(cfg.get("fade_out_sec", 3.0))

    # Loop music to voice duration, apply base gain + fades, then sidechain
    # compress against the voice signal.
    filter_complex = (
        f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{voice_dur:.3f},"
        f"volume={music_base}dB,"
        f"afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={max(voice_dur - fade_out, 0):.3f}:d={fade_out}[bg];"
        f"[bg][0:a]sidechaincompress=threshold={_db_to_lin(thresh):.5f}:"
        f"ratio={ratio}:attack={attack}:release={release}:makeup=0[ducked];"
        f"[0:a][ducked]amix=inputs=2:dropout_transition=0:duration=first[mix]"
    )
    subprocess.run(
        ["ffmpeg", "-y",
         "-i", str(voice_wav),
         "-i", str(music_path),
         "-filter_complex", filter_complex,
         "-map", "[mix]",
         "-c:a", "pcm_s16le",
         "-ar", "48000",
         str(out_wav)],
        check=True, capture_output=True,
    )
    log.info("mixed music: %s + %s -> %s", voice_wav.name, music_path.name, out_wav.name)
    return out_wav


def overlay_sfx(voice_wav: Path, sfx_at: list[tuple[float, str]], out_wav: Path) -> Path:
    """Overlay SFX clips at given absolute timestamps.

    `sfx_at` = [(t_sec, sfx_pattern), ...]  e.g. [(57.2, "whoosh*"), (123.0, "boom*")]
    If no matches found, the voice passes through unchanged.
    """
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    picked: list[tuple[float, Path]] = []
    for t, pattern in sfx_at:
        p = pick_sfx(pattern)
        if p is not None:
            picked.append((t, p))

    if not picked:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(voice_wav), "-c", "copy", str(out_wav)],
            check=True, capture_output=True,
        )
        return out_wav

    cfg = config.audio().get("sfx", {})
    vol_db = float(cfg.get("volume_db", -12))
    offset_before_ms = int(cfg.get("offset_before_ms", 300))

    inputs: list[str] = ["-i", str(voice_wav)]
    parts: list[str] = []
    delayed_labels: list[str] = []
    for i, (t, p) in enumerate(picked):
        inputs += ["-i", str(p)]
        start_ms = max(0, int(t * 1000) - offset_before_ms)
        label = f"s{i}"
        parts.append(
            f"[{i + 1}:a]volume={vol_db}dB,adelay={start_ms}|{start_ms}[{label}]"
        )
        delayed_labels.append(f"[{label}]")

    merge = f"[0:a]{''.join(delayed_labels)}amix=inputs={len(picked) + 1}:" \
            f"dropout_transition=0:duration=first[mix]"

    filter_complex = ";".join(parts + [merge])
    subprocess.run(
        ["ffmpeg", "-y", *inputs,
         "-filter_complex", filter_complex,
         "-map", "[mix]",
         "-c:a", "pcm_s16le",
         "-ar", "48000",
         str(out_wav)],
        check=True, capture_output=True,
    )
    log.info("overlayed %d sfx -> %s", len(picked), out_wav.name)
    return out_wav


def _db_to_lin(db: float) -> float:
    return 10 ** (db / 20.0)
