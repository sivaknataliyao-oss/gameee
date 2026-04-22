"""Pull per-video stats from YouTube Analytics API for videos we've uploaded.

Uses the same OAuth credentials as src/publish/youtube.py plus the
`yt-analytics.readonly` + `youtube.readonly` scopes.

Run:
    python -m src.cli pull-analytics            # all known uploaded videos
    python -m src.cli pull-analytics --days 28  # stats over last 28 days
"""
from __future__ import annotations

import logging
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from src.analytics.metrics_store import VideoMetricsRow, upsert
from src.core import config
from src.core.resilience import retry
from src.core.storage import engine
from src.publish.scheduler import ScheduledPostRow

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def _service():
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = Path(config.env("YOUTUBE_ANALYTICS_TOKEN",
                                  "./secrets/youtube_analytics_token.pickle"))
    client_secret = Path(config.env("YOUTUBE_CLIENT_SECRET",
                                     "./secrets/client_secret.json"))

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
    return (
        build("youtubeAnalytics", "v2", credentials=creds),
        build("youtube", "v3", credentials=creds),
    )


@retry(attempts=3, initial=2.0, factor=2.0)
def _query_analytics(analytics, video_ids: list[str], since: str, until: str):
    return analytics.reports().query(
        ids="channel==MINE",
        startDate=since,
        endDate=until,
        dimensions="video",
        metrics="views,estimatedMinutesWatched,averageViewPercentage,"
                "subscribersGained,likes,dislikes,comments",
        filters=f"video=={','.join(video_ids)}",
        maxResults=200,
    ).execute()


def uploaded_video_ids() -> list[tuple[str, str]]:
    """Return [(story_id, video_id), ...] for everything we've uploaded to YouTube."""
    with Session(engine()) as s:
        q = select(ScheduledPostRow).where(
            ScheduledPostRow.platform.in_(("youtube", "youtube_shorts")),
            ScheduledPostRow.status == "uploaded",
        )
        # video_id is stored in `error` field after upload? No — we haven't
        # threaded it through yet. For now, scan UploadRow from storage too.
        from src.core.storage import UploadRow
        qu = select(UploadRow).where(UploadRow.platform.in_(("youtube", "youtube_shorts")))
        rows = list(s.exec(qu))
    return [(r.story_id, r.video_id) for r in rows if r.video_id]


def pull(days: int = 28) -> int:
    """Pull analytics for all uploaded videos. Returns number of rows written."""
    pairs = uploaded_video_ids()
    if not pairs:
        log.info("no uploaded YouTube videos yet")
        return 0

    analytics, _yt = _service()
    until = datetime.now(timezone.utc).date().isoformat()
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()

    # YT Analytics API caps filter length; chunk by 50.
    video_ids = [v for _s, v in pairs]
    id_to_story = {v: s for s, v in pairs}
    written = 0
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i : i + 50]
        resp = _query_analytics(analytics, chunk, since, until)
        for row in resp.get("rows", []) or []:
            vid, views, watch_min, avp, subs, likes, dis, coms = (row + [0] * 8)[:8]
            upsert(VideoMetricsRow(
                story_id=id_to_story.get(vid, ""),
                platform="youtube",
                video_id=vid,
                views=int(views or 0),
                watch_minutes=float(watch_min or 0),
                average_view_percentage=float(avp or 0),
                subscribers_gained=int(subs or 0),
                likes=int(likes or 0),
                dislikes=int(dis or 0),
                comments=int(coms or 0),
            ))
            written += 1
    log.info("analytics: wrote %d metric rows", written)
    return written
