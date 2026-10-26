"""POST /mcp/deal — deal tools and vacancy answer only."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from capabilities_gateway.deal import tools

mcp = MCPServer(
    "capabilities-deal",
    instructions=(
        "Deal capabilities: vault counts, income, NOI, cap rate, geocode, "
        "web search, memos, and vacancy answer. "
        "ask_vacancy forwards to the vacancy app and returns its sentence. "
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
def ask_vacancy(question: str, session_id: str = "") -> str:
    """Vacancy answer. Forwards to the vacancy app ask_vacancy tool.

    question is the user text (floor plan or forecast). Reuse session_id on a
    follow-up. This tool does not parse, fit, or save.
    """
    return tools.ask_vacancy(question, session_id=session_id)


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/mcp/deal",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=_SECURITY,
        max_request_body_size=20 * 1024 * 1024,
    )
