"""Append-only ledger of permission events — tamper-evident audit trail."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.core.config import runs_dir

LEDGER = runs_dir().parent / "rights_ledger.jsonl"


def append(event: dict) -> None:
    event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def iter_events():
    if not LEDGER.exists():
        return
    with LEDGER.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
