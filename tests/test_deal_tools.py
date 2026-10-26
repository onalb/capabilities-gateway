"""Real deal tools live here: vault math, floor-plan vacancy, prediction forward."""

from __future__ import annotations

import json

from capabilities_gateway.deal.predict import (
    build_forecast_question,
    forecast,
    reset_predict_state,
)
from capabilities_gateway.deal.tools import (
    ask_prediction_agent,
    ask_vacancy_agent,
    compute_income,
    query_units,
)
from capabilities_gateway.deal.vault import put_memory_roll


def _hill_roll() -> dict:
    occupied = [
        {
            "unit_id": str(i),
            "occupancy": "Occupied",
            "in_place_rent": 800,
            "vacant": False,
            "sqft": 700 if i < 2 else None,
        }
        for i in range(151)
    ]
    vacant = [
        {
            "unit_id": f"v{i}",
            "occupancy": "Vacant",
            "in_place_rent": 0,
            "vacant": True,
            "sqft": 0,
        }
        for i in range(13)
    ]
    return {
        "property_name": "Hill",
        "as_of": "2024-01-31",
        "layout": "one_row",
        "units": occupied + vacant,
    }


def test_query_units_and_income_math_stay_on_the_gateway():
    put_memory_roll("ada", _hill_roll())
    body = json.loads(query_units(username="ada"))
    assert body["unit_count"] == 164
    assert body["occupied_count"] == 151
    assert body["vacant_count"] == 13
    assert body["occupancy_pct"] == round(151 / 164, 4)
    assert body["mtm_count"] == 0
    assert "complete in this result" in body["note"]
    income = json.loads(compute_income(username="ada"))
    assert income["in_place_monthly"] == 151 * 800
    assert income["estimated_full_occupancy_monthly"] == 164 * 800
    filled = json.loads(compute_income(vacant_fill_rent=5000, username="ada"))
    assert filled["vacant_fill_monthly"] == 13 * 5000
    assert filled["scenario_full_occupancy_annual"] == (151 * 800 + 13 * 5000) * 12


def test_query_units_avg_sqft_ignores_non_positive():
    put_memory_roll(
        "ada",
        {
            "property_name": "La Cordoba",
            "as_of": "2024-01-31",
            "layout": "one_row",
            "units": [
                {"unit_id": "1", "sqft": 700, "in_place_rent": 1000, "occupancy": "Occupied", "vacant": False},
                {"unit_id": "2", "sqft": 800, "in_place_rent": 1100, "occupancy": "Occupied", "vacant": False},
                {"unit_id": "3", "sqft": 0, "in_place_rent": 0, "occupancy": "Vacant", "vacant": True},
                {"unit_id": "4", "sqft": None, "in_place_rent": 900, "occupancy": "Occupied", "vacant": False},
            ],
        },
    )
    body = json.loads(query_units(username="ada"))
    assert body["avg_sqft"] == 750.0
    assert body["sqft_n"] == 2


def test_income_full_occupancy_uses_vacant_asking():
    put_memory_roll(
        "ada",
        {
            "property_name": "Bay",
            "as_of": "2024-01-31",
            "layout": "one_row",
            "units": [
                {"unit_id": "1", "in_place_rent": 1000, "occupancy": "Occupied", "vacant": False},
                {"unit_id": "2", "in_place_rent": 1000, "occupancy": "Occupied", "vacant": False},
                {
                    "unit_id": "3",
                    "in_place_rent": 0,
                    "occupancy": "Vacant",
                    "vacant": True,
                    "charge_codes": {"_market_rent": 1200},
                },
            ],
        },
    )
    income = json.loads(compute_income(username="ada"))
    assert income["in_place_monthly"] == 2000
    assert income["vacant_asking_monthly"] == 1200.0
    assert income["estimated_full_occupancy_monthly"] == 3200.0


