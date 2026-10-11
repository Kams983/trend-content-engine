"""One-line ``key=value`` logging.

Every log line is a single line of ``event=... key=value ...`` pairs so the
output is greppable in CI. Timestamps are always UTC (ISO-8601, ``Z``).

Secrets must never be passed to these helpers. ``kv()`` renders whatever it is
given, so callers are responsible for not handing it tokens or passwords.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TextIO

_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _render(value: Any) -> str:
    """Render a value for a ``key=value`` pair without spaces or newlines."""
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return "[" + ",".join(_render(v) for v in value) + "]"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    text = str(value)
    # Keep the line intact: collapse whitespace, quote if it contains spaces.
    text = " ".join(text.split())
    if any(ch in text for ch in " =\":") or text == "":
        return json.dumps(text)
    return text


def kv(event: str, **fields: Any) -> str:
    """Build a ``key=value`` log message. ``event`` is the leading token."""
    parts = [f"event={event}"] if event else []
    parts.extend(f"{key}={_render(val)}" for key, val in fields.items())
    return " ".join(parts)


class KVFormatter(logging.Formatter):
    """``<utc-ts> level=<lvl> logger=<name> <event=k=v ...>``."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(_TIME_FMT)
        message = record.getMessage()
        line = f"{ts} level={record.levelname.lower()} logger={record.name} {message}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def setup_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Configure the root logger once, idempotently."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Replace any pre-existing handlers we own so repeated calls don't duplicate.
    for handler in list(root.handlers):
        if getattr(handler, "_tce_handler", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(KVFormatter())
    handler._tce_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    # Third-party libraries are noisy at INFO; keep them at WARNING.
    for noisy in ("urllib3", "requests", "sentence_transformers", "transformers", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
