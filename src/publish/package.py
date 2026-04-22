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


def build_long_youtube(title: str, description: str, keywords: list[str],
                       video_path: Path, publish_at: str | None) -> Package:
    ch = config.channel().get("channel", {})
    desc = description + f"\n\nКанал: {ch.get('youtube_url','')}\n#" + " #".join(_hashtags(keywords))
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
