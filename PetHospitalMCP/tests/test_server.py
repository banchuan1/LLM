"""Tests for the MCP server assembly — tool registration and JSON Schemas.

Goes through the in-memory MCP `Client` (no HTTP), so we exercise the
SDK's `tools/list` and `tools/call` flow against our `MCPServer`
instance.
"""
from __future__ import annotations

from .conftest import with_client


# ---------------------------------------------------------------------------
# Tool registration & JSON Schema
# ---------------------------------------------------------------------------


async def test_list_pets_is_registered():
    """`tools/list` should include exactly one tool named `list_pets`."""
    async with with_client() as client:
        result = await client.list_tools()
    names = [t.name for t in result.tools]
    assert "list_pets" in names
    # Stage 1: only one tool is exposed.
    assert len(result.tools) == 1


async def test_tool_name_is_snake_case():
    """The tool name must be snake_case per the spec."""
    async with with_client() as client:
        result = await client.list_tools()
    tool = next(t for t in result.tools if t.name == "list_pets")
    assert tool.name == "list_pets"
    assert "_" in tool.name
    assert tool.name.islower()


async def test_tool_has_input_schema_with_params_property():
    """`input_schema` must publish a `params` property referencing the model."""
    async with with_client() as client:
        result = await client.list_tools()
    tool = result.tools[0]
    schema = tool.input_schema
    assert schema["type"] == "object"
    assert "params" in schema["properties"]
    assert "params" in schema["required"]
    # The referenced model defines the 14 Go query parameters.
    # Resolve $ref to inspect the model's properties.
    defs = schema.get("$defs") or schema.get("definitions") or {}
    ref = schema["properties"]["params"].get("$ref", "")
    # The $ref looks like "#/$defs/ListPetsParams" or "#/definitions/ListPetsParams"
    model_name = ref.rsplit("/", 1)[-1]
    model_schema = defs.get(model_name, {})
    props = model_schema.get("properties", {})
    expected = {
        "q", "name", "ownerName", "ownerPhone", "species", "doctor", "disease",
        "status", "min", "max", "sortBy", "order", "page", "pageSize",
    }
    assert expected.issubset(props.keys()), f"missing: {expected - set(props.keys())}"
    # extra=forbid is enforced at the model level.
    assert model_schema.get("additionalProperties") is False


async def test_tool_has_output_schema_with_envelope_fields():
    """`output_schema` must publish the Go envelope `data` fields."""
    async with with_client() as client:
        result = await client.list_tools()
    tool = result.tools[0]
    schema = tool.output_schema
    assert schema is not None
    assert schema["type"] == "object"
    props = schema["properties"]
    for field in ("items", "total", "page", "pageSize", "totalPages", "totalCost"):
        assert field in props, f"missing output field: {field}"


async def test_tool_description_mentions_purpose_and_parameters():
    """The description should mention purpose, parameters, and use cases."""
    async with with_client() as client:
        result = await client.list_tools()
    tool = result.tools[0]
    desc = tool.description or ""
    # Sanity: the docstring mentions key terms.
    assert "pet" in desc.lower()
    assert "filter" in desc.lower() or "sort" in desc.lower() or "page" in desc.lower()
    assert "list_pets" in desc or "GET /api/v1/pets" in desc or "page" in desc.lower()


# ---------------------------------------------------------------------------
# Tool call happy path (light check; thorough tests live in test_list_pets.py)
# ---------------------------------------------------------------------------


async def test_call_tool_succeeds_via_in_memory_client(sample_envelope):
    """`tools/call list_pets` returns a successful structured_content."""
    async with with_client() as client:
        result = await client.call_tool(
            "list_pets",
            {"params": {"page": 1, "pageSize": 5}},
        )
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["total"] == sample_envelope["data"]["total"]


async def test_call_unknown_tool_returns_error():
    """Calling a non-existent tool surfaces as `is_error=true`."""
    async with with_client() as client:
        result = await client.call_tool("does_not_exist", {})
    assert result.is_error is True
    assert "Unknown tool" in result.content[0].text
