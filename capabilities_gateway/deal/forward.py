"""Forward deal vacancy-answer calls to the vacancy app. Never to this gateway."""

from __future__ import annotations

from capabilities_gateway.jsonrpc import call_tool
from capabilities_gateway.settings import vacancy_mcp_url


def _refuses_loop(url: str) -> bool:
    lowered = url.lower().rstrip("/")
    return "/mcp/deal" in lowered or lowered.endswith("/mcp/vacancy")


def forward_ask_vacancy(question: str, session_id: str = "") -> str:
    asked = (question or "").strip()
    if not asked:
        return "Name the building and the floor plan."
    url = vacancy_mcp_url()
    if _refuses_loop(url):
        return (
            "Refusing to forward vacancy answer into the capabilities gateway. "
            "VACANCY_MCP_URL must be the vacancy app /mcp."
        )
    return call_tool(
        url,
        "ask_vacancy",
        {"question": asked, "session_id": session_id or ""},
        client_name="capabilities-gateway-deal",
    )
