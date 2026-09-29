"""Tests for the `list_pets` tool — input validation, success path, param forwarding.

Goes through the in-memory MCP `Client` (no HTTP), so the SDK's tool
dispatch and our `PetHospitalToolError` → `is_error=true` wire format
are exercised end-to-end. The backend is mocked via the autouse
`override_rest_client` fixture (or per-test overrides).
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    PetHospitalToolError,
)
from pet_hospital_mcp.rest_client import PetHospitalRestClient
from pet_hospital_mcp.tools import set_rest_client
from pet_hospital_mcp.tools.list_pets import ListPetsParams, ListPetsResult

from .conftest import TEST_SETTINGS, with_client


def _client_returning(transport: httpx.MockTransport) -> PetHospitalRestClient:
    return PetHospitalRestClient(TEST_SETTINGS, transport=transport)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


async def test_success_returns_structured_content(sample_envelope, sample_pet):
    """A valid call should return structured_content matching the Go envelope."""
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"species": "犬", "page": 1, "pageSize": 5}},
        )
    assert result.is_error is False
    assert result.structured_content is not None
    data = sample_envelope["data"]
    assert result.structured_content["total"] == data["total"]
    assert result.structured_content["page"] == data["page"]
    assert result.structured_content["pageSize"] == data["pageSize"]
    assert result.structured_content["totalPages"] == data["totalPages"]
    assert result.structured_content["totalCost"] == data["totalCost"]
    assert len(result.structured_content["items"]) == 1
    item = result.structured_content["items"][0]
    assert item["id"] == sample_pet["id"]
    assert item["species"] == sample_pet["species"]
    # records/charges null → normalised to empty list
    assert item["records"] == []
    assert item["charges"] == []


async def test_success_forwards_params_to_backend(sample_envelope):
    """Tool should forward all 14 params (camelCase keys preserved) to the backend."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=sample_envelope)

    set_rest_client(_client_returning(httpx.MockTransport(handler)))

    async with with_client() as client:
        await client.call_tool(
            "list_pets",
            {"params": {
                "q": "发烧", "name": "旺财", "ownerName": "张三", "ownerPhone": "13800001111",
                "species": "犬", "doctor": "李医生", "disease": "肠胃炎", "status": "就诊中",
                "min": 100, "max": 500, "sortBy": "name", "order": "asc",
                "page": 2, "pageSize": 25,
            }},
        )
    forwarded = captured["params"]
    for key, expected in [
        ("q", "发烧"), ("name", "旺财"), ("ownerName", "张三"), ("ownerPhone", "13800001111"),
        ("species", "犬"), ("doctor", "李医生"), ("disease", "肠胃炎"), ("status", "就诊中"),
        ("min", "100.0"), ("max", "500.0"), ("sortBy", "name"), ("order", "asc"),
        ("page", "2"), ("pageSize", "25"),
    ]:
        assert forwarded.get(key) == expected, f"{key}: got {forwarded.get(key)!r}, want {expected!r}"


# ---------------------------------------------------------------------------
# Input validation (caught by the SDK's Pydantic layer)
# ---------------------------------------------------------------------------


async def test_rejects_unknown_input_field():
    """`extra=forbid` rejects unknown fields inside `params`."""
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"bogus": 1}},
        )
    assert result.is_error is True
    text = result.content[0].text
    # SDK wraps the Pydantic ValidationError as "Error executing tool list_pets: <msg>".
    assert "Error executing tool list_pets" in text
    assert "extra" in text or "bogus" in text  # Pydantic mentions the rejected field


async def test_rejects_bad_species_enum():
    """`species: Literal[...]` rejects values outside the Go enum."""
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"species": "外星人"}},
        )
    assert result.is_error is True
    assert "Error executing tool list_pets" in result.content[0].text


async def test_rejects_bad_status_enum():
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"status": "外星人"}},
        )
    assert result.is_error is True
    assert "Error executing tool list_pets" in result.content[0].text


async def test_rejects_bad_sortby_enum():
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"sortBy": "randomField"}},
        )
    assert result.is_error is True
    assert "Error executing tool list_pets" in result.content[0].text


async def test_rejects_bad_order_enum():
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"order": "sideways"}},
        )
    assert result.is_error is True
    assert "Error executing tool list_pets" in result.content[0].text


async def test_rejects_page_below_one():
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"page": 0}},
        )
    assert result.is_error is True
    assert "Error executing tool list_pets" in result.content[0].text


async def test_rejects_pagesize_out_of_range():
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"pageSize": 0}},
        )
    assert result.is_error is True

    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"pageSize": 501}},
        )
    assert result.is_error is True


async def test_rejects_negative_min():
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"min": -1}},
        )
    assert result.is_error is True


