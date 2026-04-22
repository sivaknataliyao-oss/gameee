"""Retries + in-memory circuit breaker for fragile I/O."""
from __future__ import annotations

import functools
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


# -------- Retries --------

def retry(
    attempts: int = 3,
    initial: float = 1.0,
    factor: float = 2.0,
    max_wait: float = 30.0,
    on: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Simple exponential backoff. Intentionally tiny — avoids pulling tenacity
    into modules that only need one retry decorator."""

    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            wait = initial
            last: BaseException | None = None
            for i in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except on as exc:
                    last = exc
                    if i == attempts - 1:
                        break
                    log.warning("retry %s/%s for %s: %s", i + 1, attempts, fn.__name__, exc)
                    time.sleep(min(wait, max_wait))
                    wait *= factor
            assert last is not None
            raise last

        return wrapper

    return deco


# -------- Circuit breaker --------

@dataclass
class _BreakerState:
    failures: int = 0
    opened_at: datetime | None = None
    last_error: str = ""


class CircuitBreaker:
    """Trip after N consecutive failures; stay open for `cooldown` seconds."""

    _registry: dict[str, "_BreakerState"] = {}
    _lock = threading.Lock()

    def __init__(self, name: str, threshold: int = 3, cooldown_sec: int = 3600) -> None:
        self.name = name
        self.threshold = threshold
        self.cooldown = timedelta(seconds=cooldown_sec)

    def _state(self) -> _BreakerState:
        with self._lock:
            if self.name not in self._registry:
                self._registry[self.name] = _BreakerState()
            return self._registry[self.name]

    def is_open(self) -> bool:
        st = self._state()
        if st.opened_at is None:
            return False
        if datetime.now(timezone.utc) - st.opened_at > self.cooldown:
            # half-open: reset and let a probe call through
            st.opened_at = None
            st.failures = 0
            return False
        return True

    def record_success(self) -> None:
        st = self._state()
        st.failures = 0
        st.opened_at = None
        st.last_error = ""

    def record_failure(self, err: BaseException) -> None:
        st = self._state()
        st.failures += 1
        st.last_error = f"{type(err).__name__}: {err}"
        if st.failures >= self.threshold:
            st.opened_at = datetime.now(timezone.utc)
            log.warning("circuit %s OPEN for %s (%s)", self.name, self.cooldown, st.last_error)

    def __call__(self, fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if self.is_open():
                raise CircuitOpen(self.name)
            try:
                out = fn(*args, **kwargs)
            except BaseException as exc:
                self.record_failure(exc)
                raise
            self.record_success()
            return out

        return wrapper


class CircuitOpen(RuntimeError):
    """Raised when the breaker is tripped."""

    def __init__(self, name: str) -> None:
        super().__init__(f"circuit {name} is open")
        self.name = name
