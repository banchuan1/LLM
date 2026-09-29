"""MCP server assembly + Starlette app factory.

The MCPServer instance is created at module import so that `tools/`
modules can decorate their handlers with `@mcp.tool()` at import time.
The Starlette app is built lazily via `create_app()` so tests can
construct a fresh app per test (the SDK's session manager is not
designed to be reused across `streamable_http_app()` calls).

Key design points:
    - Uses `MCPServer` (SDK 2.x); no FastMCP import.
    - Stateless Streamable HTTP: `stateless_http=True`,
      `json_response=True`. No `initialize` handshake, no
      `Mcp-Session-Id`, no session store. Protocol version 2026-07-28
      is the SDK's default.
    - `/health` is a `custom_route` on the same Starlette app (no MCP
      semantics, no auth — teaching scope).
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse

# SDK 2.x: import MCPServer (NOT FastMCP).
from mcp.server import MCPServer

# The MCPServer instance. Tools decorate themselves with `@mcp.tool()`
# at import time of `tools/<name>.py`, which is triggered by importing
# the `tools` package below.
mcp = MCPServer(
    name="pet-hospital-mcp",
    instructions=(
        "MCP service exposing the Go Pet Hospital REST API. "
        "Stage 1 provides the `list_pets` tool, which adapts "
        "GET /api/v1/pets (filter / sort / paginate)."
    ),
)

# Importing the tools package triggers `@mcp.tool()` registration.
from . import tools  # noqa: F401, E402  (import-for-side-effects)
from .tools import reset_rest_client  # noqa: F401  (re-export for tests)


@mcp.custom_route("/health", methods=["GET"])
async def health(request) -> JSONResponse:  # noqa: ARG001 - request unused
    """Liveness probe. Returns 200 JSON outside the MCP protocol."""
    return JSONResponse({
        "status": "ok",
        "service": "pet-hospital-mcp",
        "protocol_version": "2026-07-28",
        "sdk": "mcp==2.0.0",
    })


def create_app() -> Starlette:
    """Build a fresh Starlette app with stateless Streamable HTTP + /health.

    Each call returns a new app instance (the SDK's session manager
    cannot be reused across runs).
    """
    return mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
    )


# Default app for `python -m pet_hospital_mcp` and for ad-hoc imports.
# Tests should call `create_app()` to get a fresh app per test.
app = create_app()
