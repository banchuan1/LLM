"""`list_pets` MCP tool — adapts `GET /api/v1/pets` on the Go backend.

Input model — exactly the 14 Go query parameters, all optional, with
strict Pydantic validation: `species`/`status`/`sortBy`/`order` are
`Literal` enums drawn from the Go backend's allowed values; `page>=1`,
`1<=pageSize<=500`, `min`/`max` non-negative with `min<=max` enforced
at the model level; `extra=forbid` rejects unknown fields; a
`field_validator` rejects `NaN`/`Infinity` strings before numeric
coercion. The model is passed to the handler as a single Pydantic
parameter so the input schema references it via a top-level `params`
property.

Success output — `ListPetsResult` mirrors the Go envelope's `data`
payload: `items`, `total`, `page`, `pageSize`, `totalPages`,
`totalCost`. `PetModel` tolerates the Go nil-slice marshaling of
`records`/`charges` (which arrive as `null`) by normalizing them to
empty lists.

Failure — raises `PetHospitalToolError`, which the SDK converts to an
`is_error=true` tool result whose `content[0].text` is
`Error executing tool list_pets: <JSON envelope>` (the prefix is
framework metadata; the JSON envelope is our payload).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Literal

import pydantic
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..errors import (
    BACKEND_INVALID_RESPONSE,
    INTERNAL_ERROR,
    PetHospitalToolError,
)
from ..logging_config import mask_payload
from ..rest_client import PetHospitalRestClient
from ..server import mcp

logger = logging.getLogger(__name__)

# Enums mirrored from internal/store/store.go + internal/api/api.go.
SpeciesValues = Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
StatusValues = Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
SortByValues = Literal[
    "id", "name", "ownerName", "species", "doctor", "disease",
    "status", "totalCost", "visitCount", "createdAt", "updatedAt",
]
OrderValues = Literal["asc", "desc"]

# String spellings rejected as NaN/Infinity (case-insensitive).
_NAN_INF_TOKENS = frozenset({
    "nan", "infinity", "+infinity", "-infinity",
    "inf", "+inf", "-inf",
})


class ListPetsParams(BaseModel):
    """Input model — exactly the 14 Go query parameters."""

    model_config = ConfigDict(extra="forbid")

    q: str | None = None
    name: str | None = None
    ownerName: str | None = None
    ownerPhone: str | None = None
    species: SpeciesValues | None = None
    doctor: str | None = None
    disease: str | None = None
    status: StatusValues | None = None
    min: float | None = Field(default=None, ge=0)
    max: float | None = Field(default=None, ge=0)
    sortBy: SortByValues | None = None
    order: OrderValues | None = None
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=500)

    @field_validator("min", "max", mode="before")
    @classmethod
    def _reject_nan_inf(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            if v.strip().lower() in _NAN_INF_TOKENS:
                raise ValueError("NaN/Infinity not allowed")
        return v

    @model_validator(mode="after")
    def _check_min_max(self) -> "ListPetsParams":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class MedicalRecordModel(BaseModel):
    """Mirror of Go MedicalRecord (see internal/model/model.go)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    visitDate: str | None = None
    doctor: str = ""
    diagnosis: str = ""
    symptoms: str | None = None
    treatment: str | None = None
    prescription: list[str] | None = None
    weightKg: float | None = None
    temperature: float | None = None
    followUp: str | None = None
    charge: float = 0.0
    createdAt: str | None = None


class TreatmentModel(BaseModel):
    """Mirror of Go Treatment (see internal/model/model.go)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    item: str = ""
    category: str | None = None
    amount: float = 0.0
    doctor: str | None = None
    date: str | None = None
    note: str | None = None


class PetModel(BaseModel):
    """Mirror of Go Pet — `records`/`charges` may be `null` or array in JSON."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    species: str
    ownerName: str
    ownerPhone: str
    ownerAddr: str | None = None
    chipNo: str | None = None
    disease: str
    doctor: str
    status: str
    totalCost: float = 0.0
    visitCount: int = 0
    createdAt: str | None = None
    updatedAt: str | None = None
    records: list[MedicalRecordModel] | None = None
    charges: list[TreatmentModel] | None = None

    @field_validator("records", "charges", mode="before")
    @classmethod
    def _null_to_list(cls, v: Any) -> Any:
        # Go nil slice marshals to `null`; normalize to empty list.
        if v is None:
            return []
        return v


