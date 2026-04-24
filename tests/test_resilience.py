import time

import pytest

from src.core.resilience import CircuitBreaker, CircuitOpen, retry


def test_retry_succeeds_after_transient_failure():
    attempts = {"n": 0}

    @retry(attempts=3, initial=0.01, factor=1.0)
    def flaky() -> int:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("boom")
        return 42

    assert flaky() == 42
    assert attempts["n"] == 2


def test_retry_gives_up_after_limit():
    @retry(attempts=2, initial=0.01)
    def always_bad():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        always_bad()


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(name="test_breaker_1", threshold=2, cooldown_sec=60)

    @cb
    def boom():
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        boom()
    with pytest.raises(RuntimeError):
        boom()
    # third call must be short-circuited
    with pytest.raises(CircuitOpen):
        boom()


def test_circuit_breaker_resets_after_cooldown():
    cb = CircuitBreaker(name="test_breaker_2", threshold=1, cooldown_sec=0)

    @cb
    def bad():
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        bad()
    # cooldown=0 -> half-open immediately; next call is retried (and fails again)
    with pytest.raises(RuntimeError):
        bad()
