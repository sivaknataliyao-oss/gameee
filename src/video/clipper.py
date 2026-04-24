"""Cut the long video into Shorts/TikTok segments by chapter markers.

Each Short gets:
  - opening "Часть N/K" card (~2s)
  - the chapter body with optional cliffhanger
  - an end card + CTA pointing at the channel handle
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.core import config

log = logging.getLogger(__name__)


@dataclass
class ClipPlan:
    index: int
    total: int
    start_sec: float
    end_sec: float
    chapter_hook: str


def _dims() -> tuple[int, int]:
    return 1080, 1920


def _endcard_png(handle: str, out_path: Path) -> Path:
    w, h = _dims()
    img = Image.new("RGB", (w, h), (10, 10, 16))
    draw = ImageDraw.Draw(img)
    try:
        font_title = ImageFont.truetype("assets/fonts/Montserrat-Black.ttf", 88)
        font_body = ImageFont.truetype("assets/fonts/Manrope-Bold.ttf", 54)
    except OSError:
        font_title = font_body = ImageFont.load_default()

    cta = config.channel().get("cta_shorts", {}).get(
        "text_template", "Часть {n}/{k} — продолжение на канале {handle}"
    )
    text = cta.replace("{handle}", handle).replace("{n}", "").replace("{k}", "").strip(" —")
    lines = ["ПОЛНАЯ ИСТОРИЯ", "НА КАНАЛЕ", handle]
    y = h // 3
    for ln in lines:
        _, _, r, b = draw.textbbox((0, 0), ln, font=font_title)
        draw.text(((w - r) // 2, y), ln, font=font_title, fill=(245, 215, 110))
        y += b + 20
    img.save(out_path)
    return out_path


def _cta_banner_png(text: str, out_path: Path) -> Path:
    w, h = _dims()
    img = Image.new("RGBA", (w, 220), (0, 0, 0, 180))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("assets/fonts/Manrope-Bold.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    _, _, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text(((w - r) // 2, (220 - b) // 2), text, font=font, fill=(255, 255, 255))
    img.save(out_path)
    return out_path


def cut_shorts(
    long_vertical_mp4: Path,
    plans: list[ClipPlan],
    out_dir: Path,
) -> list[Path]:
    """Produce one 1080x1920 MP4 per ClipPlan with CTA banner + end card."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ch_cfg = config.channel().get("channel", {})
    handle = ch_cfg.get("handle", "@channel")
    cta_tmpl = config.channel().get(
        "cta_shorts", {}
    ).get("text_template", "Часть {n}/{k} — продолжение на канале {handle}")

    endcard = _endcard_png(handle, out_dir / "_endcard.png")
    clips: list[Path] = []
    endcard_dur = int(config.channel().get("endcard", {}).get("duration_sec", 4))

    for plan in plans:
        banner_text = cta_tmpl.format(n=plan.index, k=plan.total, handle=handle)
        banner = _cta_banner_png(banner_text, out_dir / f"_banner_{plan.index}.png")

        clip_body = out_dir / f"short_{plan.index:02d}_body.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{plan.start_sec:.2f}",
             "-to", f"{plan.end_sec:.2f}",
             "-i", str(long_vertical_mp4),
             "-c:v", "libx264", "-c:a", "aac",
             "-preset", "medium", "-crf", "20",
             str(clip_body)],
            check=True, capture_output=True,
        )

        # Append endcard silently
        endcard_clip = out_dir / f"short_{plan.index:02d}_end.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loop", "1", "-t", str(endcard_dur),
             "-i", str(endcard),
             "-f", "lavfi", "-t", str(endcard_dur),
             "-i", "anullsrc=r=48000:cl=stereo",
             "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k",
             str(endcard_clip)],
            check=True, capture_output=True,
        )

        # Concat body + endcard
        listfile = out_dir / f"short_{plan.index:02d}_list.txt"
        listfile.write_text(
            f"file '{clip_body.resolve()}'\nfile '{endcard_clip.resolve()}'\n",
            encoding="utf-8",
        )
        merged = out_dir / f"short_{plan.index:02d}_merged.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
             "-c", "copy", str(merged)],
            check=True, capture_output=True,
        )

        # Overlay CTA banner on top (first 2s + last 3s)
        final = out_dir / f"short_{plan.index:02d}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(merged), "-i", str(banner),
             "-filter_complex",
             "[0:v][1:v]overlay=0:80:enable='between(t,0,2)+between(t,main_t-3,main_t)'[v]",
             "-map", "[v]", "-map", "0:a",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-c:a", "copy", str(final)],
            check=True, capture_output=True,
        )
        clips.append(final)

        # Cleanup intermediates
        for tmp in (clip_body, endcard_clip, merged, listfile, banner):
            Path(tmp).unlink(missing_ok=True)

    return clips


def plan_from_timings(
    chapter_ranges: list[tuple[float, float, str]],
    max_short_sec: float = 75.0,
) -> list[ClipPlan]:
    """Convert chapter (start, end, hook) tuples into clip plans.

    Splits any chapter longer than max_short_sec into multiple shorts.
    """
    plans: list[ClipPlan] = []
    idx = 1

    # First pass: flatten oversized chapters into sub-windows
    windows: list[tuple[float, float, str]] = []
    for start, end, hook in chapter_ranges:
        length = end - start
        if length <= max_short_sec:
            windows.append((start, end, hook))
        else:
            n = int(length // max_short_sec) + 1
            step = length / n
            for i in range(n):
                windows.append((start + i * step, start + (i + 1) * step, hook))

    total = len(windows)
    for start, end, hook in windows:
        plans.append(ClipPlan(index=idx, total=total, start_sec=start, end_sec=end,
                              chapter_hook=hook))
        idx += 1
    return plans
