"""Runtime configuration loaded from environment variables.

All values have safe localhost defaults so `python -m pet_hospital_mcp`
runs out of the box against a Go backend on 127.0.0.1:8080.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got: {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got: {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    """Snapshot of the service configuration. Immutable after load."""

    mcp_host: str
    mcp_port: int
    pet_hospital_base_url: str
    backend_timeout_seconds: float
    backend_max_retries: int


def load_settings() -> Settings:
    """Read configuration from environment variables.

    Environment variables:
        MCP_HOST (default "127.0.0.1")                  — bind address for the MCP HTTP server.
        MCP_PORT (default 8765)                         — bind port for the MCP HTTP server.
        PET_HOSPITAL_BASE_URL (default "http://127.0.0.1:8080") — Go REST API origin.
        BACKEND_TIMEOUT_SECONDS (default 10)            — per-request timeout for Go calls.
        BACKEND_MAX_RETRIES (default 2)                 — retry attempts for 5xx / network errors.
    """
    return Settings(
        mcp_host=_env_str("MCP_HOST", "127.0.0.1"),
        mcp_port=_env_int("MCP_PORT", 8765),
        pet_hospital_base_url=_env_str("PET_HOSPITAL_BASE_URL", "http://127.0.0.1:8080").rstrip("/"),
        backend_timeout_seconds=_env_float("BACKEND_TIMEOUT_SECONDS", 10.0),
        backend_max_retries=_env_int("BACKEND_MAX_RETRIES", 2),
    )
