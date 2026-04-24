"""Default template: Ken-Burns slideshow + typewriter subtitles.

This file wires slideshow.build, typewriter.render_png_sequence, renderer.compose_long
into one callable used by the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.video import renderer, slideshow, subtitles, typewriter


@dataclass
class TemplateOutput:
    long_16x9: Path
    long_9x16: Path
    subtitles_ass: Path | None
    typewriter_dir: Path


def build(
    audio_path: Path,
    images: list[Path],
    run_dir: Path,
    duration_sec: float,
) -> TemplateOutput:
    run_dir.mkdir(parents=True, exist_ok=True)

    # 1) align words on synthesized audio
    words = subtitles.align(audio_path)

    # 2) render typewriter PNG sequence (vertical sized; we overlay on both orientations)
    tw_dir = run_dir / "typewriter"
    typewriter.render_png_sequence(words, tw_dir)

    # 3) ass fallback (useful for editors / auditing)
    ass = run_dir / "subs.ass"
    if words:
        subtitles.to_ass(words, ass)

    # 4) 16:9 slideshow
    slide_16 = run_dir / "slideshow_16x9.mp4"
    slideshow.build(images, duration_sec, slide_16, ratio="16:9")

    # 5) compose long 16:9
    long_16 = run_dir / "long_16x9.mp4"
    renderer.compose_long(slide_16, audio_path, tw_dir, long_16, ratio="16:9")

    # 6) reframe to vertical for shorts/tiktok
    long_9 = run_dir / "long_9x16.mp4"
    renderer.reframe_to_vertical(long_16, long_9)

    return TemplateOutput(long_16x9=long_16, long_9x16=long_9,
                          subtitles_ass=ass if words else None,
                          typewriter_dir=tw_dir)
