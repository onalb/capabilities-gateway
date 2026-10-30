"""Shared checklist tools, per role (route=deal / route=vacancy)."""

from __future__ import annotations

import json

import pytest

from test_allowlist import _call

ROUTES = ("deal", "vacancy")


def _body(client, path: str, name: str, arguments: dict) -> dict:
    payload = _call(client, path, name, arguments)
    assert payload.get("error") is None, payload
    result = payload["result"]
    assert result.get("isError") is not True, result
    return json.loads(result["content"][0]["text"])


def _pair(path: str) -> tuple[str, str, str]:
    if path.endswith("/deal"):
        return (
            "1. [in_progress] query_units\n2. [pending] compute_income",
            "query_units",
            "compute_income",
        )
    return (
        "1. [in_progress] load_fit\n2. [pending] score_vacancy",
        "load_fit",
        "score_vacancy",
    )


@pytest.mark.parametrize("path", ROUTES)
def test_create_then_reject_second_create(client, path):
    tasks, first, _second = _pair(path)
    created = _body(client, path, "create_plan", {"tasks": tasks})
    assert created["ok"] is True
    assert created["rejected"] is False
    assert [row["text"] for row in created["checklist"]] == [first, _second]
    again = _body(
        client,
        path,
        "create_plan",
        {"tasks": "1. something else", "checklist": created["checklist"]},
    )
    assert again["ok"] is False
    assert again["rejected"] is True
    assert again["checklist"] == created["checklist"]
    assert "update_plan" in again["text"]


@pytest.mark.parametrize("path", ROUTES)
def test_update_keeps_completed_rows_and_demotes_terminal_new_rows(client, path):
    tasks, first, second = _pair(path)
    created = _body(client, path, "create_plan", {"tasks": tasks})
    marked = _body(
        client,
        path,
        "update_plan_status",
        {
            "tasks": f"1. [completed] {first}\n2. [in_progress] {second}",
            "checklist": created["checklist"],
            "last_work_tool": first,
            "last_work_status": "ok",
        },
    )
    assert marked["ok"] is True
    assert [row["status"] for row in marked["checklist"]] == ["completed", "in_progress"]
    replaced = _body(
        client,
        path,
        "update_plan",
        {
            "tasks": (
                f"1. [completed] {first}\n"
                "2. [completed] brand new step\n"
                "3. [incomplete] also new\n"
                f"4. [in_progress] follow up {second}"
            ),
            "checklist": marked["checklist"],
        },
    )
    assert replaced["ok"] is True
    rows = replaced["checklist"]
    assert rows[0] == {"text": first, "status": "completed"}
    assert sum(1 for row in rows if row["text"] == first) == 1
    fresh = next(row for row in rows if row["text"] == "brand new step")
    assert fresh["status"] == "pending"
    also = next(row for row in rows if row["text"] == "also new")
    assert also["status"] == "pending"
    assert any(row["status"] == "in_progress" and second in row["text"] for row in rows)


@pytest.mark.parametrize("path", ROUTES)
def test_status_rejected_with_no_prior_work_tool(client, path):
    """A second status call with no intervening work tool is rejected.

    The first status call is still allowed when no work tool has run. That is
    the deal rule. The app reports it with status_since_work.
    """
    tasks, first, second = _pair(path)
    created = _body(client, path, "create_plan", {"tasks": tasks})
    first_status = _body(
        client,
        path,
        "update_plan_status",
        {
            "tasks": f"1. [completed] {first}\n2. [in_progress] {second}",
            "checklist": created["checklist"],
            "last_work_tool": "",
            "last_work_status": "",
            "status_since_work": False,
        },
    )
    assert first_status["ok"] is True
    assert first_status["checklist"][0]["status"] == "completed"
    blocked = _body(
        client,
        path,
        "update_plan_status",
        {
            "tasks": f"1. [completed] {first}\n2. [completed] {second}",
            "checklist": first_status["checklist"],
            "last_work_tool": "",
            "last_work_status": "",
            "status_since_work": True,
        },
    )
    assert blocked["ok"] is False
    assert blocked["rejected"] is True
    assert blocked["reason"] == "consecutive_status"
    assert blocked["checklist"] == first_status["checklist"]
    assert "update_plan_status" in blocked["text"]


@pytest.mark.parametrize("path", ROUTES)
def test_status_rejected_when_the_list_is_wholly_new(client, path):
    tasks, first, second = _pair(path)
    created = _body(client, path, "create_plan", {"tasks": tasks})
    blocked = _body(
        client,
        path,
        "update_plan_status",
        {
            "tasks": "1. [completed] an entirely different step",
            "checklist": created["checklist"],
            "last_work_tool": first,
            "last_work_status": "ok",
        },
    )
    assert blocked["ok"] is False
    assert blocked["rejected"] is True
    assert blocked["reason"] == "new_list"
    assert [row["text"] for row in blocked["checklist"]] == [first, second]
    assert "update_plan" in blocked["text"]


@pytest.mark.parametrize("path", ROUTES)
def test_reflection_does_not_change_the_checklist(client, path):
    tasks, _first, _second = _pair(path)
    created = _body(client, path, "create_plan", {"tasks": tasks})
    reflected = _body(
        client,
        path,
        "reflection",
        {
            "analysis": "the next step is still open",
            "need_replan": True,
            "checklist": created["checklist"],
        },
    )
    assert reflected["ok"] is True
    assert reflected["rejected"] is False
    assert reflected["need_replan"] is True
    assert reflected["checklist"] == created["checklist"]
    assert "score_gcr" not in reflected["text"]


def test_score_gcr_is_not_a_gateway_tool(client):
    from test_allowlist import _tool_names

    for path in ROUTES:
        assert "score_gcr" not in _tool_names(client, path)


def test_update_plan_seeds_checklist_when_empty_on_deal_route(client):
    """Planless escape hatch: with no checklist, update_plan with a numbered
    list seeds it (deal route) instead of demanding create_plan."""
    seeded = _body(
        client,
        "deal",
        "update_plan",
        {"tasks": "1. [in_progress] query_units\n2. [pending] compute_income"},
    )
    assert seeded["ok"] is True
    assert seeded["rejected"] is False
    assert seeded["reason"] == "seeded"
    assert [row["text"] for row in seeded["checklist"]] == [
        "query_units",
        "compute_income",
    ]


def test_update_plan_empty_tasks_with_no_checklist_still_rejected(client):
    blocked = _body(
        client,
        "deal",
        "update_plan",
        {"tasks": ""},
    )
    assert blocked["ok"] is False
    assert blocked["rejected"] is True
    assert blocked["reason"] == "no_checklist"
    assert "create_plan" in blocked["text"]


def test_update_plan_no_checklist_still_rejected_on_vacancy_route(client):
    """The vacancy route keeps the old rule: no checklist → create_plan first."""
    blocked = _body(
        client,
        "vacancy",
        "update_plan",
        {"tasks": "1. [in_progress] load_fit"},
    )
    assert blocked["ok"] is False
    assert blocked["rejected"] is True
    assert blocked["reason"] == "no_checklist"
    assert "create_plan" in blocked["text"]
