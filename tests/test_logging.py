"""Structured JSON logging."""
import io
import json
import logging

from src.core.logging import JsonFormatter, bind_log, setup


def _capture(level: str = "INFO") -> tuple[logging.Logger, io.StringIO]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(f"test.{id(buf)}")
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
    return logger, buf


def test_json_formatter_basic_record() -> None:
    logger, buf = _capture()
    logger.info("hello world")
    rec = json.loads(buf.getvalue().strip())
    assert rec["msg"] == "hello world"
    assert rec["level"] == "INFO"
    assert rec["name"].startswith("test.")
    assert "ts" in rec and rec["ts"].endswith("Z")


def test_json_formatter_includes_extras() -> None:
    logger, buf = _capture()
    logger.info("stage_ok", extra={"story_id": "reddit:abc", "duration_ms": 42})
    rec = json.loads(buf.getvalue().strip())
    assert rec["story_id"] == "reddit:abc"
    assert rec["duration_ms"] == 42


def test_bind_log_injects_fields() -> None:
    logger, buf = _capture()
    adapter = bind_log(logger, story_id="reddit:abc", stage="script_llm")
    adapter.info("stage_ok", duration_ms=100)
    rec = json.loads(buf.getvalue().strip())
    assert rec["story_id"] == "reddit:abc"
    assert rec["stage"] == "script_llm"
    assert rec["duration_ms"] == 100
    assert rec["msg"] == "stage_ok"


def test_bind_log_extra_kwargs_override_bound_fields() -> None:
    """bind_log fields can be overridden per-call by passing the same key in extras."""
    logger, buf = _capture()
    adapter = bind_log(logger, stage="A")
    adapter.info("x", stage="B")
    rec = json.loads(buf.getvalue().strip())
    assert rec["stage"] == "B"


def test_setup_replaces_root_handlers(capsys) -> None:
    setup(level="INFO")
    logging.getLogger().info("plain")
    out = capsys.readouterr().out.strip()
    rec = json.loads(out)
    assert rec["msg"] == "plain"


def test_exception_serialized() -> None:
    logger, buf = _capture()
    try:
        raise ValueError("boom")
    except ValueError:
        logger.error("caught", exc_info=True)
    rec = json.loads(buf.getvalue().strip())
    assert "ValueError: boom" in rec["exc_info"]
