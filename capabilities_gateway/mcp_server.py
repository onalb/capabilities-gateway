"""POST /mcp — the one route for every external app.

The calling app stamps ``route`` (deal or vacancy) on every tool call. The
permit allowlist decides which tools that role may run, and the checklist
rules follow the same route. There is no per-role URL path anymore: role is
an argument, not an endpoint. The app also stamps ``X-MCP-Role`` on every
POST so tools/list can answer with that role's allowlist (the union when the
header is absent or unknown — call-time route checks still protect calls).
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ListToolsResult

from capabilities_gateway.call_log import ToolCallLog
from capabilities_gateway.checklist_mcp import mount_checklist_tools
from capabilities_gateway.invoke import call_tool
from capabilities_gateway.permits import tools_for

_ROUTES = ("deal", "vacancy")
_ROLE_HEADER = "x-mcp-role"  # Starlette lowercases header names.


def _tool_name(item: object) -> str:
    name = getattr(item, "name", None)
    if name is None and isinstance(item, dict):
        name = item.get("name")
    return str(name) if name else ""


class RoleFilteredToolsList:
    """MCP middleware: role-filtered tools/list.

    stateless_http=True gives every POST a fresh session, so the calling app
    stamps X-MCP-Role: deal|vacancy on every request. tools/list then answers
    with that role's permit allowlist (permits.tools_for). A missing or
    unknown value returns the union, which stays backwards compatible for
    direct curl and tests. This header never authorizes a call: tools/call
    keeps its route argument and invoke.call_tool enforces the same allowlist.
    """

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if getattr(ctx, "method", None) != "tools/list":
            return await call_next(ctx)
        result = await call_next(ctx)
        headers = getattr(getattr(ctx, "request", None), "headers", None)
        role = ""
        if headers is not None:
            try:
                role = str(headers.get(_ROLE_HEADER) or "").strip().lower()
            except Exception:
                role = ""
        if role not in _ROUTES:
            return result
        allowed = tools_for(role)
        tools = getattr(result, "tools", None)
        if tools is None and isinstance(result, dict):
            tools = result.get("tools")
        if not isinstance(tools, list):
            return result
        kept = [item for item in tools if _tool_name(item) in allowed]
        if isinstance(result, ListToolsResult):
            return result.model_copy(update={"tools": kept})
        if isinstance(result, dict):
            updated = dict(result)
            updated["tools"] = kept
            return updated
        return result


mcp = MCPServer(
    "capabilities",
    instructions=(
        "Capabilities for two roles, one route. The calling app stamps "
        "route=deal or route=vacancy on every tool call; the permit "
        "allowlist enforces which tools each role may run. "
        "Deal capabilities: vault counts, income, NOI, cap rate, geocode, "
        "web search, memos, and ask_prediction_agent (forwards to the vacancy "
        "app ask_vacancy, which answers from its trained store only). "
        "Vacancy capabilities: parse a rent roll, fit logistic regression, "
        "load a saved fit, list trained property names, save a fit, delete "
        "a fit, and score one floor plan. delete_fit removes JSON only when "
        "confirm is true. "
        "create_plan, update_plan, update_plan_status, and reflection are "
        "stateless: the calling app sends the checklist and writes back the "
        "returned rows."
    ),
    middleware=[ToolCallLog(), RoleFilteredToolsList()],
)

_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


def _call(name: str, arguments: dict, route: str) -> str:
    """Run one tool for the calling app's role. Route violations come back as
    a structured error payload (not a framework-generic isError) so the
    caller sees the actual reason."""
    route = str(route or "").strip()
    if route not in _ROUTES:
        return json.dumps(
            {
                "ok": False,
                "rejected": True,
                "error": f"route must be one of {', '.join(_ROUTES)} (the calling app stamps it)",
            }
        )
    try:
        return call_tool(name, arguments, route=route)
    except ValueError as exc:
        return json.dumps({"ok": False, "rejected": True, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 — never leak a framework-generic isError
        return json.dumps({"ok": False, "error": str(exc)})


@mcp.tool()
def cre_ping(route: str = "") -> dict:
    """Gateway health ping. Not a model tool."""
    return {"status": "ok", "tool": "cre_ping", "route": route}


@mcp.tool()
def query_units(
    occupancy: str | None = None,
    vacant_only: bool = False,
    username: str = "",
    as_of: str = "",
    route: str = "",
) -> str:
    """Read vault unit counts for username. The deal app injects username."""
    return _call(
        "query_units",
        {"occupancy": occupancy, "vacant_only": vacant_only, "username": username, "as_of": as_of},
        route,
    )


@mcp.tool()
def compute_income(
    vacant_fill_rent: float | None = None,
    username: str = "",
    as_of: str = "",
    route: str = "",
) -> str:
    """In-place and full-occupancy income from the vaulted roll."""
    return _call(
        "compute_income",
        {"vacant_fill_rent": vacant_fill_rent, "username": username, "as_of": as_of},
        route,
    )


@mcp.tool()
def compute_noi(
    operating_expenses: float | None = None,
    username: str = "",
    as_of: str = "",
    route: str = "",
) -> str:
    """NOI from annualized in-place income minus stated expenses."""
    return _call(
        "compute_noi",
        {"operating_expenses": operating_expenses, "username": username, "as_of": as_of},
        route,
    )


@mcp.tool()
def compute_cap_rate(
    ask_price: float,
    noi: float | None = None,
    username: str = "",
    as_of: str = "",
    route: str = "",
) -> str:
    """Implied cap rate. ask_price is required."""
    return _call(
        "compute_cap_rate",
        {"ask_price": ask_price, "noi": noi, "username": username, "as_of": as_of},
        route,
    )


@mcp.tool()
def osm_geocode(query: str, username: str = "", route: str = "") -> str:
    """Geocode a street or place."""
    return _call("osm_geocode", {"query": query, "username": username}, route)


@mcp.tool()
def web_search(
    query: str,
    max_results: int = 5,
    username: str = "",
    route: str = "",
) -> str:
    """Search the public web."""
    return _call(
        "web_search",
        {"query": query, "max_results": max_results, "username": username},
        route,
    )


@mcp.tool()
def publish_memo(
    title: str,
    body: str,
    username: str = "",
    hitl_allow: bool = False,
    route: str = "",
) -> str:
    """Stage or publish a memo. hitl_allow is set by the deal app after Approve."""
    return _call(
        "publish_memo",
        {"title": title, "body": body, "username": username, "hitl_allow": hitl_allow},
        route,
    )


@mcp.tool()
def ask_prediction_agent(
    horizon_months: int = 12,
    question: str = "",
    session_id: str = "",
    username: str = "",
    as_of: str = "",
    route: str = "",
) -> str:
    """Forecast occupancy or floor-plan vacancy. Forwards to the vacancy app MCP tool ask_vacancy.

    question is the user text. Reuse session_id on a follow-up. This tool does
    not parse, fit, or save. The vacancy app answers from its trained store
    only — a building with no saved fit gets its not-trained reply.
    """
    return _call(
        "ask_prediction_agent",
        {
            "horizon_months": horizon_months,
            "question": question,
            "session_id": session_id,
            "username": username,
            "as_of": as_of,
        },
        route,
    )


@mcp.tool()
def parse_rent_roll_file(
    file_id: str = "",
    filename: str = "",
    content_base64: str = "",
    route: str = "",
) -> dict:
    """Parse workbook bytes into a plan table. Does not save."""
    return _call(
        "parse_rent_roll_file",
        {"file_id": file_id, "filename": filename, "content_base64": content_base64},
        route,
    )


@mcp.tool()
def fit_vacancy(plans: list[dict], route: str = "") -> dict:
    """Fit logistic regression from a plan table. Does not save."""
    return _call("fit_vacancy", {"plans": plans}, route)


@mcp.tool()
def list_trained_properties(route: str = "") -> dict:
    """Names of properties this model is trained on. Does not score, fit, or delete."""
    return _call("list_trained_properties", {}, route)


@mcp.tool()
def load_fit(property_name: str = "", route: str = "") -> dict:
    """One named building's plan names. No probabilities. Does not list every property."""
    return _call("load_fit", {"property_name": property_name}, route)


@mcp.tool()
def save_fit(property_name: str, as_of: str, model: dict, route: str = "") -> dict:
    """Save one building fit returned by fit_vacancy."""
    return _call("save_fit", {"property_name": property_name, "as_of": as_of, "model": model}, route)


@mcp.tool()
def delete_fit(
    property_name: str = "",
    all_properties: bool = False,
    confirm: bool = False,
    route: str = "",
) -> dict:
    """Delete saved fit JSON. Deletes only when confirm is true.

    The vacancy app session holds the user confirmation. This server is
    stateless and does not ask the user. A direct call that omits confirm
    does not delete. all_properties removes every fit JSON.
    """
    return _call(
        "delete_fit",
        {"property_name": property_name, "all_properties": all_properties, "confirm": confirm},
        route,
    )


@mcp.tool()
def score_vacancy(building: str, plan: str = "", renovated: int | None = None, route: str = "") -> dict:
    """Score p(vacant) for one saved building and one floor plan."""
    return _call("score_vacancy", {"building": building, "plan": plan, "renovated": renovated}, route)


mount_checklist_tools(mcp)


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=_SECURITY,
        max_request_body_size=20 * 1024 * 1024,
    )