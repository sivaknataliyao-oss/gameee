"""Build a Ken-Burns slideshow from a list of images."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.core import config

log = logging.getLogger(__name__)


def _dims(ratio: str) -> tuple[int, int]:
    if ratio == "9:16":
        return 1080, 1920
    return 1920, 1080


def build(
    images: list[Path],
    duration_sec: float,
    out_path: Path,
    ratio: str = "16:9",
    fps: int = 30,
) -> Path:
    """Crossfade a slideshow with Ken-Burns zoom. One output clip of `duration_sec`."""
    w, h = _dims(ratio)
    cfg = config.images().get("slideshow", {}).get("ken_burns", {})
    zoom_start = float(cfg.get("zoom_start", 1.0))
    zoom_end = float(cfg.get("zoom_end", 1.2))

    if not images:
        raise ValueError("slideshow.build requires at least one image")

    n = len(images)
    per_slide = duration_sec / n
    frames_per_slide = int(per_slide * fps)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Render each slide as its own MP4, then concat with crossfade.
    tmp_dir = out_path.parent / (out_path.stem + "_slides")
    tmp_dir.mkdir(exist_ok=True)
    clips: list[Path] = []
    for i, img in enumerate(images):
        clip = tmp_dir / f"slide_{i:03d}.mp4"
        zoom_expr = (
            f"min(zoom+{(zoom_end - zoom_start) / max(frames_per_slide,1):.5f},{zoom_end})"
        )
        vf = (
            f"scale={w*2}:-2:flags=lanczos,"
            f"zoompan=z='{zoom_expr}':d={frames_per_slide}:s={w}x{h}:fps={fps},"
            f"format=yuv420p"
        )
        subprocess.run(
            [
                "ffmpeg", "-y", "-loop", "1", "-framerate", str(fps),
                "-t", f"{per_slide:.3f}", "-i", str(img),
                "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(clip),
            ],
            check=True, capture_output=True,
        )
        clips.append(clip)

    # Concat (no crossfade for MVP simplicity; TODO: xfade filter chain).
    listfile = tmp_dir / "list.txt"
    listfile.write_text("\n".join(f"file '{c.resolve()}'" for c in clips), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(out_path)],
        check=True, capture_output=True,
    )
    log.info("slideshow built: %s (%d slides, %.1fs)", out_path, n, duration_sec)
    return out_path
