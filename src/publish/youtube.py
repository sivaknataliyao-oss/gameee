"""YouTube Data API v3 uploader with optional scheduled publishing."""
from __future__ import annotations

import logging
import pickle
from pathlib import Path

from src.core import config
from src.publish.package import Package

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _service():
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = Path(config.env("YOUTUBE_TOKEN", "./secrets/youtube_token.pickle"))
    client_secret = Path(config.env("YOUTUBE_CLIENT_SECRET", "./secrets/client_secret.json"))

    creds = None
    if token_path.exists():
        creds = pickle.loads(token_path.read_bytes())
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_bytes(pickle.dumps(creds))
    return build("youtube", "v3", credentials=creds)


def upload(pkg: Package) -> str:
    from googleapiclient.http import MediaFileUpload

    yt = _service()

    body = {
        "snippet": {
            "title": pkg.title[:100],
            "description": pkg.description[:4900],
            "tags": pkg.hashtags[:15],
            "categoryId": "24",  # Entertainment
            "defaultLanguage": "ru",
            "defaultAudioLanguage": "ru",
        },
        "status": {
            "privacyStatus": "private" if pkg.publish_at else pkg.privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    if pkg.publish_at:
        body["status"]["publishAt"] = pkg.publish_at

    media = MediaFileUpload(str(pkg.video_path), chunksize=-1, resumable=True,
                             mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    video_id = resp["id"]
    log.info("youtube uploaded: %s", video_id)
    return video_id
