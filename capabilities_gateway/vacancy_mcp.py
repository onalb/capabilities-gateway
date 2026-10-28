"""POST /mcp/vacancy — parse, fit, load, list, save, score. No deal tools, no ask_vacancy."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from capabilities_gateway.call_log import ToolCallLog
from capabilities_gateway.checklist_mcp import mount_checklist_tools
from capabilities_gateway.vacancy_math import tools

mcp = MCPServer(
    "capabilities-vacancy",
    instructions=(
        "Vacancy math: parse a rent roll, fit logistic regression, load a saved fit, "
        "list trained property names, save a fit, delete a fit, and score one floor plan. "
        "delete_fit removes JSON only when confirm is true. The vacancy app holds "
        "the user confirmation on its session and sends confirm only after the "
        "user agrees to that same scope. This server does not store that pending "
        "question. A direct call is not a user prompt and must not be used to "
        "skip the vacancy session gate. The model-facing vacancy tool still "
        "requires the two-step flow. "
        "create_plan, update_plan, update_plan_status, and reflection are "
        "stateless: the vacancy app sends the checklist and writes back the "
        "returned rows. This path cannot read a deal vault, geocode, search, "
        "publish a memo, or answer with ask_vacancy."
    ),
    middleware=[ToolCallLog("/mcp/vacancy")],
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
def list_trained_properties() -> dict:
    """Names of properties this model is trained on. Does not score, fit, or delete."""
    return tools.list_trained_properties()


@mcp.tool()
def load_fit(property_name: str = "") -> dict:
    """One named building's plan names. No probabilities. Does not list every property."""
    return tools.load_fit(property_name)


@mcp.tool()
def save_fit(property_name: str, as_of: str, model: dict) -> dict:
    """Save one building fit returned by fit_vacancy."""
    return tools.save_fit(property_name, as_of, model)


@mcp.tool()
def delete_fit(
    property_name: str = "",
    all_properties: bool = False,
    confirm: bool = False,
) -> dict:
    """Delete saved fit JSON. Deletes only when confirm is true.

    The vacancy app session holds the user confirmation. This server is
    stateless and does not ask the user. It deletes the file only when that
    app sends confirm=true after the pending check. A direct call that omits
    confirm does not delete. Do not use this path to skip the user: the
    model-facing vacancy tool requires the two-step flow and withholds confirm
    until the same scope is pending. all_properties removes every fit JSON.
    """
    return tools.delete_fit(
        property_name, all_properties=all_properties, confirm=confirm
    )


@mcp.tool()
def score_vacancy(building: str, plan: str = "", renovated: int | None = None) -> dict:
    """Score p(vacant) for one saved building and one floor plan."""
    return tools.score_vacancy(building, plan, renovated)


mount_checklist_tools(mcp, "vacancy")


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/mcp/vacancy",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=_SECURITY,
        max_request_body_size=20 * 1024 * 1024,
    )
