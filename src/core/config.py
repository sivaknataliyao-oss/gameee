"""Load YAML configs + .env into typed objects."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = Path(os.getenv("GAMEEE_RUNS", ROOT / ".data"))


def _read_yaml(name: str) -> dict[str, Any]:
    p = CONFIG_DIR / name
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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


def env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def db_path() -> Path:
    raw = os.getenv("GAMEEE_DB", "./.data/gameee.db")
    return Path(raw).expanduser().resolve()


def runs_dir() -> Path:
    d = Path(os.getenv("GAMEEE_RUNS", "./runs")).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d
