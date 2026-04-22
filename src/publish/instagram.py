"""Instagram Reels via Meta Graph API (requires IG Business Account)."""
from __future__ import annotations

import logging
import time

import requests

from src.core import config
from src.publish.package import Package

log = logging.getLogger(__name__)


def upload(pkg: Package, public_url: str) -> str:
    """Publish a Reel. `public_url` must be a fetchable URL of the MP4.

    Meta Graph's IG publishing requires the video hosted on a reachable URL,
    not an uploaded binary — so this step assumes the caller uploaded the file
    to CDN/S3/drive and provides a public link.
    """
    token = config.env("META_ACCESS_TOKEN")
    ig_user = config.env("META_IG_USER_ID")
    if not token or not ig_user:
        raise RuntimeError("META_ACCESS_TOKEN + META_IG_USER_ID required")

    create = requests.post(
        f"https://graph.facebook.com/v21.0/{ig_user}/media",
        data={
            "media_type": "REELS",
            "video_url": public_url,
            "caption": pkg.description[:2000],
            "access_token": token,
        },
        timeout=60,
    )
    create.raise_for_status()
    container_id = create.json()["id"]

    # Poll status
    for _ in range(30):
        r = requests.get(
            f"https://graph.facebook.com/v21.0/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        )
        r.raise_for_status()
        if r.json().get("status_code") == "FINISHED":
            break
        time.sleep(5)

    pub = requests.post(
        f"https://graph.facebook.com/v21.0/{ig_user}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    pub.raise_for_status()
    media_id = pub.json()["id"]
    log.info("instagram reels published: %s", media_id)
    return media_id