def _plan_units() -> list[dict]:
    rows = [{"unit_id": f"a{i}", "unit_type": "1x1", "occupancy": "Occupied", "vacant": False} for i in range(40)]
    rows += [{"unit_id": f"b{i}", "unit_type": "1x1", "occupancy": "Vacant", "vacant": True} for i in range(2)]
    rows += [{"unit_id": f"c{i}", "unit_type": "1x1 Reno", "occupancy": "Occupied", "vacant": False} for i in range(12)]
    rows += [{"unit_id": f"d{i}", "unit_type": "1x1 Reno", "occupancy": "Vacant", "vacant": True} for i in range(6)]
    return rows


def test_ask_vacancy_agent_scores_the_emptier_plan_higher():
    put_memory_roll(
        "ada",
        {
            "property_name": "Hill",
            "as_of": "2021-05-25",
            "layout": "one_row",
            "units": _plan_units(),
        },
    )
    out = json.loads(ask_vacancy_agent(username="ada"))
    by = {row["plan"]: row["probability"] for row in out["plans"]}
    assert out["agent"] == "vacancy"
    assert out["steps"] == ["fit_vacancy_model"]
    assert by["1x1 Reno"] > by["1x1"]
    one = json.loads(ask_vacancy_agent(floor_plan="1x1 Reno", username="ada"))
    assert [row["plan"] for row in one["plans"]] == ["1x1 Reno"]


def test_ask_prediction_agent_posts_vacancy_ask_vacancy(monkeypatch):
    reset_predict_state()
    seen: dict = {}

    def fake_call(url, name, arguments, client_name="x"):
        seen["url"] = url
        seen["name"] = name
        seen["arguments"] = arguments
        return "building not trained"

    monkeypatch.setenv("VACANCY_MCP_URL", "https://vacancy-agent.example.test/mcp")
    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", fake_call)
    put_memory_roll(
        "ada",
        {
            "property_name": "La Cordoba",
            "as_of": "2024-06-01",
            "layout": "one_row",
            "units": [
                {"unit_id": "1", "unit_type": "1x1 B", "occupancy": "Occupied", "in_place_rent": 1000, "vacant": False},
            ],
        },
    )
    body = json.loads(
        ask_prediction_agent(
            question="What occupancy do you predict?",
            horizon_months=12,
            username="ada",
        )
    )
    assert body["ok"] is True
    assert body["answer"] == "building not trained"
    assert body["awaiting_followup"] is True
    assert seen["url"] == "https://vacancy-agent.example.test/mcp"
    assert seen["name"] == "ask_vacancy"
    question = seen["arguments"]["question"]
    assert "La Cordoba" not in question
    assert "1x1 B" not in question
    assert "do not parse" in question.lower()
    assert "what occupancy do you predict?" in question.lower()
    assert "/api/chat" not in seen["url"]
    assert seen["arguments"]["session_id"]


def test_prediction_followup_reuses_session_and_raw_text(monkeypatch):
    reset_predict_state()
    prompts: list[str] = []
    ids: list[str] = []

    def fake_call(url, name, arguments, client_name="x"):
        prompts.append(arguments["question"])
        ids.append(arguments["session_id"])
        if len(prompts) == 1:
            return "Which floor plan? • Plan A\n• Plan B"
        return "Plan A is vacant with probability 0.12."

    monkeypatch.setenv("VACANCY_MCP_URL", "https://vacancy-agent.example.test/mcp")
    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", fake_call)
    first = forecast("tester", "What occupancy do you predict?", vault={"property_name": "Fixture Towers"})
    second = forecast("tester", "Plan A")
    assert "Which floor plan?" in first["answer"]
    assert "0.12" in second["answer"]
    assert "Fixture Towers" not in prompts[0]
    assert prompts[1] == "Plan A"
    assert ids[0] == ids[1]


def test_forecast_question_keeps_a_named_property_only():
    unnamed = build_forecast_question(
        "What occupancy do you predict?",
        vault={"property_name": "La Cordoba", "as_of": "2024-06-01", "unit_count": 164},
    )
    assert "La Cordoba" not in unnamed
    named = build_forecast_question(
        "What occupancy do you predict for La Cordoba?",
        vault={"property_name": "La Cordoba", "as_of": "2024-06-01", "unit_count": 164, "occupancy_pct": 0.92, "vacant_count": 13},
    )
    assert "Score occupancy for La Cordoba as of 2024-06-01" in named
    assert "unit_count=164" in named
