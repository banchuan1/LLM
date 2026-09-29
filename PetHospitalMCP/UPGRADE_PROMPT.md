# Stage 2 — Upgrade Prompt (NOT IMPLEMENTED)

This document outlines how to extend the pet-hospital MCP service to
stage 2 (additional tools). Stage 1 implements only `list_pets`; the
items below are placeholders and are **not** part of this delivery.

## Goal

Add tools that adapt the remaining Go REST endpoints under
`/api/v1/pets` and related sub-resources, so an AI Agent can perform
the full CRUD + search surface of the pet hospital through MCP.

## Extension recipe

1. **Add a new tool module** under `src/pet_hospital_mcp/tools/`:
   - Mirror the `list_pets.py` structure:
     - Pydantic input model with `extra="forbid"` and strict
       validation (Literal enums for `species`/`status`/etc.; `ge/le`
       constraints; `model_validator` for cross-field rules).
     - Pydantic success-output model that mirrors the Go envelope's
       `data` shape (tolerate `null` lists from Go nil slices via
       `field_validator(mode="before")`).
     - Async handler decorated with `@mcp.tool()`, calling
       `get_rest_client()` (so tests can swap the backend), wrapping
       backend errors in `PetHospitalToolError`, and emitting one
       structured log line via `_log_tool_call`.
2. **No registration glue needed**: the `tools/__init__.py` module
   calls `register_all()`, which imports every tool module so
   `@mcp.tool()` decorators run at import time. Just drop the new
   file in and it is picked up automatically.
3. **REST client**: extend `PetHospitalRestClient` with the new
   endpoint (or add a sibling method). Keep the timeout + retry +
   envelope-parsing pattern; do not branch on HTTP method for retry
   policy (4xx → no retry, 5xx + network → retry).
4. **Tests**: add `tests/test_<tool_name>.py` mirroring
   `test_list_pets.py`. Use `with_client()` from `conftest.py` to keep
   the SDK Client's anyio cancel-scope inside the test task. Override
   the backend with `httpx.MockTransport` via `set_rest_client()`.
5. **Docs**: update `README.md` with the new tool's parameters,
   endpoint, and a `curl` example.

## Candidate stage 2 tools (from `internal/api/api.go`)

- `get_pet` — `GET /api/v1/pets/{id}`
- `create_pet` — `POST /api/v1/pets`
- `update_pet` — `PUT /api/v1/pets/{id}`
- `patch_pet` — `PATCH /api/v1/pets/{id}`
- `delete_pet` — `DELETE /api/v1/pets/{id}`
- `search_pets` — `GET /api/v1/pets/search?q=...`
- `list_pets_by_owner` — `GET /api/v1/pets/by-owner`
- `list_pets_by_doctor` — `GET /api/v1/pets/by-doctor`
- `list_pets_by_species` — `GET /api/v1/pets/by-species`
- `list_pets_by_disease` — `GET /api/v1/pets/by-disease`
- `list_pets_by_status` — `GET /api/v1/pets/by-status`
- `list_top_spenders` — `GET /api/v1/pets/top-spenders`
- `list_pets_by_cost_range` — `GET /api/v1/pets/cost-range`
- `list_records` — `GET /api/v1/pets/{id}/records`
- `create_record` — `POST /api/v1/pets/{id}/records`
- `list_charges` — `GET /api/v1/pets/{id}/charges`
- (and a few more — see `Endpoints()` in `internal/api/api.go`)

## Constraints that still apply

- No changes to the Go service.
- Python 3.11+, `mcp==2.0.0`, `MCPServer` (not FastMCP).
- Stateless Streamable HTTP; no `initialize` / `Mcp-Session-Id`.
- Unified error envelope for handler failures; SDK-level input
  validation produces Pydantic-style errors (documented limitation).
- JSON logging with recursive masking of `ownerPhone` / `ownerAddr` /
  `chipNo` (and their snake_case forms).
- `pytest -q` from the `pet-hospital-mcp/` directory must stay green.
