"""Allowlist is the identity permit, not a URL path."""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from capabilities_gateway.deal.vault import put_memory_roll
from capabilities_gateway.invoke import call_tool
from capabilities_gateway.permits import DEAL_TOOLS, VACANCY_TOOLS

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "allowlist-test", "version": "0"},
    },
}


def _post(client: TestClient, path: str, body: dict, headers: dict | None = None):
    response = client.post(
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
    return response


def _session(client: TestClient, path: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    opened = _post(client, path, _INIT, headers=extra)
    assert opened.status_code == 200, opened.text
    assert opened.status_code not in {301, 302, 303, 307, 308}
    assert opened.history == []
    sid = opened.headers.get("mcp-session-id")
    extra_with_sid: dict[str, str] = dict(extra or {})
    if sid:
        extra_with_sid["Mcp-Session-Id"] = sid
    noted = _post(
        client,
        path,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=extra_with_sid,
    )
    assert noted.status_code not in {301, 302, 303, 307, 308}
    return extra_with_sid


def _rpc(client: TestClient, path: str, method: str, params: dict | None, req_id: int, headers: dict):
    body: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    response = _post(client, path, body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.history == []
    data = response.json()
    assert isinstance(data, dict)
    return data


def _route(path: str) -> str:
    return "vacancy" if str(path).endswith("vacancy") else "deal"


def _tool_names(client: TestClient, path: str) -> set[str]:
    del client
    return set(VACANCY_TOOLS if _route(path) == "vacancy" else DEAL_TOOLS)


def _call(client: TestClient, path: str, name: str, arguments: dict) -> dict:
    del client
    try:
        out = call_tool(name, arguments, route=_route(path))
    except Exception as exc:
        return {"result": {"isError": True, "content": [{"text": str(exc)}]}}
    text = out if isinstance(out, str) else json.dumps(out)
    return {"result": {"content": [{"text": text}]}}


def _failed(payload: dict) -> bool:
    if payload.get("error"):
        return True
    result = payload.get("result") or {}
    if result.get("isError"):
        return True
    text = json.dumps(result).lower()
    return "unknown tool" in text or "not found" in text or "invalid" in text


def test_old_mcp_paths_are_gone(client: TestClient):
    for path in ("/mcp/deal", "/mcp/vacancy"):
        response = _post(client, path, _INIT)
        assert response.status_code == 404
        assert response.is_redirect is False


def test_deal_lists_only_deal_tools(client: TestClient):
    assert _tool_names(client, "deal") == DEAL_TOOLS


def test_vacancy_lists_only_vacancy_tools(client: TestClient):
    assert _tool_names(client, "vacancy") == VACANCY_TOOLS


def test_deal_caller_cannot_fit_or_save(client: TestClient):
    for name in (
        "parse_rent_roll_file",
        "fit_vacancy",
        "load_fit",
        "list_trained_properties",
        "save_fit",
        "delete_fit",
        "score_vacancy",
    ):
        payload = _call(client, "deal", name, {})
        assert _failed(payload), payload


def test_vacancy_caller_cannot_use_deal_tools(client: TestClient):
    for name in (
        "query_units",
        "compute_income",
        "compute_noi",
        "compute_cap_rate",
        "osm_geocode",
        "web_search",
        "publish_memo",
        "ask_prediction_agent",
    ):
        payload = _call(client, "vacancy", name, {})
        assert _failed(payload), payload


def test_deal_query_units_reads_memory_vault(client: TestClient):
    put_memory_roll(
        "ada",
        {
            "property_name": "Hill",
            "as_of": "2024-01-31",
            "layout": "one_row",
            "geo_confidence": "high",
            "units": [
                {
                    "unit_id": "1",
                    "occupancy": "Occupied",
                    "in_place_rent": 1500,
                    "vacant": False,
                    "sqft": 700,
                },
                {
                    "unit_id": "2",
                    "occupancy": "Vacant",
                    "in_place_rent": 0,
                    "vacant": True,
                    "sqft": 500,
                },
            ],
        },
    )
    payload = _call(client, "deal", "query_units", {"username": "ada"})
    assert "error" not in payload
    result = payload["result"]
    assert result.get("isError") is not True
    text = result["content"][0]["text"]
    body = json.loads(text)
    assert body["unit_count"] == 2
    assert body["vacant_count"] == 1
    assert body["property_name"] == "Hill"


def test_single_mcp_route_lists_the_union(client: TestClient):
    headers = _session(client, "/mcp")
    data = _rpc(client, "/mcp", "tools/list", None, 1, headers)
    tools = (data.get("result") or {}).get("tools") or []
    names = {str(t.get("name")) for t in tools if isinstance(t, dict)}
    assert names == set(DEAL_TOOLS) | set(VACANCY_TOOLS)


def _listed_names(client: TestClient, role: str | None) -> set[str]:
    role_headers = {"X-MCP-Role": role} if role else None
    headers = _session(client, "/mcp", role_headers)
    data = _rpc(client, "/mcp", "tools/list", None, 1, headers)
    tools = (data.get("result") or {}).get("tools") or []
    return {str(t.get("name")) for t in tools if isinstance(t, dict)}


def test_deal_role_header_lists_only_deal_tools(client: TestClient):
    assert _listed_names(client, "deal") == set(DEAL_TOOLS)


def test_vacancy_role_header_lists_only_vacancy_tools(client: TestClient):
    assert _listed_names(client, "vacancy") == set(VACANCY_TOOLS)


def test_unknown_role_header_lists_the_union(client: TestClient):
    assert _listed_names(client, "intern") == set(DEAL_TOOLS) | set(VACANCY_TOOLS)


def test_role_header_does_not_authorize_cross_role_calls(client: TestClient):
    # The header filters tools/list only. tools/call still needs a valid
    # route argument; a deal header cannot run a vacancy-role tool.
    headers = _session(client, "/mcp", {"X-MCP-Role": "deal"})
    response = _post(
        client,
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "fit_vacancy", "arguments": {"route": "deal", "plans": []}},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json().get("result") or {}
    assert result.get("isError") is not True
    body = json.loads(result["content"][0]["text"])
    assert body["ok"] is False
    assert "unknown tool" in body["error"]


def test_single_mcp_route_call_requires_a_known_route(client: TestClient):
    headers = _session(client, "/mcp")
    response = _post(
        client,
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "query_units", "arguments": {"username": "ada"}},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json().get("result") or {}
    assert result.get("isError") is not True
    body = json.loads(result["content"][0]["text"])
    assert body["ok"] is False
    assert "route must be one of deal, vacancy" in body["error"]


def test_single_mcp_route_runs_tool_for_its_role(client: TestClient):
    put_memory_roll(
        "ada",
        {
            "property_name": "Hill",
            "as_of": "2024-01-31",
            "layout": "one_row",
            "geo_confidence": "high",
            "units": [
                {
                    "unit_id": "1",
                    "occupancy": "Occupied",
                    "in_place_rent": 1500,
                    "vacant": False,
                    "sqft": 700,
                },
                {
                    "unit_id": "2",
                    "occupancy": "Vacant",
                    "in_place_rent": 0,
                    "vacant": True,
                    "sqft": 500,
                },
            ],
        },
    )
    headers = _session(client, "/mcp")
    response = _post(
        client,
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "query_units",
                "arguments": {"username": "ada", "route": "deal"},
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json().get("result") or {}
    assert result.get("isError") is not True
    body = json.loads(result["content"][0]["text"])
    assert body["unit_count"] == 2
    assert body["property_name"] == "Hill"


def test_single_mcp_route_rejects_cross_role_tools(client: TestClient):
    headers = _session(client, "/mcp")
    response = _post(
        client,
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "query_units",
                "arguments": {"username": "ada", "route": "vacancy"},
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json().get("result") or {}
    assert result.get("isError") is not True
    body = json.loads(result["content"][0]["text"])
    assert body["ok"] is False
    assert "unknown tool: query_units" in body["error"]


def test_vacancy_fit_roundtrip_on_its_path(client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setenv("VACANCY_FIT_DIR", str(tmp_path))
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT", raising=False)
    from capabilities_gateway.vacancy_math.tools import reset_store

    reset_store()
    plans = [
        {"plan": "A1", "renovated": 0, "units": 4, "vacant": 1},
        {"plan": "B2", "renovated": 1, "units": 4, "vacant": 3},
    ]
    fitted = _call(client, "vacancy", "fit_vacancy", {"plans": plans})
    assert fitted.get("error") is None
    model_text = fitted["result"]["content"][0]["text"]
    model = json.loads(model_text)
    assert model["reference_plan"]
    assert all("probability" not in group for group in model["groups"])
    for group in model["groups"]:
        group["probability"] = 0.99
    saved = _call(
        client,
        "vacancy",
        "save_fit",
        {"property_name": "Hill", "as_of": "2024-01-31", "model": model},
    )
    assert json.loads(saved["result"]["content"][0]["text"])["saved"] is True
    written = json.loads((tmp_path / "hill.json").read_text(encoding="utf-8"))
    assert all("probability" not in group for group in written["groups"])
    loaded = _call(client, "vacancy", "load_fit", {"property_name": "Hill"})
    catalog = json.loads(loaded["result"]["content"][0]["text"])
    assert "probability" not in catalog
    assert "A1" in catalog["plan_keys"]
    scored = _call(
        client,
        "vacancy",
        "score_vacancy",
        {"building": "Hill", "plan": "A1", "renovated": 0},
    )
    score = json.loads(scored["result"]["content"][0]["text"])
    assert "probability" in score
    assert score["probability"] != 0.99
    reset_store()
