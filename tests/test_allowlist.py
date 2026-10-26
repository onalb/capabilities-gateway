"""Allowlist is the route: /mcp/deal and /mcp/vacancy."""

from __future__ import annotations

import json

from starlette.testclient import TestClient

from capabilities_gateway.deal.vault import put_memory_roll

DEAL_TOOLS = {
    "query_units",
    "compute_income",
    "compute_noi",
    "compute_cap_rate",
    "osm_geocode",
    "web_search",
    "publish_memo",
    "ask_vacancy_agent",
    "ask_prediction_agent",
}
VACANCY_TOOLS = {
    "parse_rent_roll_file",
    "fit_vacancy",
    "load_fit",
    "save_fit",
    "score_vacancy",
}

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


def _session(client: TestClient, path: str) -> dict[str, str]:
    opened = _post(client, path, _INIT)
    assert opened.status_code == 200, opened.text
    assert opened.status_code not in {301, 302, 303, 307, 308}
    assert opened.history == []
    sid = opened.headers.get("mcp-session-id")
    extra = {"Mcp-Session-Id": sid} if sid else {}
    noted = _post(
        client,
        path,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=extra,
    )
    assert noted.status_code not in {301, 302, 303, 307, 308}
    return extra


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


def _tool_names(client: TestClient, path: str) -> set[str]:
    headers = _session(client, path)
    data = _rpc(client, path, "tools/list", {}, 2, headers)
    tools = ((data.get("result") or {}).get("tools")) or []
    return {str(item.get("name")) for item in tools}


def _call(client: TestClient, path: str, name: str, arguments: dict) -> dict:
    headers = _session(client, path)
    return _rpc(
        client,
        path,
        "tools/call",
        {"name": name, "arguments": arguments},
        3,
        headers,
    )


def _failed(payload: dict) -> bool:
    if payload.get("error"):
        return True
    result = payload.get("result") or {}
    if result.get("isError"):
        return True
    text = json.dumps(result).lower()
    return "unknown tool" in text or "not found" in text or "invalid" in text


def test_paths_do_not_redirect(client: TestClient):
    for path in ("/mcp/deal", "/mcp/vacancy"):
        response = _post(client, path, _INIT)
        assert response.status_code == 200
        assert response.is_redirect is False
        assert response.headers.get("location") is None


def test_deal_lists_only_deal_tools(client: TestClient):
    assert _tool_names(client, "/mcp/deal") == DEAL_TOOLS


def test_vacancy_lists_only_vacancy_tools(client: TestClient):
    assert _tool_names(client, "/mcp/vacancy") == VACANCY_TOOLS


def test_deal_caller_cannot_fit_or_save(client: TestClient):
    for name in ("parse_rent_roll_file", "fit_vacancy", "load_fit", "save_fit", "score_vacancy"):
        payload = _call(client, "/mcp/deal", name, {})
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
        "ask_vacancy_agent",
        "ask_prediction_agent",
    ):
        payload = _call(client, "/mcp/vacancy", name, {})
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
    payload = _call(client, "/mcp/deal", "query_units", {"username": "ada"})
    assert "error" not in payload
    result = payload["result"]
    assert result.get("isError") is not True
    text = result["content"][0]["text"]
    body = json.loads(text)
    assert body["unit_count"] == 2
    assert body["vacant_count"] == 1
    assert body["property_name"] == "Hill"


def test_vacancy_fit_roundtrip_on_its_path(client: TestClient, tmp_path, monkeypatch):
    monkeypatch.setenv("VACANCY_FIT_DIR", str(tmp_path))
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT", raising=False)
    from capabilities_gateway.vacancy_math.tools import reset_store

    reset_store()
    plans = [
        {"plan": "A1", "renovated": 0, "units": 4, "vacant": 1},
        {"plan": "B2", "renovated": 1, "units": 4, "vacant": 3},
    ]
    fitted = _call(client, "/mcp/vacancy", "fit_vacancy", {"plans": plans})
    assert fitted.get("error") is None
    model_text = fitted["result"]["content"][0]["text"]
    model = json.loads(model_text)
    assert model["reference_plan"]
    saved = _call(
        client,
        "/mcp/vacancy",
        "save_fit",
        {"property_name": "Hill", "as_of": "2024-01-31", "model": model},
    )
    assert json.loads(saved["result"]["content"][0]["text"])["saved"] is True
    loaded = _call(client, "/mcp/vacancy", "load_fit", {"property_name": "Hill"})
    catalog = json.loads(loaded["result"]["content"][0]["text"])
    assert "probability" not in catalog
    assert "A1" in catalog["plan_keys"]
    scored = _call(
        client,
        "/mcp/vacancy",
        "score_vacancy",
        {"building": "Hill", "plan": "A1", "renovated": 0},
    )
    score = json.loads(scored["result"]["content"][0]["text"])
    assert "probability" in score
    reset_store()
