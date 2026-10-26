"""GET /skills serves markdown the deal harness can paste."""

EXPECTED = {
    "rent-roll-abstract",
    "citation-policy",
    "underwriting",
    "rr-predict",
    "vacancy",
}


def test_skill_index_and_body(client):
    listed = client.get("/skills")
    assert listed.status_code == 200
    names = set(listed.json()["skills"])
    assert EXPECTED <= names
    body = client.get("/skills/citation-policy")
    assert body.status_code == 200
    assert "text/markdown" in body.headers["content-type"]
    assert "citation-policy" in body.text
    missing = client.get("/skills/not-a-skill")
    assert missing.status_code == 404
    escaped = client.get("/skills/..%2F..%2Fetc")
    assert escaped.status_code == 404


def test_gateway_rent_roll_skill_names_ask_vacancy(client):
    text = client.get("/skills/rent-roll-abstract").text
    assert "ask_vacancy" in text
    assert "ask_vacancy_agent" not in text
    predict = client.get("/skills/rr-predict").text
    assert "/mcp/deal" in predict
    assert "forwards" in predict
