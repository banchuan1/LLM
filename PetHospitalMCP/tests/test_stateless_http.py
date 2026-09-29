"""Tests for stateless Streamable HTTP behavior over the wire.

Verifies the SDK 2.x 2026-07-28 protocol is observed end-to-end:
    - `/health` custom route returns 200 outside MCP.
    - `/mcp` accepts raw JSON-RPC `server/discover`, `tools/list`,
      `tools/call` with `MCP-Protocol-Version: 2026-07-28`, the
      `Mcp-Method`/`Mcp-Name` headers, and a `_meta` envelope carrying
      protocol version + client info + client capabilities.
    - No `Mcp-Session-Id` is sent or expected (stateless).
    - No `initialize` handshake is required.
    - `list_pets` is discoverable and callable through the HTTP endpoint.
"""
from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from pet_hospital_mcp.server import create_app
from pet_hospital_mcp.tools import set_rest_client
from pet_hospital_mcp.rest_client import PetHospitalRestClient

from .conftest import TEST_SETTINGS, default_backend_handler


PROTOCOL_VERSION = "2026-07-28"

# `base_url` MUST include a port — the SDK's DNS-rebinding protection
# whitelists `127.0.0.1:*` (port wildcard) by default, and Starlette's
# TestClient sends a Host header without a port unless told otherwise.
# `http://127.0.0.1:8080` produces Host=127.0.0.1 (no port), which the
# wildcard does not match. Using any port (e.g. :8080) yields Host=
# 127.0.0.1:8080, which matches `127.0.0.1:*`.
TEST_BASE_URL = "http://127.0.0.1:8080"


def _meta() -> dict[str, object]:
    """The 2026-07-28 envelope required inside `params._meta`."""
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "test-client", "version": "1.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def _headers(method: str, name: str | None = None) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        h["Mcp-Name"] = name
    return h


@pytest.fixture
def http_client(sample_envelope) -> TestClient:
    """TestClient wired to a fresh Starlette app with a mock backend.

    Uses the autouse `override_rest_client` fixture to install the mock
    backend, then builds a fresh app (SDK session manager is not reused
    across `streamable_http_app()` calls).
    """
    # Ensure the singleton points at the mock transport (the autouse
    # fixture already does this, but we re-state it here for clarity
    # because the HTTP path goes through the same singleton).
    transport = default_backend_handler(sample_envelope)
    set_rest_client(PetHospitalRestClient(TEST_SETTINGS, transport=transport))

    app = create_app()
    # `base_url` includes a port so the SDK's host-header wildcard
    # (`127.0.0.1:*`) accepts the request.
    with TestClient(app, base_url=TEST_BASE_URL) as client:
        yield client


# ---------------------------------------------------------------------------
# /health — custom route, outside MCP
# ---------------------------------------------------------------------------


def test_health_returns_200(http_client):
    """`/health` is a custom route returning JSON outside MCP semantics."""
    r = http_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "pet-hospital-mcp"
    assert body["protocol_version"] == "2026-07-28"
    assert body["sdk"] == "mcp==2.0.0"


# ---------------------------------------------------------------------------
# server/discover — protocol version advertising
# ---------------------------------------------------------------------------


def test_server_discover_advertises_2026_07_28(http_client):
    """`server/discover` must list `2026-07-28` in `supportedVersions`."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": _meta()}}
    r = http_client.post("/mcp", json=body, headers=_headers("server/discover"))
    assert r.status_code == 200
    result = r.json()["result"]
    assert "2026-07-28" in result["supportedVersions"]


def test_no_mcp_session_id_header_returned(http_client):
    """Stateless mode: server must NOT return `mcp-session-id`."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": _meta()}}
    r = http_client.post("/mcp", json=body, headers=_headers("server/discover"))
    assert r.status_code == 200
    assert r.headers.get("mcp-session-id") is None


def test_no_initialize_required(http_client):
    """Stateless mode: a request without `initialize` must still be served."""
    # We directly call `tools/list` without any prior `initialize`.
    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": _meta()}}
    r = http_client.post("/mcp", json=body, headers=_headers("tools/list"))
    assert r.status_code == 200
    result = r.json()["result"]
    assert any(t["name"] == "list_pets" for t in result["tools"])


# ---------------------------------------------------------------------------
# tools/list — discover `list_pets` over HTTP
# ---------------------------------------------------------------------------


def test_tools_list_returns_list_pets_with_input_and_output_schema(http_client):
    body = {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {"_meta": _meta()}}
    r = http_client.post("/mcp", json=body, headers=_headers("tools/list"))
    assert r.status_code == 200
    tools = r.json()["result"]["tools"]
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "list_pets"
    assert "inputSchema" in tool
    assert "outputSchema" in tool
    # inputSchema references the ListPetsParams model.
    assert "params" in tool["inputSchema"]["properties"]


# ---------------------------------------------------------------------------
# tools/call — invoke `list_pets` over HTTP
# ---------------------------------------------------------------------------


def test_tools_call_list_pets_returns_structured_content(http_client, sample_envelope):
    """`tools/call list_pets` should return `structuredContent` with the envelope `data`."""
    body = {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {
            "name": "list_pets",
            "arguments": {"params": {"species": "犬", "page": 1, "pageSize": 5}},
            "_meta": _meta(),
        },
    }
    r = http_client.post("/mcp", json=body, headers=_headers("tools/call", name="list_pets"))
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["isError"] is False
    sc = result["structuredContent"]
    assert sc["total"] == sample_envelope["data"]["total"]
    assert sc["page"] == 1
    # pageSize reflects the mock envelope's value (20), not the request's
    assert sc["pageSize"] == sample_envelope["data"]["pageSize"]
    assert len(sc["items"]) == 1


def test_tools_call_list_pets_validation_error_returns_is_error(http_client):
    """Bad input should surface as `isError=true` (SDK wraps Pydantic errors)."""
    body = {
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {
            "name": "list_pets",
            "arguments": {"params": {"species": "外星人"}},  # bad enum
            "_meta": _meta(),
        },
    }
    r = http_client.post("/mcp", json=body, headers=_headers("tools/call", name="list_pets"))
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["isError"] is True
    assert "Error executing tool list_pets" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# Protocol version enforcement
# ---------------------------------------------------------------------------


def test_modern_protocol_version_headers_accepted(http_client):
    """The 2026-07-28 envelope (with `clientCapabilities`) is required."""
    # Missing `clientCapabilities` should yield a JSON-RPC error.
    bad_meta = {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "t", "version": "1"},
        # clientCapabilities intentionally omitted
    }
    body = {"jsonrpc": "2.0", "id": 6, "method": "tools/list", "params": {"_meta": bad_meta}}
    r = http_client.post("/mcp", json=body, headers=_headers("tools/list"))
    payload = r.json()
    assert "error" in payload
    # -32602 == INVALID_PARAMS per JSON-RPC 2.0
    assert payload["error"]["code"] == -32602
