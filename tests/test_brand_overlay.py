"""Brand overlay deep-merges onto base yaml."""
import importlib
import os
import tempfile
from pathlib import Path


def test_overlay_replaces_only_specified_keys(monkeypatch):
    # Import after we set env so config module picks up the brand from os.environ.
    os.environ.pop("GAMEEE_BRAND", None)
    import src.core.config as cfg
    importlib.reload(cfg)
    default_channel = cfg.channel()
    assert default_channel["channel"]["handle"] == "@channel"  # from base

    cfg.set_active_brand("horror")
    horror = cfg.channel()
    # overlay changed handle
    assert horror["channel"]["handle"] == "@darkstoriesru"
    # but inherited fonts from base
    assert "font_title" in horror["branding"]

    cfg.set_active_brand("default")
    back = cfg.channel()
    assert back["channel"]["handle"] == "@channel"


def test_brand_sources_replace_list(monkeypatch):
    os.environ.pop("GAMEEE_BRAND", None)
    import src.core.config as cfg
    importlib.reload(cfg)
    cfg.set_active_brand("horror")
    sources = cfg.sources()
    names = {s["name"] for s in sources["reddit"]["subreddits"]}
    assert "LetsNotMeet" in names
    assert "AskReddit" not in names
    cfg.set_active_brand("default")
