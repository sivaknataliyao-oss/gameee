"""Confirm the filter pipeline rejects near-duplicate stories."""
from datetime import datetime, timezone


def _make_story(text: str, sid: str):
    from src.core.models import Lang, Metrics, Source, Story
    return Story(
        id=sid,
        source=Source.REDDIT,
        source_id=sid.split(":")[-1],
        permalink="https://example",
        title="title",
        text=text,
        lang_detected=Lang.RU,
        created_at=datetime.now(timezone.utc),
        metrics=Metrics(upvotes=10),
    )


def test_accept_rejects_near_duplicates(monkeypatch):
    import src.filters.dedup as dd
    import src.filters.pipeline as fp

    original = (
        "Это была обычная осень. Он проснулся рано и пошёл на работу. "
        "На столе лежал конверт без обратного адреса. Открыв его, он увидел "
        "фотографию, которую не видел двадцать лет. Он долго смотрел на неё "
        "и не мог понять, как она сюда попала. Тогда зазвонил телефон."
    ) * 3

    near_dup = _make_story(original + " Мелкая правка в конце.", "reddit:second")
    existing_hash = dd.simhash(original)

    # Pretend the DB already has a story with near-identical simhash
    import src.filters.dedup as _dd
    monkeypatch.setattr("src.core.storage.has_near_duplicate",
                        lambda our_hash, threshold=4, since_days=60, batch=500:
                            "reddit:first" if _dd.hamming(our_hash, existing_hash) <= threshold else None)
    # Loosen the length gate so our fake story isn't rejected earlier
    from src.core import config
    monkeypatch.setitem(config.filters().get("length", {}), "min_chars", 0)

    ok, reason = fp.accept(near_dup)
    assert not ok
    assert reason.startswith("dedup:")


def test_accept_allows_unrelated_story(monkeypatch):
    import src.filters.pipeline as fp

    a = "Зимой мы ходили в походы и варили чай на костре. " * 20
    b = "Главный герой нашёл ключ от старой библиотеки на чердаке. " * 20

    monkeypatch.setattr("src.core.storage.has_near_duplicate",
                        lambda our_hash, threshold=4, since_days=60, batch=500: None)
    from src.core import config
    monkeypatch.setitem(config.filters().get("length", {}), "min_chars", 0)

    story = _make_story(b, "reddit:new")
    ok, reason = fp.accept(story)
    assert ok, f"should have passed, got {reason}"
