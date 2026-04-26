"""AppConfig validation."""
import pytest

from src.core.configs import AppConfig, ConfigError


def test_load_default_brand_succeeds() -> None:
    cfg = AppConfig.load("default")
    assert cfg.filters.dedup.enabled is True
    assert cfg.filters.dedup.simhash_threshold >= 1
    assert cfg.filters.dedup.history_days >= 1
    assert isinstance(cfg.filters.length.min_chars, int)


def test_load_unknown_brand_falls_back_to_defaults() -> None:
    cfg = AppConfig.load("nonexistent_brand_xyz")
    assert cfg.filters.dedup.enabled is True


def test_invalid_overlay_raises_config_error(tmp_path, monkeypatch) -> None:
    """A wrong-typed value in a brand overlay should raise ConfigError with a path."""
    import src.core.config as legacy_config
    bad_brand = tmp_path / "brands" / "broken"
    bad_brand.mkdir(parents=True)
    (bad_brand / "filters.yaml").write_text(
        "dedup:\n  simhash_threshold: 'not-an-int'\n", encoding="utf-8"
    )
    monkeypatch.setattr(legacy_config, "BRANDS_DIR", tmp_path / "brands")
    legacy_config._base_yaml.cache_clear()
    for fn in (legacy_config.sources, legacy_config.filters, legacy_config.voices,
               legacy_config.images, legacy_config.channel, legacy_config.audio):
        fn.cache_clear()
    with pytest.raises(ConfigError) as ei:
        AppConfig.load("broken")
    msg = str(ei.value)
    assert "filters" in msg and "simhash_threshold" in msg


def test_config_error_message_lists_all_failures(tmp_path, monkeypatch) -> None:
    import src.core.config as legacy_config
    bad = tmp_path / "brands" / "many_errors"
    bad.mkdir(parents=True)
    (bad / "filters.yaml").write_text(
        "dedup:\n  simhash_threshold: 'bad'\n  history_days: 'also bad'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(legacy_config, "BRANDS_DIR", tmp_path / "brands")
    legacy_config._base_yaml.cache_clear()
    for fn in (legacy_config.sources, legacy_config.filters, legacy_config.voices,
               legacy_config.images, legacy_config.channel, legacy_config.audio):
        fn.cache_clear()
    with pytest.raises(ConfigError) as ei:
        AppConfig.load("many_errors")
    msg = str(ei.value)
    assert "simhash_threshold" in msg
    assert "history_days" in msg
