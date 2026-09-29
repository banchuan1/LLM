"""Tool registration and shared per-process REST client factory.

Tools are registered at import time via `@mcp.tool()` decorators inside
each `tools/<name>.py` module. Importing this package imports every
tool module, so a single `from .tools import register_all` (or just
`from . import tools`) is enough for the server to expose them.

The REST client is a per-process singleton so tests can override it
without touching the live Go backend — call `set_rest_client(client)`
in test setup and `set_rest_client(None)` in teardown.
"""
from __future__ import annotations

from typing import Callable

from ..config import Settings, load_settings
from ..rest_client import PetHospitalRestClient

__all__ = [
    "get_rest_client",
    "set_rest_client",
    "reset_rest_client",
    "register_all",
]


# Module-level singleton state. Lazily initialised so importing this
# module does not require environment variables to be set (useful for
# tests that override the client before any tool call).
_settings: Settings | None = None
_rest_client: PetHospitalRestClient | None = None
_rest_client_factory: Callable[[], PetHospitalRestClient] | None = None


def _ensure_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def get_rest_client() -> PetHospitalRestClient:
    """Return the per-process REST client (creating one on first use)."""
    global _rest_client
    if _rest_client is None:
        if _rest_client_factory is not None:
            _rest_client = _rest_client_factory()
        else:
            _rest_client = PetHospitalRestClient(_ensure_settings())
    return _rest_client


def set_rest_client(client: PetHospitalRestClient | None) -> None:
    """Override the per-process REST client (test-only). Pass None to reset."""
    global _rest_client
    _rest_client = client


def reset_rest_client() -> None:
    """Forget any cached client so the next `get_rest_client()` rebuilds one."""
    global _rest_client
    _rest_client = None


def register_all() -> None:
    """No-op kept for symmetry with future multi-tool stages.

    Today tools self-register via `@mcp.tool()` decorators at import
    time, so simply importing this package suffices. Future stages may
    add explicit registration here.
    """
    # Importing the tool module triggers `@mcp.tool()` registration.
    from . import list_pets  # noqa: F401


# Eager self-registration so that `from .server import app` (which
# imports this package) automatically registers every tool.
register_all()
