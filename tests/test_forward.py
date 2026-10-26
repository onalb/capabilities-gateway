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
    text = forward_ask_vacancy("score A1 at Hill", "sess-1")
    assert text.startswith("A1 is 25%")
    assert seen["url"] == "https://vacancy-agent.example.test/mcp"
    assert seen["name"] == "ask_vacancy"
    assert seen["arguments"]["session_id"] == "sess-1"
    assert seen["client_name"] == "capabilities-gateway-deal"


def test_forward_refuses_deal_and_vacancy_gateway_paths(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("must not call the gateway")

    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", boom)
    for url in (
        "http://127.0.0.1:8010/mcp/deal",
        "http://127.0.0.1:8010/mcp/vacancy",
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