async def test_rejects_min_greater_than_max():
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"min": 100, "max": 10}},
        )
    assert result.is_error is True
    assert "min must be <= max" in result.content[0].text


async def test_rejects_nan_string_for_min():
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"min": "NaN"}},
        )
    assert result.is_error is True
    assert "NaN" in result.content[0].text or "nan" in result.content[0].text


async def test_rejects_infinity_string_for_max():
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"max": "Infinity"}},
        )
    assert result.is_error is True


# ---------------------------------------------------------------------------
# Backend errors (caught by our handler → unified envelope)
# ---------------------------------------------------------------------------


async def test_backend_4xx_returns_unified_envelope():
    """4xx from the backend should surface as our unified error envelope."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    set_rest_client(_client_returning(httpx.MockTransport(handler)))

    async with with_client() as client:
        result = await client.call_tool("list_pets", {"params": {"page": 1}})
    assert result.is_error is True
    text = result.content[0].text
    # Strip the SDK prefix to recover our JSON envelope.
    prefix = "Error executing tool list_pets: "
    assert text.startswith(prefix)
    payload = json.loads(text[len(prefix):])
    assert payload["error"]["code"] == BACKEND_API_ERROR
    assert payload["error"]["details"]["status_code"] == 404


async def test_backend_timeout_returns_unified_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    set_rest_client(_client_returning(httpx.MockTransport(handler)))

    async with with_client() as client:
        result = await client.call_tool("list_pets", {"params": {"page": 1}})
    assert result.is_error is True
    prefix = "Error executing tool list_pets: "
    payload = json.loads(result.content[0].text[len(prefix):])
    assert payload["error"]["code"] == "BACKEND_TIMEOUT"


async def test_backend_unreachable_returns_unified_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    set_rest_client(_client_returning(httpx.MockTransport(handler)))

    async with with_client() as client:
        result = await client.call_tool("list_pets", {"params": {"page": 1}})
    assert result.is_error is True
    prefix = "Error executing tool list_pets: "
    payload = json.loads(result.content[0].text[len(prefix):])
    assert payload["error"]["code"] == "BACKEND_UNAVAILABLE"


async def test_backend_invalid_response_returns_unified_envelope():
    """Backend returns malformed data → BACKEND_INVALID_RESPONSE envelope."""
    def handler(request: httpx.Request) -> httpx.Response:
        # `items` missing → ListPetsResult validation fails.
        return httpx.Response(200, json={
            "code": 200, "message": "ok",
            "data": {"total": 1, "page": 1, "pageSize": 20, "totalPages": 1, "totalCost": 0.0},
            "time": "2024-01-01T10:00:00Z",
        })

    set_rest_client(_client_returning(httpx.MockTransport(handler)))

    async with with_client() as client:
        result = await client.call_tool("list_pets", {"params": {"page": 1}})
    assert result.is_error is True
    prefix = "Error executing tool list_pets: "
    payload = json.loads(result.content[0].text[len(prefix):])
    assert payload["error"]["code"] == BACKEND_INVALID_RESPONSE


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


async def test_defaults_page_and_pagesize_when_omitted(sample_envelope):
    """Omitting page/pageSize should default to 1/20 (per Go backend)."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=sample_envelope)

    set_rest_client(_client_returning(httpx.MockTransport(handler)))

    async with with_client() as client:
        await client.call_tool("list_pets", {"params": {}})
    assert captured["params"].get("page") == "1"
    assert captured["params"].get("pageSize") == "20"


# ---------------------------------------------------------------------------
# Unit tests for the Pydantic models (no MCP layer)
# ---------------------------------------------------------------------------


def test_list_pets_params_accepts_all_valid_fields():
    params = ListPetsParams(
        q="发烧", name="旺财", ownerName="张三", ownerPhone="13800001111",
        species="犬", doctor="李医生", disease="肠胃炎", status="就诊中",
        min=100, max=500, sortBy="name", order="asc", page=2, pageSize=25,
    )
    assert params.page == 2
    assert params.pageSize == 25


def test_list_pets_params_defaults():
    params = ListPetsParams()
    assert params.page == 1
    assert params.pageSize == 20
    assert params.q is None
    assert params.species is None


def test_list_pets_result_validates_sample(sample_pet):
    """ListPetsResult should accept the sample PetModel and normalise nulls."""
    result = ListPetsResult.model_validate({
        "items": [sample_pet],
        "total": 1, "page": 1, "pageSize": 20, "totalPages": 1, "totalCost": 380.5,
    })
    assert len(result.items) == 1
    assert result.items[0].records == []  # null → []
    assert result.items[0].charges == []  # null → []
