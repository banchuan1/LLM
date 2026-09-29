"""Tests for `PetHospitalRestClient` — HTTP transport, retry, envelope parsing.

These tests bypass the per-process singleton (they construct their own
`PetHospitalRestClient`) and use `httpx.MockTransport` to stub the Go
backend. No real Go service is touched.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from pet_hospital_mcp.errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    PetHospitalToolError,
)
from pet_hospital_mcp.rest_client import PetHospitalRestClient

from .conftest import TEST_SETTINGS


def _client_with(transport: httpx.MockTransport) -> PetHospitalRestClient:
    return PetHospitalRestClient(TEST_SETTINGS, transport=transport)


def _envelope(data: dict[str, Any] | None = None, code: int = 200, message: str = "ok") -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "data": data if data is not None else {},
        "time": "2024-01-01T10:00:00Z",
    }


# ---------------------------------------------------------------------------
# Happy path: parameter forwarding
# ---------------------------------------------------------------------------


async def test_forwards_all_filter_params_to_backend(sample_envelope):
    """All 14 query params should be forwarded verbatim to the Go backend."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=sample_envelope)

    client = _client_with(httpx.MockTransport(handler))
    params = {
        "q": "发烧", "name": "旺财", "ownerName": "张三", "ownerPhone": "13800001111",
        "species": "犬", "doctor": "李医生", "disease": "肠胃炎", "status": "就诊中",
        "min": 100.0, "max": 500.0, "sortBy": "name", "order": "asc",
        "page": 2, "pageSize": 25,
    }
    data = await client.list_pets(params)
    assert data == sample_envelope["data"]
    # URL is the Go endpoint, and every forwarded param landed in the query string.
    assert captured["url"].startswith("http://127.0.0.1:8080/api/v1/pets")
    forwarded = captured["params"]
    for key, value in params.items():
        assert forwarded.get(key) == str(value), f"{key} not forwarded correctly"
    # Camel-case keys preserved (Go expects camelCase).
    for camel in ("ownerName", "ownerPhone", "sortBy", "pageSize"):
        assert camel in forwarded


async def test_none_params_become_empty_string(sample_envelope):
    """httpx sends None as an empty query param (rest_client doesn't filter).

    The tool layer's `_build_query` filters out None before calling the
    rest_client; this test documents httpx's raw behavior when None
    reaches the transport.
    """
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=sample_envelope)

    client = _client_with(httpx.MockTransport(handler))
    await client.list_pets({"q": None, "name": "旺财", "species": "犬", "page": 1})
    forwarded = captured["params"]
    # httpx converts None to an empty string in the query string.
    assert forwarded["q"] == ""
    assert forwarded["name"] == "旺财"
    assert forwarded["species"] == "犬"
    assert forwarded["page"] == "1"


# ---------------------------------------------------------------------------
# 4xx — no retry, immediate BACKEND_API_ERROR
# ---------------------------------------------------------------------------


async def test_4xx_no_retry_raises_backend_api_error():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, text="not found")

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(PetHospitalToolError) as exc_info:
        await client.list_pets({"page": 1})
    assert exc_info.value.code == BACKEND_API_ERROR
    assert exc_info.value.details["status_code"] == 404
    assert call_count == 1  # no retry on 4xx


# ---------------------------------------------------------------------------
# 5xx — retried up to BACKEND_MAX_RETRIES, then BACKEND_API_ERROR
# ---------------------------------------------------------------------------


async def test_5xx_retries_then_raises_backend_api_error():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, text="boom")

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(PetHospitalToolError) as exc_info:
        await client.list_pets({"page": 1})
    assert exc_info.value.code == BACKEND_API_ERROR
    assert exc_info.value.details["status_code"] == 500
    # 1 initial + 2 retries = 3 attempts.
    assert call_count == TEST_SETTINGS.backend_max_retries + 1


async def test_5xx_then_200_recovers_within_retry_budget(sample_envelope):
    """A transient 5xx followed by 200 should succeed."""
    responses = iter([httpx.Response(500, text="boom"), httpx.Response(200, json=sample_envelope)])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    client = _client_with(httpx.MockTransport(handler))
    data = await client.list_pets({"page": 1})
    assert data == sample_envelope["data"]


# ---------------------------------------------------------------------------
# Network errors — retry, then BACKEND_TIMEOUT / BACKEND_UNAVAILABLE
# ---------------------------------------------------------------------------


async def test_timeout_retries_then_raises_backend_timeout():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("read timed out", request=request)

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(PetHospitalToolError) as exc_info:
        await client.list_pets({"page": 1})
    assert exc_info.value.code == BACKEND_TIMEOUT
    assert call_count == TEST_SETTINGS.backend_max_retries + 1


async def test_connect_error_retries_then_raises_backend_unavailable():
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(PetHospitalToolError) as exc_info:
        await client.list_pets({"page": 1})
    assert exc_info.value.code == BACKEND_UNAVAILABLE
    assert call_count == TEST_SETTINGS.backend_max_retries + 1


# ---------------------------------------------------------------------------
# Invalid backend response — BACKEND_INVALID_RESPONSE
# ---------------------------------------------------------------------------


async def test_non_json_response_raises_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(PetHospitalToolError) as exc_info:
        await client.list_pets({"page": 1})
    assert exc_info.value.code == BACKEND_INVALID_RESPONSE


async def test_envelope_missing_data_raises_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 200, "message": "ok"})  # no `data`

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(PetHospitalToolError) as exc_info:
        await client.list_pets({"page": 1})
    assert exc_info.value.code == BACKEND_INVALID_RESPONSE


async def test_envelope_non_200_code_raises_backend_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope(data=None, code=500, message="internal"))

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(PetHospitalToolError) as exc_info:
        await client.list_pets({"page": 1})
    assert exc_info.value.code == BACKEND_API_ERROR
    assert exc_info.value.details["envelope_code"] == 500


async def test_envelope_data_not_object_raises_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 200, "message": "ok", "data": [1, 2, 3]})

    client = _client_with(httpx.MockTransport(handler))
    with pytest.raises(PetHospitalToolError) as exc_info:
        await client.list_pets({"page": 1})
    assert exc_info.value.code == BACKEND_INVALID_RESPONSE
    assert exc_info.value.details["data_type"] == "list"
