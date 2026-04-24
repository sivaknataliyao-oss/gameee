"""Generate an `index.html` inside a run directory so you can review everything
produced for a story (long video, shorts, thumbnail, packages) in one browser
tab before hitting publish.

Usage via CLI:
    python -m src.cli preview <story_id>
    python -m src.cli preview <story_id> --open       # xdg-open the HTML
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from src.core.config import runs_dir


_HTML = """<!doctype html>
<html lang=\"ru\">
<head>
<meta charset=\"utf-8\">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ font-family: system-ui, sans-serif; background: #0b0f14; color: #eee;
          margin: 0; padding: 24px; }}
  h1 {{ margin-top: 0; font-size: 22px; }}
  h2 {{ margin-top: 40px; font-size: 17px; color: #f5d76e; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
           gap: 16px; }}
  video {{ width: 100%; border-radius: 8px; background: #000; }}
  img.thumb {{ width: 100%; border-radius: 8px; }}
  .card {{ background: #141923; padding: 12px; border-radius: 10px; }}
  .card small {{ color: #8a99af; display: block; margin-top: 6px;
                 word-break: break-all; }}
  details pre {{ background: #0b0f14; padding: 12px; border-radius: 8px;
                 font-size: 12px; max-height: 400px; overflow: auto; }}
  a {{ color: #6ec2ff; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p><small>{base_path}</small></p>

{thumbnail_block}

<h2>Длинное видео (16:9)</h2>
<div class=\"grid\">{long_videos}</div>

<h2>Шортсы / TikTok (9:16)</h2>
<div class=\"grid\">{shorts_videos}</div>

<h2>Пакеты публикаций</h2>
{packages_block}

<h2>Сценарий и промпты</h2>
{script_block}
</body>
</html>
"""


def _card_video(path: Path, base: Path) -> str:
    rel = path.relative_to(base).as_posix()
    return (
        f"<div class='card'><video controls preload='metadata' "
        f"src='{html.escape(rel)}'></video>"
        f"<small>{html.escape(path.name)}</small></div>"
    )


def _card_thumb(path: Path, base: Path) -> str:
    rel = path.relative_to(base).as_posix()
    return (
        f"<div class='card'><img class='thumb' src='{html.escape(rel)}'>"
        f"<small>{html.escape(path.name)}</small></div>"
    )


def _pretty_json(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as exc:
        return f"<error reading {path.name}: {exc}>"


def build(run_dir: Path, open_in_browser: bool = False) -> Path:
    if not run_dir.exists():
        raise FileNotFoundError(f"run_dir not found: {run_dir}")

    base = run_dir.resolve()
    mp4s = sorted(base.rglob("*.mp4"))
    # Heuristic partitioning: long = mp4 outside /shorts/, shorts = inside it.
    long_videos = [p for p in mp4s if "shorts" not in p.parts]
    short_videos = [p for p in mp4s if "shorts" in p.parts]

    thumbnail = base / "thumbnail.jpg"
    thumbnail_block = (
        f"<h2>Обложка</h2><div class='grid'>{_card_thumb(thumbnail, base)}</div>"
        if thumbnail.exists() else ""
    )

    processed = base / "processed.json"
    script_block = ""
    if processed.exists():
        script_block = (
            f"<details open><summary>processed.json</summary>"
            f"<pre>{html.escape(_pretty_json(processed))}</pre></details>"
        )

    package_jsons = sorted((base / "packages").glob("*.json")) \
        if (base / "packages").exists() else []
    packages_block = ""
    for p in package_jsons:
        packages_block += (
            f"<details><summary>{html.escape(p.name)}</summary>"
            f"<pre>{html.escape(_pretty_json(p))}</pre></details>"
        )
    if not packages_block:
        packages_block = "<p><em>(пока нет packages/)</em></p>"

    out = base / "index.html"
    out.write_text(
        _HTML.format(
            title=f"preview · {base.name}",
            base_path=html.escape(str(base)),
            thumbnail_block=thumbnail_block,
            long_videos="".join(_card_video(v, base) for v in long_videos)
            or "<p><em>нет длинных видео</em></p>",
            shorts_videos="".join(_card_video(v, base) for v in short_videos)
            or "<p><em>нет шортсов</em></p>",
            packages_block=packages_block,
            script_block=script_block or "<p><em>нет processed.json</em></p>",
        ),
        encoding="utf-8",
    )

    if open_in_browser:
        import webbrowser
        webbrowser.open(f"file://{out.resolve()}")

    return out


def find_run_dir(story_id: str) -> Path | None:
    """Locate the most recent run directory for a story_id under runs/."""
    base = runs_dir()
    normalized = story_id.replace(":", "_")
    candidates = sorted(base.rglob(normalized), key=lambda p: p.stat().st_mtime, reverse=True)
    for c in candidates:
        if c.is_dir():
            return c
    return None
