"""One Lambda for every capabilities-gateway tool.

Entry point: ``capabilities_gateway.tools_lambda.handler``.

Event::

    {"tool": "<name>", "arguments": {...}}

Checklist tools also need ``"route": "deal"`` or ``"route": "vacancy"``.
That field is not an MCP argument. The gateway wrapper adds it.

``score_gcr`` is not a tool here. Skills are not tools here.
``ask_vacancy`` stays on the vacancy app. ``ask_prediction_agent`` forwards
to that app from this handler.
"""

from __future__ import annotations

from typing import Any

from capabilities_gateway.checklist import apply_checklist
from capabilities_gateway.deal import tools as deal_tools
from capabilities_gateway.deal.tools import DEAL_TOOL_NAMES
from capabilities_gateway.vacancy_math import tools as vacancy_tools
from capabilities_gateway.vacancy_math.tools import VACANCY_TOOL_NAMES

_CHECKLIST = frozenset(
    {"create_plan", "update_plan", "update_plan_status", "reflection"}
)


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """Dispatch one tool call. ``context`` is the Lambda context; local calls pass None."""
    del context
    if not isinstance(event, dict):
        raise TypeError("event must be an object")
    name = str(event.get("tool") or "").strip()
    arguments = event.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise TypeError("arguments must be an object")
    route = str(event.get("route") or "").strip()
    return {"result": dispatch(name, arguments, route)}


def dispatch(name: str, arguments: dict[str, Any], route: str = "") -> Any:
    if name in _CHECKLIST:
        if route not in {"deal", "vacancy"}:
            raise ValueError("checklist route must be deal or vacancy")
        return apply_checklist(route, name, arguments)
    if name in DEAL_TOOL_NAMES:
        return getattr(deal_tools, name)(**arguments)
    if name in VACANCY_TOOL_NAMES:
        return getattr(vacancy_tools, name)(**arguments)
    raise ValueError(f"unknown tool: {name}")
