"""Unified error envelope for the pet-hospital MCP service.

Every tool failure surfaced through the SDK carries a stable error code
(`code`), a human-readable `message`, and a `details` dict with
non-sensitive context (status code, attempt count, etc.). `to_payload`
produces the wire shape consumed by MCP clients:

    {"error": {"code": "...", "message": "...", "details": {...}}}

Tool handlers raise `PetHospitalToolError`; the SDK 2.x wraps it as a
`ToolError` and surfaces it as an `is_error=true` tool result whose
`content[0].text` reads `Error executing tool <name>: <payload-json>`.
The `Error executing tool <name>: ` prefix is framework metadata set by
the SDK (see `mcp/server/mcpserver/tools/base.py`); it does not leak any
httpx / Pydantic / Python stack trace.
"""
from __future__ import annotations

import json
from typing import Any

# Stable error codes for MCP clients to branch on.
VALIDATION_ERROR = "VALIDATION_ERROR"
BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
BACKEND_API_ERROR = "BACKEND_API_ERROR"
BACKEND_INVALID_RESPONSE = "BACKEND_INVALID_RESPONSE"
INTERNAL_ERROR = "INTERNAL_ERROR"


class PetHospitalToolError(Exception):
    """Carries a unified error envelope through the SDK's `is_error` channel.

    The string representation is the JSON envelope so the SDK's
    `f"Error executing tool {name}: {e}"` formatting embeds our payload
    verbatim.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }

    def __str__(self) -> str:  # noqa: D401 - machine-readable wire form
        return json.dumps(self.to_payload(), ensure_ascii=False)
