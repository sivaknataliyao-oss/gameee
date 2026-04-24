"""Load YAML configs + .env into typed objects, with optional brand overlays.

Set the active brand via:
  - env var GAMEEE_BRAND
  - CLI flag --brand=<name>  (sets it before config is imported)

For each YAML (channel, sources, voices, images, filters, audio), if
config/brands/<name>/<yaml>.yaml exists it is merged over the defaults.
"""
from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
BRANDS_DIR = CONFIG_DIR / "brands"
DATA_DIR = Path(os.getenv("GAMEEE_RUNS", ROOT / ".data"))


def active_brand() -> str:
    return os.getenv("GAMEEE_BRAND", "default")


def set_active_brand(name: str) -> None:
    """Programmatically select the brand; clears caches."""
    os.environ["GAMEEE_BRAND"] = name
    for fn in (_base_yaml, sources, filters, voices, images, channel, audio):
        fn.cache_clear()


def _base_yaml(name: str) -> dict[str, Any]:
    p = CONFIG_DIR / name
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _brand_overlay(name: str) -> dict[str, Any]:
    brand = active_brand()
    if brand == "default":
        return {}
    p = BRANDS_DIR / brand / name
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep merge `overlay` into `base`. Lists are replaced, not concatenated."""
    out = copy.deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# NOTE: caches are keyed by active brand through env; `set_active_brand` clears them.
_base_yaml = lru_cache(maxsize=None)(_base_yaml)


def _read_yaml(name: str) -> dict[str, Any]:
    return _merge(_base_yaml(name), _brand_overlay(name))


@lru_cache
def sources() -> dict[str, Any]:
    return _read_yaml("sources.yaml")


@lru_cache
def filters() -> dict[str, Any]:
    return _read_yaml("filters.yaml")


@lru_cache
def voices() -> dict[str, Any]:
    return _read_yaml("voices.yaml")


@lru_cache
def images() -> dict[str, Any]:
    return _read_yaml("images.yaml")


@lru_cache
def channel() -> dict[str, Any]:
    return _read_yaml("channel.yaml")


@lru_cache
def audio() -> dict[str, Any]:
    return _read_yaml("audio.yaml")


def env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def db_path() -> Path:
    raw = os.getenv("GAMEEE_DB", "./.data/gameee.db")
    return Path(raw).expanduser().resolve()


def runs_dir() -> Path:
    d = Path(os.getenv("GAMEEE_RUNS", "./runs")).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    brand = active_brand()
    if brand != "default":
        d = d / brand
        d.mkdir(parents=True, exist_ok=True)
    return d
