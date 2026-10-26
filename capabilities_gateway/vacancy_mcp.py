"""POST /mcp/vacancy — parse, fit, load, save, score. No deal tools, no ask_vacancy."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from capabilities_gateway.vacancy_math import tools

mcp = MCPServer(
    "capabilities-vacancy",
    instructions=(
        "Vacancy math: parse a rent roll, fit logistic regression, load a saved fit, "
        "save a fit, and score one floor plan. "
        "This path cannot read a deal vault, geocode, search, publish a memo, "
        "or answer with ask_vacancy."
    ),
)

_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)


@mcp.tool()
def parse_rent_roll_file(
    file_id: str = "",
    filename: str = "",
    content_base64: str = "",
) -> dict:
    """Parse workbook bytes into a plan table. Does not save."""
    return tools.parse_rent_roll_file(
        file_id=file_id, filename=filename, content_base64=content_base64
    )


@mcp.tool()
def fit_vacancy(plans: list[dict]) -> dict:
    """Fit logistic regression from a plan table. Does not save."""
    return tools.fit_vacancy(plans)


@mcp.tool()
def load_fit(property_name: str = "") -> dict:
    """List trained buildings, or one building's plan names. No probabilities."""
    return tools.load_fit(property_name)


@mcp.tool()
def save_fit(property_name: str, as_of: str, model: dict) -> dict:
    """Save one building fit returned by fit_vacancy."""
    return tools.save_fit(property_name, as_of, model)


@mcp.tool()
def score_vacancy(building: str, plan: str = "", renovated: int | None = None) -> dict:
    """Score p(vacant) for one saved building and one floor plan."""
    return tools.score_vacancy(building, plan, renovated)


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/mcp/vacancy",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=_SECURITY,
        max_request_body_size=20 * 1024 * 1024,
    )
