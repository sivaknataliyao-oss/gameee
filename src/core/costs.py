"""Lightweight cost tracker and monthly cap enforcement.

Each API call should (optionally) call `track(...)` after it completes; callers
use `check_budget(provider, est_cost)` to decide whether to skip expensive
providers when the monthly cap is already hit.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import runs_dir

_LOCK = threading.Lock()


def _path() -> Path:
    p = runs_dir().parent / "costs.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def track(provider: str, operation: str, units: float, unit_cost_usd: float,
          meta: dict[str, Any] | None = None) -> float:
    """Append a spend record and return total cost of this record."""
    cost = units * unit_cost_usd
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "operation": operation,
        "units": units,
        "unit_cost_usd": unit_cost_usd,
        "cost_usd": round(cost, 6),
        "meta": meta or {},
    }
    with _LOCK, _path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return cost


def monthly_spend(provider: str | None = None, month: str | None = None) -> float:
    """Sum spend for a provider (or all) in YYYY-MM."""
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    total = 0.0
    if not _path().exists():
        return total
    with _path().open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("ts", "").startswith(month):
                continue
            if provider and rec.get("provider") != provider:
                continue
            total += float(rec.get("cost_usd", 0) or 0)
    return total


def check_budget(provider: str, est_cost: float, monthly_cap: float) -> bool:
    """Return True if `est_cost` fits under the monthly cap for this provider."""
    if monthly_cap <= 0:
        return True
    return monthly_spend(provider) + est_cost <= monthly_cap


def summary() -> dict[str, float]:
    """Spend per provider this month."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    out: dict[str, float] = {}
    if not _path().exists():
        return out
    with _path().open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("ts", "").startswith(month):
                continue
            out[rec["provider"]] = out.get(rec["provider"], 0.0) + float(rec.get("cost_usd", 0))
    return out
