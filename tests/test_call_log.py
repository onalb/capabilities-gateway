"""Each tools/call prints one stdout line: path, tool, ok or error."""

from __future__ import annotations

import base64

from starlette.testclient import TestClient

from tests.test_allowlist import _call
from capabilities_gateway.deal.vault import put_memory_roll


def _tool_lines(captured: str) -> list[str]:
    return [line for line in captured.splitlines() if line.startswith("TOOL ")]


def test_deal_tool_call_emits_ok_line(client: TestClient, capsys):
    put_memory_roll(
        "ada",
        {
            "property_name": "Hill",
            "as_of": "2024-01-31",
            "layout": "one_row",
            "units": [
                {"unit_id": "1", "occupancy": "Occupied", "in_place_rent": 1500, "vacant": False},
            ],
        },
    )
    capsys.readouterr()
    payload = _call(
        client,
        "/mcp/deal",
        "query_units",
        {"username": "ada", "occupancy": "Occupied"},
    )
    assert payload.get("error") is None
    lines = _tool_lines(capsys.readouterr().out)
    assert lines == ["TOOL identity=cre_deal_rentroll_wli tool=query_units status=ok"]
    assert "ada" not in lines[0]
    assert "1500" not in lines[0]


def test_rejected_tool_call_emits_error_line(client: TestClient, capsys):
    capsys.readouterr()
    payload = _call(client, "/mcp/deal", "fit_vacancy", {"plans": [{"plan": "A1"}]})
    assert payload.get("result", {}).get("isError") is True or payload.get("error")
    lines = _tool_lines(capsys.readouterr().out)
    assert lines == ["TOOL identity=cre_deal_rentroll_wli tool=fit_vacancy status=error"]
    assert "A1" not in lines[0]


def test_tool_call_summary_omits_bytes_names_and_secrets(client: TestClient, capsys):
    question = (
        "What occupancy do you predict for jane.resident@example.com "
        "at 555-867-5309 " + ("west wing " * 30)
    )
    raw = b"RESIDENT_NAME_LEAK_BYTES_9f3a"
    capsys.readouterr()
    _call(
        client,
        "/mcp/vacancy",
        "parse_rent_roll_file",
        {
            "file_id": "roll-42",
            "filename": "Jane Resident.xlsx",
            "content_base64": base64.b64encode(raw).decode("ascii"),
            "question": question,
            "body": "resident secret body",
            "property_name": "Hill",
            "floor_plan": "1x1",
        },
    )
    lines = _tool_lines(capsys.readouterr().out)
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith(
        'TOOL identity=cre_vacancy_wli tool=parse_rent_roll_file status='
    )
    assert 'property="Hill"' in line
    assert 'plan="1x1"' in line
    assert 'file_id="roll-42"' in line
    assert "question=" in line
    assert "jane.resident@example.com" not in line
    assert "555-867-5309" not in line
    assert "555" not in line
    assert "Jane Resident" not in line
    assert "RESIDENT_NAME_LEAK" not in line
    assert "resident secret body" not in line
    assert "west wing west wing west wing west wing west wing west wing" not in line
    question_value = line.split('question="', 1)[1].rstrip('"')
    assert len(question_value) <= 80
    assert question_value.startswith("What occupancy do you predict for redacted")
