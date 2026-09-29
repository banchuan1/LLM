"""Structured JSON logging with recursive sensitive-field masking.

Each tool call emits one log line containing `timestamp`, `tool_name`,
`params` (masked), `status`, and `duration_ms`. Sensitive fields are
masked recursively in both `params` and `details`:

    ownerPhone / owner_phone
    ownerAddr  / owner_addr
    chipNo     / chip_no
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

# Mask these keys (case-sensitive — covers both camelCase and snake_case forms).
_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "ownerPhone", "owner_phone",
    "ownerAddr", "owner_addr",
    "chipNo", "chip_no",
})

_MASK = "***"


def _mask_recursive(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: (_MASK if k in _SENSITIVE_KEYS else _mask_recursive(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_mask_recursive(item) for item in node]
    if isinstance(node, tuple):
        return tuple(_mask_recursive(item) for item in node)
    return node


def mask_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a deep copy of `payload` with sensitive fields masked."""
    if payload is None:
        return {}
    return _mask_recursive(dict(payload))  # type: ignore[return-value]


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter — one JSON object per log record."""

    _EXTRA_KEYS = (
        "tool_name", "params", "status", "duration_ms",
        "error_code", "details",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in self._EXTRA_KEYS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with the JSON formatter.

    Idempotent: re-calling does not stack duplicate handlers.
    """
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if isinstance(handler, logging.StreamHandler) and isinstance(
            handler.formatter, JsonFormatter
        ):
            root.handlers.remove(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
    root.addHandler(handler)
    root.setLevel(level)