class ListPetsResult(BaseModel):
    """Success output — mirrors Go envelope's `data` payload."""

    model_config = ConfigDict(extra="ignore")

    items: list[PetModel]
    total: int
    page: int
    pageSize: int
    totalPages: int
    totalCost: float


def _build_query(params: ListPetsParams) -> dict[str, Any]:
    """Translate non-empty input fields to Go-compatible query params."""
    out: dict[str, Any] = {}
    for key, value in params.model_dump().items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        out[key] = value
    return out


@mcp.tool()
async def list_pets(params: ListPetsParams) -> ListPetsResult:
    """List pet profiles from the pet hospital, with filtering, sorting, and pagination.

    Use this tool to query the pet hospital's patient registry. All 14
    parameters are optional and are forwarded verbatim to the Go REST
    API `GET /api/v1/pets`. `species`/`status` are exact-match filters
    (use the allowed enum values); the remaining text fields do
    case-insensitive substring matching. `page` starts at 1; `pageSize`
    is capped at 500. Use `min`/`max` to filter by total cost.

    Applicable when the user asks about pet patients, their owners,
    doctors, diseases, or visit history. Returns the matching page's
    items plus pagination totals and the accumulated cost across all
    matching records.

    On failure, the tool result carries `is_error=true` with a JSON
    envelope `{"error": {"code", "message", "details"}}` describing
    the failure (validation, backend timeout, backend unavailable,
    backend API error, invalid backend response, or internal error).
    """
    tool_name = "list_pets"
    started = time.perf_counter()
    query = _build_query(params)
    masked_params = mask_payload(query)
    status = "ok"
    error_payload: dict[str, Any] | None = None
    try:
        from . import get_rest_client  # local import to avoid module-load cycle
        client = get_rest_client()
        data = await client.list_pets(query)
        try:
            result = ListPetsResult.model_validate(data)
        except pydantic.ValidationError as exc:
            status = "error"
            error_payload = {
                "error": {
                    "code": BACKEND_INVALID_RESPONSE,
                    "message": "Backend response did not match the expected data model",
                    "details": {"errors": exc.errors()},
                }
            }
            raise PetHospitalToolError(
                BACKEND_INVALID_RESPONSE,
                "Backend response did not match the expected data model",
                {"errors": exc.errors()},
            ) from exc
        return result
    except PetHospitalToolError as exc:
        status = "error"
        error_payload = exc.to_payload()
        raise
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        status = "error"
        error_payload = {
            "error": {
                "code": INTERNAL_ERROR,
                "message": "Unexpected internal error",
                "details": {"exception_type": exc.__class__.__name__},
            }
        }
        raise PetHospitalToolError(
            INTERNAL_ERROR,
            "Unexpected internal error",
            {"exception_type": exc.__class__.__name__},
        ) from exc
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_tool_call(
            tool_name=tool_name,
            params=masked_params,
            status=status,
            duration_ms=duration_ms,
            error_payload=error_payload,
        )


def _log_tool_call(
    *,
    tool_name: str,
    params: dict[str, Any],
    status: str,
    duration_ms: int,
    error_payload: dict[str, Any] | None,
) -> None:
    """Emit one structured log line per tool call."""
    extra: dict[str, Any] = {
        "tool_name": tool_name,
        "params": params,
        "status": status,
        "duration_ms": duration_ms,
    }
    if error_payload is not None:
        err = error_payload.get("error", {}) if isinstance(error_payload, dict) else {}
        extra["error_code"] = err.get("code")
        extra["details"] = mask_payload(err.get("details") or {})
    logger.info("tool call", extra=extra)
