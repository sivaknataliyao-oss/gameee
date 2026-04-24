"""TTS provider protocol."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSProvider(ABC):
    name: str

    @abstractmethod
    def synthesize(self, text: str, out_path: Path) -> Path:
        """Render text to WAV at out_path. Returns out_path."""
