"""YouTube thumbnail generator (1280x720).

Picks the most dramatic image from the rendered set, zooms/crops to 16:9,
applies a dark vignette, and overlays the selected title with a bold
high-contrast style that survives YouTube compression.
"""
from __future__ import annotations

import logging
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.core import config

log = logging.getLogger(__name__)

TARGET = (1280, 720)


def _best_source(images: list[Path]) -> Path:
    """Prefer AI-generated images (openai/flux/localflux/imagefx) over Pexels
    stock, because AI images are usually more emotionally loaded and less
    generic. Fall back to Pexels if nothing else."""
    ai_prefix = ("openai_", "flux_", "localflux_", "imagefx_", "chatgpt_")
    ai = [p for p in images if p.name.startswith(ai_prefix)]
    pool = ai or images
    return random.choice(pool)


def _load_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _fit_cover(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    """Scale + center-crop `img` so it fills `target` exactly."""
    tw, th = target
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int,
          draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip() if cur else w
        l, _, r, _ = draw.textbbox((0, 0), candidate, font=font)
        if r - l > max_width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines[:3]  # cap at 3 lines


def _vignette(size: tuple[int, int]) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse([(-w // 2, -h // 2), (w * 3 // 2, h * 3 // 2)], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=180))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 170))
    overlay.putalpha(Image.eval(mask, lambda v: 170 - (v * 2 // 3)))
    return overlay


def _accent_bar(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                color: tuple[int, int, int]) -> None:
    draw.rectangle([(x, y), (x + w, y + h)], fill=color)


def render(images: list[Path], title: str, out_path: Path,
           *, accent: bool = True) -> Path:
    """Create a 1280x720 thumbnail with title overlay."""
    if not images:
        raise ValueError("thumbnail.render needs at least one image")

    branding = config.channel().get("branding", {})
    primary = _hex(branding.get("primary_color", "#F5D76E"))
    font_title_path = "assets/fonts/" + branding.get("font_title", "Montserrat-Black.ttf")

    src = _best_source(images)
    base = Image.open(src).convert("RGB")
    base = _fit_cover(base, TARGET)

    # darken + vignette
    base_rgba = base.convert("RGBA")
    base_rgba.alpha_composite(_vignette(TARGET))
    canvas = base_rgba.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    # title
    font_size = 110
    while font_size >= 58:
        font = _load_font(font_title_path, font_size)
        lines = _wrap(title.upper(), font, TARGET[0] - 160, draw)
        total_h = sum(
            (draw.textbbox((0, 0), ln, font=font)[3] - draw.textbbox((0, 0), ln, font=font)[1]) + 12
            for ln in lines
        )
        if total_h < TARGET[1] - 200:
            break
        font_size -= 8

    # accent color bar (left)
    if accent:
        _accent_bar(draw, 0, TARGET[1] // 2 - 180, 14, 360, primary)

    y = TARGET[1] - total_h - 70
    for ln in lines:
        l, t, r, b = draw.textbbox((0, 0), ln, font=font, stroke_width=8)
        x = 80
        # text with heavy outline for YouTube compression survival
        draw.text(
            (x, y), ln, font=font,
            fill=(255, 255, 255),
            stroke_width=8, stroke_fill=(0, 0, 0),
        )
        y += (b - t) + 12

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=92, optimize=True)
    log.info("thumbnail: %s", out_path)
    return out_path


def _hex(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
