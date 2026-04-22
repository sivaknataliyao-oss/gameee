"""TikTok export = ready-to-upload package (MP4 + metadata.json).

We do NOT attempt direct automatic posting to TikTok: the official
Content Posting / Direct Post APIs have aggressive gating for non-audited
apps and explicitly discourage republishing others' content. So the safer
flow is: generate the package, upload manually from the TikTok app.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from src.publish.package import Package

log = logging.getLogger(__name__)


def export(pkg: Package, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / pkg.video_path.name
    shutil.copy2(pkg.video_path, target)

    meta = {
        "platform": "tiktok",
        "title": pkg.title,
        "caption": pkg.description,
        "hashtags": pkg.hashtags,
        "privacy": pkg.privacy,
        "note": "Upload manually through the TikTok app or an audited partner tool.",
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    log.info("tiktok package: %s", out_dir)
    return out_dir
