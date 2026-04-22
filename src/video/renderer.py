"""Compose final long-form 16:9 video: slideshow + typewriter overlay + audio + watermark."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.core import config

log = logging.getLogger(__name__)


def compose_long(
    slideshow_mp4: Path,
    audio_path: Path,
    typewriter_dir: Path | None,
    out_path: Path,
    ratio: str = "16:9",
    fps: int = 30,
) -> Path:
    """Burn subtitles/typewriter onto slideshow, mix audio, add watermark."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ch = config.channel().get("channel", {})
    wm = config.channel().get("watermark", {}) or {}
    handle = ch.get("handle", "@channel")

    inputs: list[str] = ["-i", str(slideshow_mp4), "-i", str(audio_path)]
    filters: list[str] = []

    video_label = "[0:v]"
    # typewriter overlay
    if typewriter_dir and any(typewriter_dir.iterdir()):
        inputs += ["-framerate", str(fps), "-i",
                   f"{typewriter_dir}/%06d.png"]
        filters.append(f"[0:v][2:v]overlay=format=auto:shortest=0[vtw]")
        video_label = "[vtw]"

    # watermark image
    wm_path = Path(wm.get("path", "assets/channel/watermark.png"))
    if wm.get("enabled", True) and wm_path.exists():
        inputs += ["-i", str(wm_path)]
        wm_input = f"[{len(inputs)//2 - 1}:v]"
        scale_frac = float(wm.get("scale", 0.12))
        margin = int(wm.get("margin", 32))
        pos = wm.get("position", "top_right")
        x_expr = "main_w-overlay_w-%d" % margin if "right" in pos else "%d" % margin
        y_expr = "main_h-overlay_h-%d" % margin if "bottom" in pos else "%d" % margin
        filters.append(f"{wm_input}scale=iw*{scale_frac}:-1[wm]")
        filters.append(f"{video_label}[wm]overlay={x_expr}:{y_expr}:format=auto[vout]")
        video_label = "[vout]"

    # If there's a handle always draw a small text in bottom corner
    filters.append(
        f"{video_label}drawtext=text='{handle}':fontcolor=white@0.8:fontsize=28:"
        f"x=w-tw-24:y=h-th-24:box=1:boxcolor=black@0.3:boxborderw=8[vfinal]"
    )
    video_label = "[vfinal]"

    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", ";".join(filters),
           "-map", video_label,
           "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart",
           "-shortest",
           str(out_path)]
    log.info("render long: %s", out_path)
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def reframe_to_vertical(input_mp4: Path, out_mp4: Path) -> Path:
    """Crop-pad a 16:9 mp4 to 9:16 (1080x1920) with a centered blurred background."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        "split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=20:1[bg2];"
        "[fg]scale=1080:-2[fg2];"
        "[bg2][fg2]overlay=(W-w)/2:(H-h)/2"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_mp4), "-vf", vf,
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "copy", str(out_mp4)],
        check=True, capture_output=True,
    )
    return out_mp4
