"""Index on StoryRow.simhash + has_near_duplicate batch lookup."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import text


@pytest.fixture
def fresh_db(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setenv("GAMEEE_DB", str(db))
    import src.core.storage as storage
    monkeypatch.setattr(storage, "_engine", None)
    yield


def _insert_story(sid: str, simhash: int | None,
                  fetched_at: datetime | None = None) -> None:
    from src.core.storage import StoryRow, session
    row = StoryRow(
        id=sid, source="reddit", source_id=sid.split(":")[-1],
        permalink="https://example", author=None,
        title="t", text="x" * 400, lang_detected="ru",
        nsfw=False, created_at=datetime.now(timezone.utc),
        fetched_at=fetched_at or datetime.now(timezone.utc),
        simhash=simhash, used=False,
    )
    with session() as s:
        s.add(row)


def test_simhash_index_is_created(fresh_db) -> None:
    from src.core.storage import engine
    eng = engine()
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")
        ).fetchall()
    names = [r[0] for r in rows]
    assert "ix_storyrow_simhash" in names


def test_has_near_duplicate_returns_existing_id(fresh_db) -> None:
    from src.core.storage import has_near_duplicate
    target = 0xDEAD_BEEF_DEAD_BEEF
    _insert_story("reddit:a", target)
    found = has_near_duplicate(target, threshold=4, since_days=60)
    assert found == "reddit:a"


def test_has_near_duplicate_returns_none_for_unrelated(fresh_db) -> None:
    from src.core.storage import has_near_duplicate
    _insert_story("reddit:a", 0x0000_0000_0000_0001)
    out = has_near_duplicate(0xFFFF_FFFF_FFFF_FFFE, threshold=4, since_days=60)
    assert out is None


def test_has_near_duplicate_short_circuits_on_first_match(fresh_db, monkeypatch) -> None:
    """Once a match is found, no further batches are loaded."""
    from src.core.storage import has_near_duplicate
    for i in range(50):
        _insert_story(f"reddit:{i}", i)            # tiny simhashes, won't match
    _insert_story("reddit:hit", 0xABCD_0000_ABCD_0000)
    found = has_near_duplicate(0xABCD_0000_ABCD_0000, threshold=0,
                               since_days=60, batch=10)
    assert found == "reddit:hit"


def test_has_near_duplicate_respects_since_days_window(fresh_db) -> None:
    from src.core.storage import has_near_duplicate
    long_ago = datetime.now(timezone.utc) - timedelta(days=120)
    _insert_story("reddit:old", 0xDEAD, fetched_at=long_ago)
    out = has_near_duplicate(0xDEAD, threshold=0, since_days=30)
    assert out is None


def test_has_near_duplicate_skips_null_simhash_rows(fresh_db) -> None:
    from src.core.storage import has_near_duplicate
    _insert_story("reddit:null", None)
    _insert_story("reddit:hit", 0xCAFE)
    out = has_near_duplicate(0xCAFE, threshold=0, since_days=60)
    assert out == "reddit:hit"
