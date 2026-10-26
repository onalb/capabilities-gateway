"""Streamable-HTTP JSON-RPC client. Does not follow redirects."""

from __future__ import annotations

import json
from typing import Any

import httpx

MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-03-26",
}


def _rpc_payload(data: dict) -> dict:
    if data.get("error"):
        err = data["error"]
        if isinstance(err, dict):
            raise RuntimeError(err.get("message") or json.dumps(err))
        raise RuntimeError(str(err))
    result = data.get("result")
    return result if isinstance(result, dict) else {}


def _parse_body(response: httpx.Response) -> dict:
    if response.status_code in {301, 302, 303, 307, 308}:
        raise RuntimeError(
            f"MCP URL redirected ({response.status_code}); refusing to follow"
        )
    response.raise_for_status()
    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("MCP server returned non-JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("MCP server returned a non-object response")
    return _rpc_payload(data)


def content_text(result: dict) -> str:
    content = result.get("content")
    if isinstance(content, list) and content:
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return "\n".join(parts)
    structured = result.get("structuredContent")
    if isinstance(structured, str) and structured:
        return structured
    if isinstance(structured, dict):
        if structured.get("result") is not None and list(structured.keys()) == ["result"]:
            inner = structured["result"]
            return inner if isinstance(inner, str) else json.dumps(inner)
        return json.dumps(structured)
    text = result.get("text")
    return str(text) if text else ""


def tool_text(result: dict) -> str:
    if result.get("isError"):
        raise RuntimeError(content_text(result) or "MCP tool error")
    return content_text(result)


def post_rpc(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    method: str,
    params: dict | None = None,
    req_id: int | str | None = 1,
) -> tuple[dict, dict[str, str]]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        body["id"] = req_id
    if params is not None:
        body["params"] = params
    response = client.post(url, json=body, headers=headers, follow_redirects=False)
    session = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
    if session:
        headers = {**headers, "Mcp-Session-Id": session}
    if req_id is None:
        if response.status_code in {301, 302, 303, 307, 308}:
            raise RuntimeError(
                f"MCP URL redirected ({response.status_code}); refusing to follow"
            )
        if response.status_code >= 400:
            response.raise_for_status()
        return {}, headers
    return _parse_body(response), headers


def call_tool(
    url: str,
    name: str,
    arguments: dict[str, Any],
    *,
    client_name: str = "capabilities-gateway",
    timeout: float = 180.0,
) -> str:
    """initialize, then tools/call. Returns the tool text."""
    headers = dict(MCP_HEADERS)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        _, headers = post_rpc(
            client,
            url,
            headers,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "0.1.0"},
            },
            req_id=1,
        )
        post_rpc(client, url, headers, "notifications/initialized", req_id=None)
        result, _ = post_rpc(
            client,
            url,
            headers,
            "tools/call",
            {"name": name, "arguments": arguments},
            req_id=2,
        )
    return tool_text(result)
