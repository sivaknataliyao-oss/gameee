"""Engagement-prior multiplier lies in a safe range and uses keywords."""
import importlib
import tempfile
from pathlib import Path


def test_prior_multiplier_neutral_when_empty(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setenv("GAMEEE_RUNS", str(tmp))
    import src.core.config as cfg
    importlib.reload(cfg)
    import src.analytics.feedback as fb
    importlib.reload(fb)

    assert fb.prior_multiplier("любая тема здесь") == 1.0


def test_prior_multiplier_clamped(monkeypatch, tmp_path):
    monkeypatch.setenv("GAMEEE_RUNS", str(tmp_path))
    import src.core.config as cfg
    importlib.reload(cfg)
    import src.analytics.feedback as fb
    importlib.reload(fb)

    # Fake a priors file with one huge weight and one tiny weight
    path = fb._prior_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"priors": {"дневник": 5.0, "скучно": -5.0}, "updated_at": "now"}',
        encoding="utf-8",
    )
    assert 0.75 <= fb.prior_multiplier("нашёл старый дневник") <= 1.5
    assert 0.75 <= fb.prior_multiplier("какая скучно история") <= 1.5
    # neutral text (no keyword match) -> exactly 1.0
    assert fb.prior_multiplier("ничего не совпадает") == 1.0
