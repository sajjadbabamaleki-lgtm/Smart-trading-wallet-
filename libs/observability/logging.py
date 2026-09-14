"""Structured logging.

Build 0.1 Rev.1 §60 requires machine-readable events rather than free text:
`event=order_rejected asset=BTC reason=RISK_SIZE_EXCEEDED correlation_id=...`
is queryable, "Something went wrong with BTC" is not.

Implemented on the standard library so that production dependencies stay small
(Build 0.1 Rev.1 §7). Every record passes through `libs.security.redaction`, so
a secret cannot reach a log by being handed to a logging call.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from libs.security.redaction import redact_mapping

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "message",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """Render each record as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extras = {key: value for key, value in record.__dict__.items() if key not in _RESERVED}
        if extras:
            payload.update(redact_mapping(extras))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO", *, stream: Any = None) -> None:
    """Install the JSON formatter on the root logger.

    Replaces existing handlers so a library that configured logging on import
    cannot leave a plain-text handler attached alongside this one, quietly
    emitting unredacted duplicates.
    """
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    """Logger for a module. Pass structured fields via `extra=`."""
    return logging.getLogger(name)
