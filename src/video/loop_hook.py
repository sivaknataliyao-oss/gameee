"""Make a Short "loopable" — the end crossfades back into the opening frame.

Why: the YouTube Shorts / TikTok players auto-loop silent replays, and if the
last frame smoothly becomes the first, the viewer often watches twice. Each
loop counts as another watch-through, boosting retention metrics.

Implementation:
  1. Clip the first ~`overlap`s of the input as `head`.
  2. Extract the body (from `overlap` to end) — this is where the original
     content lives minus the very opening tail.
  3. xfade(body, head) with duration=overlap, offset=body_duration-overlap.
  4. Cross-fade the matching audio so there's no click.

The resulting clip is approximately the same length as the input (it loses
`overlap` seconds of actual content but gains a `overlap`-second "wrap-around"
that sells the loop).
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(r.stdout.strip() or 0)


def make_loopable(input_mp4: Path, out_mp4: Path, overlap: float = 0.5) -> Path:
    """Produce a loop-friendly version of a Short. Safe for any input >= 2*overlap."""
    total = _probe_duration(input_mp4)
    if total < max(2.5, overlap * 5):
        # Too short to split usefully — copy through unchanged.
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(input_mp4), "-c", "copy", str(out_mp4)],
            check=True, capture_output=True,
        )
        return out_mp4

    offset = max(0.0, total - 2 * overlap)

    # Extract head (first `overlap`s) and the rest (body) in one pass.
    tmp_head = out_mp4.with_name(out_mp4.stem + "_head.mp4")
    tmp_body = out_mp4.with_name(out_mp4.stem + "_body.mp4")

    subprocess.run(
        ["ffmpeg", "-y",
         "-i", str(input_mp4),
         "-t", f"{overlap:.3f}",
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-c:a", "aac", "-b:a", "192k",
         str(tmp_head)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y",
         "-i", str(input_mp4),
         "-ss", f"{overlap:.3f}",
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-c:a", "aac", "-b:a", "192k",
         str(tmp_body)],
        check=True, capture_output=True,
    )

    try:
        subprocess.run(
            ["ffmpeg", "-y",
             "-i", str(tmp_body),
             "-i", str(tmp_head),
             "-filter_complex",
             f"[0:v][1:v]xfade=transition=fade:duration={overlap}:offset={offset}[v];"
             f"[0:a][1:a]acrossfade=d={overlap}[a]",
             "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart",
             str(out_mp4)],
            check=True, capture_output=True,
        )
    finally:
        tmp_head.unlink(missing_ok=True)
        tmp_body.unlink(missing_ok=True)

    log.info("loop_hook: %s -> %s (overlap=%.2fs)", input_mp4.name, out_mp4.name, overlap)
    return out_mp4
