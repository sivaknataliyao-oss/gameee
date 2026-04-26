"""Monetization classifier: fail-open when no key, blocks when verdict strong."""
from datetime import datetime, timezone


def _make_story(text: str):
    from src.core.models import Lang, Metrics, Source, Story
    return Story(
        id="reddit:x",
        source=Source.REDDIT,
        source_id="x",
        permalink="https://example",
        title="t",
        text=text,
        lang_detected=Lang.RU,
        created_at=datetime.now(timezone.utc),
        metrics=Metrics(upvotes=10),
    )


def test_classify_fails_open_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import importlib
    import src.core.config as cfg
    importlib.reload(cfg)
    from src.filters.monetization import classify

    v = classify("Обычная история о походе в магазин.", title="Test")
    assert v.friendly is True
    assert v.risk_category == "error"


def test_filter_blocks_when_verdict_not_friendly(monkeypatch):
    import src.filters.pipeline as fp
    from src.filters.monetization import Verdict

    # No dup history
    monkeypatch.setattr("src.core.storage.has_near_duplicate",
                        lambda our_hash, threshold=4, since_days=60, batch=500: None)
    # Fake the classifier to return an "unsafe" verdict
    monkeypatch.setattr(fp.monetization, "classify", lambda text, title="": Verdict(
        friendly=False, risk_category="violence", confidence=0.95,
        explanation="graphic",
    ))

    from src.core import config
    monkeypatch.setitem(config.filters().get("length", {}), "min_chars", 0)

    story = _make_story("Обычный текст " * 50)
    ok, reason = fp.accept(story)
    assert not ok
    assert reason == "monetization:violence"


def test_filter_allows_low_confidence(monkeypatch):
    import src.filters.pipeline as fp
    from src.filters.monetization import Verdict

    monkeypatch.setattr("src.core.storage.has_near_duplicate",
                        lambda our_hash, threshold=4, since_days=60, batch=500: None)
    monkeypatch.setattr(fp.monetization, "classify", lambda text, title="": Verdict(
        friendly=False, risk_category="tragedy", confidence=0.3,
        explanation="maybe",
    ))

    from src.core import config
    monkeypatch.setitem(config.filters().get("length", {}), "min_chars", 0)

    story = _make_story("Длинная история " * 50)
    ok, _reason = fp.accept(story)
    assert ok
