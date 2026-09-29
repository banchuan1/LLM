"""Top-level package for the pet-hospital MCP service (stage 1)."""

__version__ = "0.1.0"

# Re-export the Starlette app and the MCPServer instance so callers can
# `from pet_hospital_mcp import app, mcp` without poking into `server`.
from .server import app, create_app, mcp  # noqa: F401
