"""Forward deal vacancy-answer calls to the vacancy app. Never to this gateway."""

from __future__ import annotations

from capabilities_gateway.jsonrpc import call_tool
from capabilities_gateway.settings import vacancy_mcp_url


def _refuses_loop(url: str) -> bool:
    """ask_vacancy must go to the vacancy app, never to this gateway itself."""
    low = url.lower().rstrip("/")
    return (
        "/mcp/deal" in low
        or low.endswith("/mcp/vacancy")
        or low.endswith(":8010/mcp")
        or "bedrock-agentcore" in low
    )


def forward_ask_vacancy(
    question: str,
    session_id: str = "",
    plan_table: list | None = None,
) -> str:
    asked = (question or "").strip()
    if not asked:
        return "Name the building and the floor plan."
    url = vacancy_mcp_url()
    if _refuses_loop(url):
        return (
            "Refusing to forward vacancy answer into the capabilities gateway. "
            "VACANCY_MCP_URL must be the vacancy app /mcp."
        )
    arguments: dict = {"question": asked, "session_id": session_id or ""}
    if plan_table:
        # Aggregated per-plan groups fit transiently on the vacancy session.
        # Never a raw roll and never saved.
        arguments["plan_table"] = plan_table
    return call_tool(
        url,
        "ask_vacancy",
        arguments,
        client_name="capabilities-gateway-deal",
    )
