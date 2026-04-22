"""Channel intro stinger (~3s) prepended to the long-form YT video.

Priority:
  1. `assets/channel/intro.mp4` if it exists (pre-made, preferred).
  2. Otherwise generate from `assets/channel/avatar.png` (or solid color) +
     channel handle + display name.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.core import config

log = logging.getLogger(__name__)


def build_intro(out_path: Path, ratio: str = "16:9") -> Path | None:
    """Return a path to an MP4 intro, or None if disabled / unbuildable."""
    cfg = config.channel().get("intro", {}) or {}
    if cfg.get("enabled", True) is False:
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)

    supplied = Path(cfg.get("path", "assets/channel/intro.mp4"))
    duration = float(cfg.get("duration_sec", 3.0))

    if supplied.exists():
        # Re-encode to match pipeline codec to avoid concat seam issues.
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(supplied),
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-t", f"{duration:.2f}",
             str(out_path)],
            check=True, capture_output=True,
        )
        return out_path

    if not cfg.get("generated_fallback", True):
        return None

    poster = _render_poster(ratio, duration)
    if poster is None:
        return None

    # Solid-color video with poster overlay + silent track.
    subprocess.run(
        ["ffmpeg", "-y",
         "-loop", "1", "-framerate", "30",
         "-t", f"{duration:.2f}",
         "-i", str(poster),
         "-f", "lavfi", "-t", f"{duration:.2f}",
         "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", "fade=t=in:st=0:d=0.5,fade=t=out:st={fo}:d=0.5".format(
             fo=max(0.0, duration - 0.5),
         ),
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k",
         str(out_path)],
        check=True, capture_output=True,
    )
    log.info("generated intro: %s", out_path)
    return out_path


def _render_poster(ratio: str, duration: float) -> Path | None:
    ch = config.channel().get("channel", {})
    branding = config.channel().get("branding", {})

    w, h = (1920, 1080) if ratio == "16:9" else (1080, 1920)
    bg_hex = branding.get("accent_color", "#0B0F14")
    fg_hex = branding.get("primary_color", "#F5D76E")
    bg = _hex(bg_hex)
    fg = _hex(fg_hex)

    canvas = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(canvas)

    avatar_path = Path("assets/channel/avatar.png")
    if avatar_path.exists():
        try:
            av = Image.open(avatar_path).convert("RGBA")
            size = min(w, h) // 3
            av = av.resize((size, size), Image.LANCZOS)
            # Round mask
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            av_round = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            av_round.paste(av, (0, 0), mask=mask)
            canvas.paste(av_round, ((w - size) // 2, (h - size) // 2 - 80),
                         mask=av_round)
        except Exception as exc:
            log.warning("intro avatar failed: %s", exc)

    # Title + handle
    try:
        font_title = ImageFont.truetype(
            "assets/fonts/" + branding.get("font_title", "Montserrat-Black.ttf"),
            int(h * 0.07),
        )
        font_body = ImageFont.truetype(
            "assets/fonts/" + branding.get("font_body", "Manrope-Bold.ttf"),
            int(h * 0.04),
        )
    except OSError:
        font_title = ImageFont.load_default()
        font_body = font_title

    handle = ch.get("handle", "@channel")
    display_name = ch.get("display_name", handle)

    # Display name
    _, _, r, b = draw.textbbox((0, 0), display_name, font=font_title,
                                stroke_width=2)
    draw.text(
        ((w - r) // 2, h // 2 + int(h * 0.08)),
        display_name, font=font_title,
        fill=fg, stroke_width=2, stroke_fill=(0, 0, 0),
    )
    # Handle under title
    _, _, r2, _ = draw.textbbox((0, 0), handle, font=font_body)
    draw.text(
        ((w - r2) // 2, h // 2 + int(h * 0.08) + b + 20),
        handle, font=font_body, fill=(230, 230, 230),
    )

    # Subtle radial glow
    glow = canvas.copy().filter(ImageFilter.GaussianBlur(radius=40))
    canvas = Image.blend(canvas, glow, 0.15)

    out = Path(".data/intro_poster.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out


def prepend(long_mp4: Path, intro_mp4: Path, out_mp4: Path) -> Path:
    """Concat intro + main long video with a one-frame crossfade."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    listfile = out_mp4.with_suffix(".txt")
    listfile.write_text(
        f"file '{intro_mp4.resolve()}'\nfile '{long_mp4.resolve()}'\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "aac", "-b:a", "192k",
         str(out_mp4)],
        check=True, capture_output=True,
    )
    listfile.unlink(missing_ok=True)
    return out_mp4


def _hex(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
