"""Bundle per-story export package for each platform."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from src.core import config


@dataclass
class Package:
    platform: str
    video_path: Path
    title: str
    description: str
    hashtags: list[str]
    publish_at: str | None = None
    privacy: str = "public"


def _hashtags(keywords: list[str]) -> list[str]:
    base = ["storytime", "истории", "reddit"]
    for k in keywords[:5]:
        base.append("".join(ch for ch in k.lower() if ch.isalnum()))
    return [h for h in dict.fromkeys(base) if h]


def _fmt_ts(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def youtube_chapters_block(
    chapter_ranges: list[tuple[float, float, str]],
    intro_offset_sec: float = 0.0,
) -> str:
    """Format chapter timestamps for a YouTube description.

    YouTube requires:
      - first chapter at exactly 00:00
      - monotonically increasing timestamps
      - at least 3 chapters total
      - each chapter >= 10 seconds

    If the video has an intro stinger (`intro_offset_sec >= 1`), we anchor
    00:00 with the label "Вступление". Otherwise the first chapter's hook
    becomes the 00:00 label so we don't lose it behind a synthetic entry.
    Returns '' if the result wouldn't meet YT's 3-chapter minimum.
    """
    if not chapter_ranges or len(chapter_ranges) < 2:
        return ""

    lines: list[str] = ["Главы:"]
    prev_t = 0.0

    if intro_offset_sec >= 1.0:
        lines.append("00:00 Вступление")
        to_emit: list[tuple[float, float, str]] = list(chapter_ranges)
        start_idx = 1
    else:
        first_hook = (chapter_ranges[0][2] or "Часть 1").strip()
        if len(first_hook) > 80:
            first_hook = first_hook[:77] + "..."
        lines.append(f"00:00 {first_hook}")
        to_emit = list(chapter_ranges[1:])
        start_idx = 2

    for idx, (start, _end, hook) in enumerate(to_emit, start=start_idx):
        t = max(0.0, start + intro_offset_sec)
        if t - prev_t < 10:            # YT requires >= 10s between chapters
            continue
        label = (hook or f"Часть {idx}").strip()
        if len(label) > 80:
            label = label[:77] + "..."
        lines.append(f"{_fmt_ts(t)} {label}")
        prev_t = t

    # Need at least header + 3 chapter lines for YT to render them.
    if len(lines) < 4:
        return ""
    return "\n".join(lines)


def build_long_youtube(
    title: str,
    description: str,
    keywords: list[str],
    video_path: Path,
    publish_at: str | None,
    chapter_ranges: list[tuple[float, float, str]] | None = None,
    intro_offset_sec: float = 0.0,
) -> Package:
    ch = config.channel().get("channel", {})
    parts: list[str] = [description, ""]
    chapters = youtube_chapters_block(chapter_ranges or [], intro_offset_sec)
    if chapters:
        parts.extend([chapters, ""])
    parts.append(f"Канал: {ch.get('youtube_url','')}")
    parts.append("#" + " #".join(_hashtags(keywords)))
    desc = "\n".join(parts)
    return Package(
        platform="youtube",
        video_path=video_path,
        title=title,
        description=desc,
        hashtags=_hashtags(keywords),
        publish_at=publish_at,
    )


def build_short(platform: str, index: int, total: int, title_base: str,
                keywords: list[str], video_path: Path) -> Package:
    ch = config.channel().get("channel", {})
    handle = ch.get("handle", "@channel")
    title = f"Часть {index}/{total}: {title_base[:45]}"
    desc = (
        f"Часть {index} из {total}. Полная история — на канале {handle}.\n"
        f"#" + " #".join(_hashtags(keywords) + ["shorts", "storytime"])
    )
    return Package(
        platform=platform,
        video_path=video_path,
        title=title,
        description=desc,
        hashtags=_hashtags(keywords) + ["shorts", "storytime"],
    )


def dump(pkg: Package, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{pkg.platform}_{pkg.video_path.stem}.json"
    data = asdict(pkg)
    data["video_path"] = str(pkg.video_path)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
