"""Invoke the tools Lambda, or the same handler in this process.

``TOOLS_LAMBDA_ARN`` set: ``boto3`` ``lambda.invoke`` of that function.
Unset or blank: call ``capabilities_gateway.tools_lambda.handler`` here.
Local docker and pytest leave it unset and do not need an AWS account.
"""

from __future__ import annotations

import json
import os
from typing import Any


def tools_lambda_arn() -> str:
    return os.environ.get("TOOLS_LAMBDA_ARN", "").strip()


def call_tool(name: str, arguments: dict | None = None, *, route: str = "") -> Any:
    """Run one gateway tool. ``route`` is only for the four checklist tools."""
    event: dict[str, Any] = {"tool": name, "arguments": dict(arguments or {})}
    if route:
        event["route"] = route
    arn = tools_lambda_arn()
    if not arn:
        from capabilities_gateway import tools_lambda

        body = tools_lambda.handler(event, None)
    else:
        body = _invoke_lambda(arn, event)
    if not isinstance(body, dict) or "result" not in body:
        raise RuntimeError("tools handler returned an unexpected payload")
    return body["result"]


def _invoke_lambda(arn: str, event: dict[str, Any]) -> dict[str, Any]:
    import boto3

    client = boto3.client("lambda")
    response = client.invoke(
        FunctionName=arn,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode("utf-8"),
    )
    raw = response["Payload"].read()
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw or "")
    try:
        body = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("tools Lambda returned non-JSON") from exc
    if response.get("FunctionError"):
        message = ""
        if isinstance(body, dict):
            message = str(body.get("errorMessage") or body.get("errorType") or "")
        raise RuntimeError(message or "tools Lambda invoke failed")
    if not isinstance(body, dict):
        raise RuntimeError("tools Lambda returned an unexpected payload")
    return body
