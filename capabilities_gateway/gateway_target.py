"""AgentCore gateway target. One Lambda entry for every permitted tool.

The gateway invokes this after AuthorizeAction. ``route`` and ``roll`` are
stamped by the calling app. They are not model decisions.
"""

from __future__ import annotations

import json
from typing import Any

from capabilities_gateway import tools_lambda
from capabilities_gateway.deal import vault

_ENVELOPE = {"name", "toolName", "id", "context", "toolContext", "arguments", "input", "toolInput"}


def _tool_name(event: dict[str, Any], context: Any) -> str:
    cc = getattr(context, "client_context", None)
    custom = getattr(cc, "custom", None) if cc is not None else None
    if isinstance(custom, dict):
        raw = custom.get("bedrockAgentCoreToolName") or custom.get("bedrockAgentCoreToolname") or ""
        if raw:
            return str(raw)
    return str(event.get("toolName") or event.get("name") or "")


def _arguments(event: dict[str, Any]) -> dict[str, Any]:
    for key in ("arguments", "toolInput", "input"):
        raw = event.get(key)
        if isinstance(raw, dict):
            return dict(raw)
    return {key: value for key, value in event.items() if key not in _ENVELOPE}


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    event = event or {}
    name = _tool_name(event, context).split("___")[-1].split("/")[-1]
    args = _arguments(event)
    route = str(args.pop("route", "") or "")
    roll = args.pop("roll", None)
    token = vault.set_snapshot(roll if isinstance(roll, dict) else None)
    try:
        if name == "cre_ping":
            return {"status": "ok", "tool": "cre_ping"}
        body = tools_lambda.handler({"tool": name, "arguments": args, "route": route}, context)
    finally:
        vault.reset_snapshot(token)
    inner = body.get("result") if isinstance(body, dict) else body
    if isinstance(inner, str):
        try:
            parsed = json.loads(inner)
        except json.JSONDecodeError:
            return {"text": inner}
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    if isinstance(inner, dict):
        return inner
    return {"result": inner}
