"""Typewriter caption renderer: PNG sequence with alpha channel.

Produces per-frame PNGs where text appears character by character in sync with
spoken audio timing. The PNG sequence is composited on top of the slideshow
via ffmpeg overlay.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.video.subtitles import WordTiming

log = logging.getLogger(__name__)


@dataclass
class TypewriterConfig:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    font_path: str = "assets/fonts/Manrope-Bold.ttf"
    font_size: int = 66
    line_chars: int = 24
    margin_y: int = 320         # pixels from bottom
    stroke_width: int = 4
    cursor: str = "|"
    cursor_blink_hz: float = 3.0


def render_png_sequence(
    words: list[WordTiming],
    out_dir: Path,
    cfg: TypewriterConfig | None = None,
) -> tuple[Path, float]:
    """Write a transparent PNG sequence. Returns (dir, total_duration_sec)."""
    cfg = cfg or TypewriterConfig()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not words:
        return out_dir, 0.0

    try:
        font = ImageFont.truetype(cfg.font_path, cfg.font_size)
    except OSError:
        log.warning("font %s missing; falling back to default", cfg.font_path)
        font = ImageFont.load_default()

    total = max(w.end for w in words)
    total_frames = int(total * cfg.fps) + 1

    # Flatten the whole reveal schedule: for each character, compute when it should appear.
    char_schedule: list[tuple[str, float]] = []   # (char, show_at_sec)
    for w in words:
        text = w.text + " "
        step = max((w.end - w.start) / max(1, len(text)), 0.01)
        for i, ch in enumerate(text):
            char_schedule.append((ch, w.start + i * step))

    for frame_idx in range(total_frames):
        t = frame_idx / cfg.fps

        # How many chars are visible by time t?
        visible = ""
        for ch, show_at in char_schedule:
            if t >= show_at:
                visible += ch
            else:
                break

        # Keep only the most recent ~2 lines to avoid drift.
        lines = _wrap(visible, cfg.line_chars)
        display = "\n".join(lines[-2:])

        # Blinking cursor
        blink_on = int(t * cfg.cursor_blink_hz) % 2 == 0
        if blink_on:
            display += cfg.cursor

        img = Image.new("RGBA", (cfg.width, cfg.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        _draw_centered(
            draw, display, font, cfg.width, cfg.height - cfg.margin_y,
            fill=(255, 255, 255, 255),
            stroke_fill=(0, 0, 0, 255),
            stroke_width=cfg.stroke_width,
        )
        img.save(out_dir / f"{frame_idx:06d}.png")

    return out_dir, total


def _wrap(text: str, line_chars: int) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip() if cur else w
        if len(candidate) <= line_chars:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, font, width: int, baseline_y: int,
                   fill, stroke_fill, stroke_width: int) -> None:
    lines = text.split("\n")
    _, _, _, line_h = draw.textbbox((0, 0), "Ag", font=font)
    y = baseline_y - line_h * len(lines)
    for line in lines:
        l, t, r, b = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        tw = r - l
        x = (width - tw) // 2
        draw.text(
            (x, y), line, font=font, fill=fill,
            stroke_width=stroke_width, stroke_fill=stroke_fill,
        )
        y += (b - t) + 12
