"""Structured JSON logging with bound-field LoggerAdapter."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# Standard LogRecord attributes we don't want to leak into the JSON output as
# "extras". Anything not in this set goes into the record verbatim.
_STD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
                .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            out["exc_info"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k in _STD_ATTRS or k.startswith("_"):
                continue
            try:
                json.dumps(v)
                out[k] = v
            except TypeError:
                out[k] = repr(v)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup(level: str | int = "INFO") -> None:
    """Replace root logger handlers with a single JSON stdout handler."""
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h]
    root.setLevel(level)


class _BoundAdapter(logging.LoggerAdapter):
    """LoggerAdapter that merges bound fields with per-call kwargs."""

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        extra = dict(self.extra or {})
        # Per-call kwargs (other than reserved logging args) override bound fields.
        reserved = {"exc_info", "stack_info", "stacklevel", "extra"}
        for key in list(kwargs.keys()):
            if key in reserved:
                continue
            extra[key] = kwargs.pop(key)
        kwargs["extra"] = extra
        return msg, kwargs


def bind_log(logger: logging.Logger | None = None, **fields: Any) -> _BoundAdapter:
    """Return a LoggerAdapter that injects `fields` into every record."""
    return _BoundAdapter(logger or logging.getLogger(), fields)
