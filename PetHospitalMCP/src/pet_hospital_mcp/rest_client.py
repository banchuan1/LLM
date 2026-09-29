"""Async REST client for the Go Pet Hospital backend.

Wraps `httpx.AsyncClient` with:
    - per-request timeout (configurable)
    - bounded retry with exponential backoff for 5xx and network errors only
    - parsing of the Go-style envelope `{code, message, data, time}`
    - mapping of failures to `PetHospitalToolError` (no stack leakage)
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings
from .errors import (
    BACKEND_API_ERROR,
    BACKEND_INVALID_RESPONSE,
    BACKEND_TIMEOUT,
    BACKEND_UNAVAILABLE,
    PetHospitalToolError,
)


class PetHospitalRestClient:
    """Thin async wrapper around `GET /api/v1/pets` on the Go backend."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport  # None in production; set in tests via MockTransport.

    async def list_pets(self, params: dict[str, Any]) -> dict[str, Any]:
        """Call `GET {base_url}/api/v1/pets` and return the parsed `data` dict.

        Raises `PetHospitalToolError` on any failure (network, HTTP
        status, JSON parse, envelope shape). The `params` dict carries
        only non-empty filter/sort/page keys, already validated by the
        tool layer.
        """
        url = f"{self._settings.pet_hospital_base_url}/api/v1/pets"
        max_attempts = max(1, self._settings.backend_max_retries + 1)
        last_error: PetHospitalToolError | None = None

        for attempt in range(1, max_attempts + 1):
            attempt_detail = {"attempt": attempt, "max_attempts": max_attempts}
            try:
                async with httpx.AsyncClient(
                    timeout=self._settings.backend_timeout_seconds,
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    response = await client.get(url, params=params)
            except httpx.TimeoutException:
                last_error = PetHospitalToolError(
                    BACKEND_TIMEOUT,
                    f"Backend timed out after {self._settings.backend_timeout_seconds}s",
                    attempt_detail,
                )
                continue  # retry
            except httpx.ConnectError:
                last_error = PetHospitalToolError(
                    BACKEND_UNAVAILABLE,
                    "Backend unreachable",
                    attempt_detail,
                )
                continue  # retry
            except httpx.HTTPError as exc:
                last_error = PetHospitalToolError(
                    BACKEND_UNAVAILABLE,
                    f"Backend transport error: {exc.__class__.__name__}",
                    attempt_detail,
                )
                continue  # retry

            # 4xx — client-side error, do not retry.
            if 400 <= response.status_code < 500:
                raise PetHospitalToolError(
                    BACKEND_API_ERROR,
                    f"Backend returned {response.status_code}",
                    {"status_code": response.status_code, "body": response.text[:500]},
                )

            # 5xx — server-side error, retry.
            if 500 <= response.status_code < 600:
                last_error = PetHospitalToolError(
                    BACKEND_API_ERROR,
                    f"Backend returned {response.status_code}",
                    {"status_code": response.status_code, **attempt_detail},
                )
                continue

            # 2xx — parse envelope.
            return self._parse_envelope(response)

        # Exhausted retries on 5xx/network errors.
        assert last_error is not None
        raise last_error

    @staticmethod
    def _parse_envelope(response: httpx.Response) -> dict[str, Any]:
        try:
            envelope = response.json()
        except json.JSONDecodeError as exc:
            raise PetHospitalToolError(
                BACKEND_INVALID_RESPONSE,
                "Backend returned non-JSON response",
                {"status_code": response.status_code, "body": response.text[:500]},
            ) from exc

        if not isinstance(envelope, dict) or "data" not in envelope:
            raise PetHospitalToolError(
                BACKEND_INVALID_RESPONSE,
                "Backend response is missing required envelope fields",
                {"status_code": response.status_code, "body": response.text[:500]},
            )

        code = envelope.get("code")
        data = envelope.get("data")
        if code != 200 or data is None:
            raise PetHospitalToolError(
                BACKEND_API_ERROR,
                str(envelope.get("message") or "Backend envelope error"),
                {"envelope_code": code, "status_code": response.status_code},
            )

        if not isinstance(data, dict):
            raise PetHospitalToolError(
                BACKEND_INVALID_RESPONSE,
                "Backend envelope `data` is not an object",
                {"status_code": response.status_code, "data_type": type(data).__name__},
            )

        return data
