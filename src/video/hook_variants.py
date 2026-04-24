"""Render A/B hook variants of the first Short.

One chapter → two versions of the same Short where only the opening 2 seconds
differ. Variant A uses hook text from title_variants[0], variant B uses
title_variants[1]. Both share the same main narration + visuals; only the
overlay banner changes.

Scheduler spreads A and B with a time gap so the engagement signal is
comparable. Analytics later attributes retention/CTR to the variant.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.core import config

log = logging.getLogger(__name__)


def _opener_png(text: str, out_path: Path) -> Path:
    w, h = 1080, 1920
    img = Image.new("RGBA", (w, h), (0, 0, 0, 220))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "assets/fonts/" + config.channel()
            .get("branding", {}).get("font_title", "Montserrat-Black.ttf"),
            96,
        )
    except OSError:
        font = ImageFont.load_default()

    # Wrap to ~18 chars per line
    words = text.split()
    lines: list[str] = []
    cur = ""
    for wd in words:
        cand = (cur + " " + wd).strip() if cur else wd
        if len(cand) > 18 and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = cand
    if cur:
        lines.append(cur)
    lines = lines[:4]

    total_h = 0
    dims: list[tuple[int, int]] = []
    for ln in lines:
        _, _, r, b = draw.textbbox((0, 0), ln, font=font, stroke_width=8)
        dims.append((r, b))
        total_h += b + 16

    y = (h - total_h) // 2
    for (r, b), ln in zip(dims, lines):
        x = (w - r) // 2
        draw.text((x, y), ln, font=font, fill=(255, 255, 255),
                  stroke_width=8, stroke_fill=(0, 0, 0))
        y += b + 16

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def render_variant(short_mp4: Path, hook_text: str, variant: str,
                   out_dir: Path) -> Path:
    """Produce a new Short with `hook_text` overlaid during first 2 seconds."""
    out = out_dir / f"{short_mp4.stem}_{variant}.mp4"
    overlay = _opener_png(hook_text, out_dir / f"{short_mp4.stem}_{variant}_opener.png")

    subprocess.run(
        ["ffmpeg", "-y",
         "-i", str(short_mp4),
         "-i", str(overlay),
         "-filter_complex",
         "[0:v][1:v]overlay=0:0:enable='between(t,0,2)'[v]",
         "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "copy",
         str(out)],
        check=True, capture_output=True,
    )
    overlay.unlink(missing_ok=True)
    log.info("variant %s: %s -> %s", variant, short_mp4.name, out.name)
    return out


def make_ab(short_mp4: Path, title_variants: list[str], out_dir: Path) -> list[tuple[str, Path]]:
    """Return [('A', path), ('B', path)]. Falls back to one variant if LLM
    only returned a single title."""
    if not title_variants:
        return [("A", short_mp4)]
    out_dir.mkdir(parents=True, exist_ok=True)
    a_text = title_variants[0]
    b_text = title_variants[1] if len(title_variants) > 1 else title_variants[0]
    if a_text == b_text:
        return [("A", render_variant(short_mp4, a_text, "A", out_dir))]
    return [
        ("A", render_variant(short_mp4, a_text, "A", out_dir)),
        ("B", render_variant(short_mp4, b_text, "B", out_dir)),
    ]
