"""POST /mcp/deal — deal tools and vacancy answer only."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from capabilities_gateway.deal import tools

mcp = MCPServer(
    "capabilities-deal",
    instructions=(
        "Deal capabilities: vault counts, income, NOI, cap rate, geocode, "
        "web search, memos, floor-plan vacancy on the vault roll, and "
        "ask_prediction_agent (forwards to the vacancy app ask_vacancy). "
        "This path cannot parse, fit, load, save, or score a rent roll."
    ),
)

_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


@mcp.tool()
def query_units(
    occupancy: str | None = None,
    vacant_only: bool = False,
    username: str = "",
    as_of: str = "",
) -> str:
    """Read vault unit counts for username. The deal app injects username."""
    return tools.query_units(
        occupancy=occupancy, vacant_only=vacant_only, username=username, as_of=as_of
    )


@mcp.tool()
def compute_income(
    vacant_fill_rent: float | None = None,
    username: str = "",
    as_of: str = "",
) -> str:
    """In-place and full-occupancy income from the vaulted roll."""
    return tools.compute_income(
        vacant_fill_rent=vacant_fill_rent, username=username, as_of=as_of
    )


@mcp.tool()
def compute_noi(
    operating_expenses: float | None = None,
    username: str = "",
    as_of: str = "",
) -> str:
    """NOI from annualized in-place income minus stated expenses."""
    return tools.compute_noi(
        operating_expenses=operating_expenses, username=username, as_of=as_of
    )


@mcp.tool()
def compute_cap_rate(
    ask_price: float,
    noi: float | None = None,
    username: str = "",
    as_of: str = "",
) -> str:
    """Implied cap rate. ask_price is required."""
    return tools.compute_cap_rate(
        ask_price=ask_price, noi=noi, username=username, as_of=as_of
    )


@mcp.tool()
def osm_geocode(query: str, username: str = "") -> str:
    """Geocode a street or place."""
    return tools.osm_geocode(query, username=username)


@mcp.tool()
def web_search(
    query: str,
    max_results: int = 5,
    force_fail: bool = False,
    username: str = "",
) -> str:
    """Search the public web."""
    return tools.web_search(
        query, max_results=max_results, force_fail=force_fail, username=username
    )


@mcp.tool()
def publish_memo(
    title: str,
    body: str,
    username: str = "",
    hitl_allow: bool = False,
) -> str:
    """Stage or publish a memo. hitl_allow is set by the deal app after Approve."""
    return tools.publish_memo(title, body, username=username, hitl_allow=hitl_allow)


@mcp.tool()
def ask_vacancy_agent(
    floor_plan: str | None = None,
    username: str = "",
    as_of: str = "",
) -> str:
    """Probability a floor plan is vacant, fit on this user's vault roll.

    Does not call the vacancy app. Omit floor_plan to score every plan.
    """
    return tools.ask_vacancy_agent(floor_plan=floor_plan, username=username, as_of=as_of)


@mcp.tool()
def ask_prediction_agent(
    horizon_months: int = 12,
    question: str = "",
    session_id: str = "",
    username: str = "",
    as_of: str = "",
) -> str:
    """Forecast occupancy. Forwards to the vacancy app MCP tool ask_vacancy.

    question is the user text. Reuse session_id on a follow-up. This tool does
    not parse, fit, or save, and it does not score the vault roll itself.
    """
    return tools.ask_prediction_agent(
        horizon_months=horizon_months,
        question=question,
        session_id=session_id,
        username=username,
        as_of=as_of,
    )


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/mcp/deal",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=_SECURITY,
        max_request_body_size=20 * 1024 * 1024,
    )
