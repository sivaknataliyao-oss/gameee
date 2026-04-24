"""Lightweight analytics collector: persist per-run KPIs to JSONL."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.core.config import runs_dir


def log_event(story_id: str, event: str, data: dict | None = None) -> None:
    path = runs_dir().parent / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "story_id": story_id,
        "event": event,
        "data": data or {},
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
