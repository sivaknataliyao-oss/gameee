import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_costs(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setenv("GAMEEE_RUNS", str(tmp / "runs"))
    # Force reload of config & costs module to pick up env.
    import importlib

    import src.core.config as cfg_mod
    importlib.reload(cfg_mod)
    import src.core.costs as costs_mod
    importlib.reload(costs_mod)
    return costs_mod


def test_track_and_summary(isolated_costs):
    costs = isolated_costs
    costs.track("flux_replicate", "image", 3, 0.003)
    costs.track("flux_replicate", "image", 2, 0.003)
    costs.track("openai_images", "image", 1, 0.04)

    summary = costs.summary()
    assert abs(summary["flux_replicate"] - 0.015) < 1e-6
    assert abs(summary["openai_images"] - 0.04) < 1e-6


def test_check_budget(isolated_costs):
    costs = isolated_costs
    costs.track("openai_images", "image", 1, 0.04)
    # cap 0.10 remaining
    assert costs.check_budget("openai_images", 0.02, 0.10) is True
    assert costs.check_budget("openai_images", 0.20, 0.10) is False
    # cap 0 means disabled -> always true
    assert costs.check_budget("openai_images", 100.0, 0.0) is True
