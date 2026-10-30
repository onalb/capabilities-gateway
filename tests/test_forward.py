"""Vacancy answer forwards to the vacancy app and refuses to call this gateway."""

from capabilities_gateway.deal.forward import forward_ask_vacancy


def test_forward_posts_ask_vacancy_to_vacancy_mcp(monkeypatch):
    seen = {}

    def fake_call(url, name, arguments, client_name="x"):
        seen["url"] = url
        seen["name"] = name
        seen["arguments"] = arguments
        seen["client_name"] = client_name
        return "A1 is 25% vacant as of 2024-01-31."

    monkeypatch.setenv(
        "VACANCY_MCP_URL",
        "https://vacancy-agent.example.test/mcp",
    )
    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", fake_call)
    table = [
        {"plan": "A1", "renovated": 0, "units": 10, "vacant": 3},
        {"plan": "B2", "renovated": 0, "units": 8, "vacant": 1},
    ]
    text = forward_ask_vacancy("score A1 at Hill", "sess-1", plan_table=table)
    assert text.startswith("A1 is 25%")
    assert seen["url"] == "https://vacancy-agent.example.test/mcp"
    assert seen["name"] == "ask_vacancy"
    assert seen["arguments"]["session_id"] == "sess-1"
    assert seen["arguments"]["plan_table"] == table
    assert seen["client_name"] == "capabilities-gateway-deal"
    # No plan_table (a trained-building ask) sends only question + session_id.
    seen.clear()
    forward_ask_vacancy("score A1 at Hill", "sess-1")
    assert "plan_table" not in seen["arguments"]


def test_forward_refuses_gateway_urls(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("must not call the gateway")

    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", boom)
    for url in (
        "http://127.0.0.1:8010/mcp/deal",
        "http://127.0.0.1:8010/mcp/vacancy",
        "http://127.0.0.1:8010/mcp",
        "https://credealrentroll-25yvwacjrd.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
    ):
        monkeypatch.setenv("VACANCY_MCP_URL", url)
        text = forward_ask_vacancy("which plan", "sess")
        assert "Refusing" in text


def test_vacancy_math_module_does_not_forward_answers():
    import inspect

    from capabilities_gateway.vacancy_math import tools

    source = inspect.getsource(tools)
    assert "def ask_vacancy" not in source
    assert "forward_ask_vacancy" not in source
    assert "VACANCY_MCP_URL" not in source
    assert "/mcp/deal" not in source
