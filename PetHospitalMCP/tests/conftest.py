"""Shared pytest fixtures for the pet-hospital MCP service.

The fixtures here keep tests off the real Go backend:
    - `sample_pet`, `sample_envelope` — canned Go responses.
    - `default_backend_handler` — a function returning a 200 envelope.
    - `mock_backend_transport` — `httpx.MockTransport` using that handler.
    - `mock_rest_client` — `PetHospitalRestClient` wired to the mock transport.
    - `override_rest_client` (autouse) — installs `mock_rest_client` as the
      per-process singleton so tool handlers go through the mock backend.

The in-memory MCP `Client` is NOT a fixture — anyio's task-group cancel
scope requires that `async with Client(...)` setup, test body, and
teardown all run in the SAME task. pytest-asyncio 1.x may run fixture
setup and teardown in different tasks, which trips anyio. Tests instead
use the `with_client()` helper, which keeps the whole lifecycle inside
the test's own task.
"""
from __future__ import annotations

import contextlib
from typing import Any, AsyncIterator

import httpx
import pytest

from mcp.client import Client

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import PetHospitalRestClient
from pet_hospital_mcp.server import mcp
from pet_hospital_mcp.tools import reset_rest_client, set_rest_client


TEST_SETTINGS = Settings(
    mcp_host="127.0.0.1",
    mcp_port=8765,
    pet_hospital_base_url="http://127.0.0.1:8080",
    backend_timeout_seconds=2.0,
    backend_max_retries=2,
)


@pytest.fixture
def test_settings() -> Settings:
    return TEST_SETTINGS


@pytest.fixture
def sample_pet() -> dict[str, Any]:
    """A single Pet row matching the Go model (records/charges are null)."""
    return {
        "id": "PET-000001",
        "name": "旺财",
        "species": "犬",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "ownerAddr": "北京市朝阳区",
        "chipNo": "CHIP001",
        "disease": "急性肠胃炎",
        "doctor": "李医生",
        "status": "就诊中",
        "totalCost": 380.5,
        "visitCount": 2,
        "createdAt": "2024-01-01T10:00:00Z",
        "updatedAt": "2024-01-02T11:00:00Z",
        "records": None,  # Go nil slice → null
        "charges": None,
    }


@pytest.fixture
def sample_envelope(sample_pet: dict[str, Any]) -> dict[str, Any]:
    """A full Go success envelope for `GET /api/v1/pets`."""
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "items": [sample_pet],
            "total": 1,
            "page": 1,
            "pageSize": 20,
            "totalPages": 1,
            "totalCost": 380.5,
        },
        "time": "2024-01-01T10:00:00Z",
    }


def default_backend_handler(envelope: dict[str, Any]) -> httpx.MockTransport:
    """Build a MockTransport that always responds with `envelope`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope)

    return httpx.MockTransport(handler)


@pytest.fixture
def mock_backend_transport(sample_envelope: dict[str, Any]) -> httpx.MockTransport:
    """MockTransport returning the sample envelope for every request."""
    return default_backend_handler(sample_envelope)


@pytest.fixture
def mock_rest_client(mock_backend_transport: httpx.MockTransport) -> PetHospitalRestClient:
    """PetHospitalRestClient wired to the mock backend transport."""
    return PetHospitalRestClient(TEST_SETTINGS, transport=mock_backend_transport)


@pytest.fixture(autouse=True)
def override_rest_client(mock_rest_client: PetHospitalRestClient) -> Any:
    """Force the per-process REST client singleton to use the mock backend.

    Tests that need a different backend can call `set_rest_client(...)`
    after this fixture runs (later fixtures win).
    """
    set_rest_client(mock_rest_client)
    yield
    reset_rest_client()


def make_backend(handler: Any) -> httpx.MockTransport:
    """Helper for tests that need a custom transport (different status / body)."""
    return httpx.MockTransport(handler)


@contextlib.asynccontextmanager
async def with_client(*, raise_exceptions: bool = True) -> AsyncIterator[Client]:
    """Create an in-memory SDK 2.x Client bound to the live `mcp` server.

    Must be used as `async with with_client() as client:` inside the test
    body so that setup, test, and teardown all run in the SAME task
    (anyio's strict cancel-scope ownership requirement).
    """
    async with Client(mcp, raise_exceptions=raise_exceptions) as client:
        yield client
