from datetime import datetime, timedelta, timezone

from src.core.models import Lang, Metrics, Source, Story
from src.core.scoring import growth_score, long_form_potential


def _mk(source: Source, text: str, m: Metrics, age_min: int) -> Story:
    return Story(
        id=f"{source.value}:x",
        source=source,
        source_id="x",
        permalink="https://example",
        title="t",
        text=text,
        lang_detected=Lang.RU,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=age_min),
        metrics=m,
    )


def test_growth_score_reddit_prefers_velocity():
    fresh = _mk(Source.REDDIT, "x", Metrics(upvotes=200, comments=40, upvote_ratio=0.95), age_min=30)
    old = _mk(Source.REDDIT, "x", Metrics(upvotes=200, comments=40, upvote_ratio=0.95), age_min=600)
    assert growth_score(Source.REDDIT, fresh.metrics, fresh.created_at) > growth_score(
        Source.REDDIT, old.metrics, old.created_at
    )


def test_long_form_potential_grows_with_structure():
    small = _mk(Source.REDDIT, "кот пропал", Metrics(), 60)
    big = _mk(
        Source.REDDIT,
        (
            "Однажды я купил дом. Но тогда я не знал что там уже жили. Утром я услышал шаги. "
            "— Кто здесь? — спросил я. Оказалось, что в подвале жил целый клан. "
            "Через неделю соседи подтвердили. В итоге всё закончилось хорошо. "
            "Но это была лишь первая из историй. "
        )
        * 6,
        Metrics(upvotes=900, comments=120),
        180,
    )
    assert long_form_potential(big) > long_form_potential(small)
    assert 0.0 <= long_form_potential(small) <= 1.0
    assert 0.0 <= long_form_potential(big) <= 1.0
