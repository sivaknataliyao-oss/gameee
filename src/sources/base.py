"""Source adapter protocol. Each source returns a list of Story."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.models import Story


class SourceAdapter(ABC):
    name: str

    @abstractmethod
    async def fetch(self, limit: int = 100) -> list[Story]:
        """Pull fresh candidates. Must be idempotent and respectful of rate limits."""
