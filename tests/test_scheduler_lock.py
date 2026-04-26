"""Scheduler enqueue must produce non-colliding slots even under concurrent calls."""
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.publish import scheduler


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setenv("GAMEEE_DB", str(db))
    # Reset the cached engine so it reopens against the new path.
    import src.core.storage as storage
    monkeypatch.setattr(storage, "_engine", None)
    yield


def test_enqueue_two_threads_no_collision(fresh_db, monkeypatch) -> None:
    """Two concurrent enqueue() calls on the same platform must produce distinct slots."""
    barrier = threading.Barrier(2)
    results: list = []
    errors: list[Exception] = []

    def worker(story_id: str) -> None:
        try:
            barrier.wait(timeout=2)
            row = scheduler.enqueue(
                story_id, "youtube_shorts",
                Path("/tmp/v.mp4"), "title", "desc", ["x"],
            )
            results.append(row.planned_for)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=("reddit:a",))
    t2 = threading.Thread(target=worker, args=("reddit:b",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors, errors
    assert len(results) == 2
    assert results[0] != results[1], (
        f"slot collision: both rows planned for {results[0]}"
    )


def test_enqueue_serial_calls_advance_by_cadence(fresh_db) -> None:
    a = scheduler.enqueue("reddit:a", "youtube_shorts",
                          Path("/tmp/a.mp4"), "t", "d", [])
    b = scheduler.enqueue("reddit:b", "youtube_shorts",
                          Path("/tmp/b.mp4"), "t", "d", [])
    delta = b.planned_for - a.planned_for
    cadence = scheduler.cadence_from_config()
    assert delta == timedelta(hours=cadence.youtube_shorts_hours)


def test_next_slot_does_not_double_step_when_base_is_past(fresh_db, monkeypatch) -> None:
    """Old code added +1 day if `base + delta < now`. New code: snap to today's
    preferred hour or tomorrow's if that's already past."""
    a = scheduler.enqueue("reddit:a", "youtube",
                          Path("/tmp/a.mp4"), "t", "d", [])
    cadence = scheduler.cadence_from_config()
    now = datetime.now(timezone.utc)
    expected_lower_bound = now + timedelta(days=cadence.long_youtube_days) - timedelta(hours=24)
    assert a.planned_for >= expected_lower_bound
    # And not absurdly far in the future.
    assert a.planned_for <= now + timedelta(days=cadence.long_youtube_days + 2)
