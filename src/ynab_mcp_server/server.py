"""YNAB MCP Server using FastMCP and OpenAPI specification."""

import os
from typing import Any

import httpx
import yaml
from fastmcp import FastMCP
from fastmcp.server.openapi import MCPType, RouteMap

YNAB_API_BASE = "https://api.ynab.com/v1"
YNAB_OPENAPI_SPEC_URL = "https://api.ynab.com/papi/open_api_spec.yaml"

# Routes to exclude from the MCP server (these return too much data and bomb the context)
EXCLUDED_ROUTES = [
    RouteMap(
        methods=["GET"],
        pattern=r"^/plans/\{plan_id\}/payees$",
        mcp_type=MCPType.EXCLUDE,
    ),
]


def _normalize_nullable(node: Any) -> Any:
    """Convert OpenAPI 3.0-style ``nullable: true`` to JSON Schema 3.1 ``type: "null"`` unions.

    The YNAB spec declares ``openapi: 3.1.1`` but still uses the 3.0 ``nullable`` keyword
    (e.g. on ``PlanSummaryResponse.data.default_plan``). FastMCP only runs its nullable
    converter for ``openapi_version`` starting with "3.0", so on 3.1 specs the keyword is
    dropped and the resulting JSON Schema rejects ``null`` values returned by the API,
    surfacing as "Output validation error: None is not of type 'object'".
    """
    if isinstance(node, dict):
        node = {k: _normalize_nullable(v) for k, v in node.items()}
        if node.pop("nullable", False):
            if any(k in node for k in ("allOf", "anyOf", "oneOf", "$ref")):
                return {"anyOf": [node, {"type": "null"}]}
            current_type = node.get("type")
            if isinstance(current_type, list):
                if "null" not in current_type:
                    node["type"] = [*current_type, "null"]
            elif isinstance(current_type, str):
                node["type"] = [current_type, "null"]
            else:
                return {"anyOf": [node, {"type": "null"}]}
        return node
    if isinstance(node, list):
        return [_normalize_nullable(item) for item in node]
    return node


def create_server() -> FastMCP:
    """Create and configure the YNAB MCP server from the OpenAPI spec."""
    token = os.environ.get("YNAB_API_TOKEN")
    if not token:
        raise ValueError(
            "YNAB_API_TOKEN environment variable is required. "
            "Get your personal access token from https://app.ynab.com/settings/developer"
        )

    # Fetch the OpenAPI spec from YNAB
    spec_response = httpx.get(YNAB_OPENAPI_SPEC_URL)
    spec_response.raise_for_status()
    openapi_spec = _normalize_nullable(yaml.safe_load(spec_response.text))

    # Create an authenticated HTTP client
    client = httpx.AsyncClient(
        base_url=YNAB_API_BASE,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )

    # Create MCP server from OpenAPI spec
    return FastMCP.from_openapi(
        openapi_spec=openapi_spec,
        client=client,
        name="YNAB MCP Server",
        route_maps=EXCLUDED_ROUTES,
    )


mcp = create_server()

if __name__ == "__main__":
    mcp.run()
