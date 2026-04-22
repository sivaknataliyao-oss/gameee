"""Light audio chain: loudness normalization + HPF + light compressor (ffmpeg)."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def master(input_path: Path, output_path: Path, target_lufs: float = -16.0) -> Path:
    """Run a simple master chain via ffmpeg's built-in filters.

    -16 LUFS is the conventional target for social short-form vertical video.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    filters = (
        f"highpass=f=80,"
        f"acompressor=threshold=-18dB:ratio=2.5:attack=10:release=200:makeup=2,"
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", filters,
        "-ar", "48000",
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    log.info("audio master: %s -> %s", input_path, output_path)
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def concat(wav_paths: list[Path], output_path: Path, gap_sec: float = 0.35) -> Path:
    """Concat a list of WAVs with short silent gaps between (for breathing)."""
    import tempfile

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        listfile = Path(f.name)
        for p in wav_paths:
            f.write(f"file '{p.resolve()}'\n")

    concat_raw = output_path.with_suffix(".raw.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(concat_raw)],
        check=True, capture_output=True,
    )
    # pad silence between by re-encoding with apad? simpler: rely on natural pauses from TTS
    # for gap, we re-render with aevalsrc mixing — skipped for MVP.
    if gap_sec > 0:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(concat_raw),
             "-af", f"apad=pad_dur={gap_sec}",
             str(output_path)],
            check=True, capture_output=True,
        )
        concat_raw.unlink(missing_ok=True)
    else:
        concat_raw.rename(output_path)

    listfile.unlink(missing_ok=True)
    return output_path
