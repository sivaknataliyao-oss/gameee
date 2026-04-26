"""Validated application configuration.

`AppConfig.load(brand)` reads the same YAML files as the dict-based
`src.core.config` accessors and runs them through pydantic models so
typos and wrong types are caught at CLI startup with a clear path-to-key
error instead of a downstream KeyError or AttributeError.

Models use `extra='allow'` to avoid breaking on YAML keys we don't yet
model — only the fields we actively depend on are constrained.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core import config as _legacy


class ConfigError(ValueError):
    """Raised when a config file fails validation."""


class _Lax(BaseModel):
    model_config = ConfigDict(extra="allow")


class DedupCfg(_Lax):
    enabled: bool = True
    shingle_size: int = 6
    simhash_threshold: int = 4
    history_days: int = 60


class LengthCfg(_Lax):
    min_chars: int = 0
    max_chars: int = 1_000_000


class FiltersConfig(_Lax):
    dedup: DedupCfg = Field(default_factory=DedupCfg)
    length: LengthCfg = Field(default_factory=LengthCfg)


class SourcesConfig(_Lax):
    pass


class VoicesRouterCfg(_Lax):
    primary: str | None = None
    fallback_chain: list[str] = Field(default_factory=list)


class VoicesConfig(_Lax):
    router: VoicesRouterCfg = Field(default_factory=VoicesRouterCfg)


class ImagesConfig(_Lax):
    pass


class ChannelConfig(_Lax):
    pass


class AudioConfig(_Lax):
    pass


_SECTION_LOADERS = {
    "sources": ("sources.yaml", SourcesConfig),
    "filters": ("filters.yaml", FiltersConfig),
    "voices": ("voices.yaml", VoicesConfig),
    "images": ("images.yaml", ImagesConfig),
    "channel": ("channel.yaml", ChannelConfig),
    "audio": ("audio.yaml", AudioConfig),
}


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: SourcesConfig
    filters: FiltersConfig
    voices: VoicesConfig
    images: ImagesConfig
    channel: ChannelConfig
    audio: AudioConfig

    @classmethod
    def load(cls, brand: str = "default") -> "AppConfig":
        prev = _legacy.active_brand()
        try:
            _legacy.set_active_brand(brand)
            raw: dict[str, dict[str, Any]] = {
                key: _legacy._read_yaml(filename)
                for key, (filename, _model) in _SECTION_LOADERS.items()
            }
        finally:
            _legacy.set_active_brand(prev)

        errors: list[str] = []
        validated: dict[str, BaseModel] = {}
        for key, (_, model) in _SECTION_LOADERS.items():
            try:
                validated[key] = model.model_validate(raw[key])
            except ValidationError as e:
                for err in e.errors():
                    path = ".".join(str(p) for p in (key, *err["loc"]))
                    errors.append(f"  - {path}: {err['msg']} (got: {err.get('input')!r})")
        if errors:
            raise ConfigError(
                "Config validation failed:\n" + "\n".join(errors)
            )
        return cls(**validated)
