"""Rights manager: permission-first gate before rendering.

Default policy: a story cannot proceed to rendering unless:
  - a PermissionRow exists with status in {GRANTED, NOT_REQUIRED}, OR
  - research mode is active (dry-run only, no publish).

Actually sending DMs to authors is platform-specific and is left as a TODO
hook — this module handles the bookkeeping and templating.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.core.models import RightsStatus, Story
from src.core.storage import PermissionRow, get_permission, upsert_permission
from src.rights import ledger, templates

log = logging.getLogger(__name__)


def ensure_asked(story: Story, lang: str = "ru") -> PermissionRow:
    existing = get_permission(story.id)
    if existing is not None and existing.status != RightsStatus.NONE.value:
        return existing

    body = templates.render(story.title, lang=lang)
    row = PermissionRow(
        story_id=story.id,
        author=story.author,
        status=RightsStatus.ASKED.value,
        asked_at=datetime.now(timezone.utc),
        text=body,
        evidence_url=story.permalink,
    )
    upsert_permission(row)
    ledger.append({
        "event": "asked",
        "story_id": story.id,
        "author": story.author,
        "source": story.source.value,
        "permalink": story.permalink,
        "lang": lang,
    })
    log.info("permission asked for %s (%s)", story.id, story.author)
    return row


def record_response(story_id: str, granted: bool, text: str, evidence_url: str | None = None) -> None:
    row = PermissionRow(
        story_id=story_id,
        status=(RightsStatus.GRANTED if granted else RightsStatus.DENIED).value,
        responded_at=datetime.now(timezone.utc),
        text=text,
        evidence_url=evidence_url,
    )
    upsert_permission(row)
    ledger.append({
        "event": "response",
        "story_id": story_id,
        "granted": granted,
        "text": text,
    })


def is_cleared(story_id: str, research_mode: bool = False) -> bool:
    if research_mode:
        return True
    p = get_permission(story_id)
    if not p:
        return False
    return p.status in {RightsStatus.GRANTED.value, RightsStatus.NOT_REQUIRED.value}
