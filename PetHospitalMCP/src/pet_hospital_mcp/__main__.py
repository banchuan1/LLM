"""Entry point: `python -m pet_hospital_mcp` starts the MCP HTTP server.

Boots a uvicorn worker serving the Starlette app returned by
`server.create_app()`. Binds to `MCP_HOST:MCP_PORT` (defaults
`127.0.0.1:8765`).
"""
from __future__ import annotations

import logging

from .config import load_settings
from .logging_config import configure_logging
from .server import app, create_app, mcp


def main() -> None:
    settings = load_settings()
    configure_logging(level="INFO")
    log = logging.getLogger("pet_hospital_mcp.__main__")

    # Rebuild the app so this process owns a fresh session manager.
    global app
    app = create_app()

    log.info(
        "starting pet-hospital-mcp",
        extra={
            "tool_name": "_server",
            "params": {
                "mcp_host": settings.mcp_host,
                "mcp_port": settings.mcp_port,
                "pet_hospital_base_url": settings.pet_hospital_base_url,
                "backend_timeout_seconds": settings.backend_timeout_seconds,
                "backend_max_retries": settings.backend_max_retries,
            },
            "status": "starting",
            "duration_ms": 0,
        },
    )

    # Imported lazily so `python -c 'from pet_hospital_mcp import app'`
    # (used in tests) does not require uvicorn.
    import uvicorn

    uvicorn.run(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
