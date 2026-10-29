"""Tools handler dispatch, in-process MCP invoke, and mocked Lambda invoke."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from starlette.testclient import TestClient

from capabilities_gateway.deal.vault import put_memory_roll
from capabilities_gateway.invoke import call_tool
from capabilities_gateway.tools_lambda import handler
from capabilities_gateway.vacancy_math.tools import reset_store


def _hill() -> dict:
    return {
        "property_name": "Hill",
        "as_of": "2024-01-31",
        "layout": "one_row",
        "units": [
            {
                "unit_id": "1",
                "occupancy": "Occupied",
                "in_place_rent": 1500,
                "vacant": False,
            },
            {
                "unit_id": "2",
                "occupancy": "Vacant",
                "in_place_rent": 0,
                "vacant": True,
            },
        ],
    }


def test_handler_dispatches_a_deal_tool():
    put_memory_roll("ada", _hill())
    body = handler({"tool": "query_units", "arguments": {"username": "ada"}}, None)
    parsed = json.loads(body["result"])
    assert parsed["unit_count"] == 2
    assert parsed["vacant_count"] == 1
    assert parsed["property_name"] == "Hill"


def test_handler_dispatches_a_vacancy_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("VACANCY_FIT_DIR", str(tmp_path))
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT", raising=False)
    reset_store()
    body = handler({"tool": "list_trained_properties", "arguments": {}}, None)
    assert body["result"] == {"properties": [], "text": "No properties are trained yet."}
    reset_store()


def test_handler_parse_reads_argument_bytes(monkeypatch):
    seen: dict[str, bytes] = {}

    def fake_parse(path):
        seen["bytes"] = Path(path).read_bytes()
        return {"plans": [{"plan": "A1"}], "property": "Hill"}

    monkeypatch.setattr(
        "capabilities_gateway.vacancy_math.tools.parse_rent_roll",
        fake_parse,
    )
    raw = b"workbook-bytes"
    body = handler(
        {
            "tool": "parse_rent_roll_file",
            "arguments": {
                "file_id": "abc",
                "filename": "roll.xlsx",
                "content_base64": base64.b64encode(raw).decode("ascii"),
            },
        },
        None,
    )
    assert seen["bytes"] == raw
    assert body["result"]["file_id"] == "abc"
    assert body["result"]["plans"][0]["plan"] == "A1"


def test_handler_rejects_score_gcr():
    try:
        handler({"tool": "score_gcr", "arguments": {"draft": "Occupancy is 92%."}}, None)
    except ValueError as exc:
        assert "unknown tool" in str(exc)
    else:
        raise AssertionError("score_gcr must not be a gateway tool")


def _post(client: TestClient, path: str, body: dict, headers: dict | None = None):
    return client.post(
        path,
        json=body,
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
            **(headers or {}),
        },
        follow_redirects=False,
    )


def _call(client: TestClient, path: str, name: str, arguments: dict) -> dict:
    opened = _post(
        client,
        path,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "lambda-test", "version": "0"},
            },
        },
    )
    assert opened.status_code == 200, opened.text
    sid = opened.headers.get("mcp-session-id")
    extra = {"Mcp-Session-Id": sid} if sid else {}
    noted = _post(
        client,
        path,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=extra,
    )
    assert noted.status_code not in {301, 302, 303, 307, 308}
    response = _post(
        client,
        path,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers=extra,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_call_tool_uses_handler_when_arn_is_unset(monkeypatch):
    monkeypatch.delenv("TOOLS_LAMBDA_ARN", raising=False)
    put_memory_roll("ada", _hill())
    seen: list[dict] = []
    from capabilities_gateway import tools_lambda

    real = tools_lambda.handler

    def spy(event, context):
        seen.append(event)
        return real(event, context)

    monkeypatch.setattr(tools_lambda, "handler", spy)
    payload = call_tool("query_units", {"username": "ada"}, route="deal")
    assert seen and seen[0]["tool"] == "query_units"
    assert seen[0]["arguments"]["username"] == "ada"
    assert seen[0]["route"] == "deal"
    assert json.loads(payload)["unit_count"] == 2


def test_call_tool_invokes_lambda_when_arn_is_set(monkeypatch):
    arn = "arn:aws:lambda:us-east-1:123:function:capabilities-tools"
    monkeypatch.setenv("TOOLS_LAMBDA_ARN", arn)
    captured: dict = {}

    class _Payload:
        def read(self):
            return json.dumps(
                {"result": {"properties": [], "text": "No properties are trained yet."}}
            ).encode("utf-8")

    class _Client:
        def invoke(self, **kwargs):
            captured.update(kwargs)
            return {"StatusCode": 200, "Payload": _Payload()}

    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: _Client())
    from capabilities_gateway import tools_lambda

    def boom(event, context):
        raise AssertionError("in-process handler must not run when the ARN is set")

    monkeypatch.setattr(tools_lambda, "handler", boom)
    out = call_tool("list_trained_properties", {})
    assert out["text"] == "No properties are trained yet."
    assert captured["FunctionName"] == arn
    sent = json.loads(captured["Payload"])
    assert sent == {"tool": "list_trained_properties", "arguments": {}}
