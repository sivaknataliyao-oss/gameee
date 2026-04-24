"""Image provider protocol."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ImageProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, prompt: str, n: int, ratio: str, out_dir: Path) -> list[Path]:
        """Produce `n` images for the prompt. Returns list of paths (may be < n)."""
