"""Real deal tools live here: vault math and the prediction forward."""

from __future__ import annotations

import json

import pytest

from capabilities_gateway.deal.predict import (
    build_forecast_question,
    forecast,
    looks_like_clarification,
    reset_predict_state,
)
from capabilities_gateway.deal.tools import (
    ask_prediction_agent,
    compute_income,
    query_units,
)
from capabilities_gateway.deal.vault import put_memory_roll
from capabilities_gateway.vacancy_math.store import DirectoryFitStore
from capabilities_gateway.vacancy_math.tools import reset_store


@pytest.fixture(autouse=True)
def _isolate_fits(tmp_path, monkeypatch):
    monkeypatch.setenv("VACANCY_FIT_DIR", str(tmp_path))
    reset_store()
    yield
    reset_store()


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
    assert "Call load_fit with that name" in question
    assert "say La Cordoba is not trained" in question
    assert "1x1 B" not in question
    assert "do not parse" in question.lower()
    assert "what occupancy do you predict for la cordoba?" in question.lower()
    assert "/api/chat" not in seen["url"]
    assert seen["arguments"]["session_id"]
    # The vault roll never rides along: the vacancy app answers from its
    # trained store only, same as its own UI.
    assert "plan_table" not in seen["arguments"]


def test_ask_prediction_agent_untrained_building_gets_the_not_trained_prompt(monkeypatch):
    reset_predict_state()
    seen: dict = {}

    def fake_call(url, name, arguments, client_name="x"):
        seen["arguments"] = arguments
        return "Hill is not trained."

    monkeypatch.setenv("VACANCY_MCP_URL", "https://vacancy-agent.example.test/mcp")
    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", fake_call)
    put_memory_roll(
        "ada",
        {
            "property_name": "Hill",
            "as_of": "2021-05-25",
            "layout": "one_row",
            "units": [
                {"unit_id": "a1", "unit_type": "1x1", "occupancy": "Occupied", "vacant": False},
                {"unit_id": "a2", "unit_type": "1x1", "occupancy": "Vacant", "vacant": True},
                {"unit_id": "b1", "unit_type": "1x1 Reno", "occupancy": "Occupied", "vacant": False},
                {"unit_id": "m1", "unit_type": "Model", "occupancy": "Model", "vacant": True},
            ],
        },
    )
    body = json.loads(
        ask_prediction_agent(
            question="Which floor plan is more likely vacant?",
            username="ada",
        )
    )
    assert body["ok"] is True
    # Never a plan_table: the vacancy app answers from its trained store.
    assert "plan_table" not in seen["arguments"]
    prompt = seen["arguments"]["question"]
    assert "The question names Hill" in prompt
    assert "say Hill is not trained" in prompt
    assert "transiently" not in prompt
    assert "must not call save_fit" not in prompt


def test_ask_prediction_agent_untrained_spoken_vault_prefix_gets_not_trained_prompt(monkeypatch):
    reset_predict_state()
    seen: dict = {}

    def fake_call(url, name, arguments, client_name="x"):
        seen["arguments"] = arguments
        return "Bay View Gardens Apartments is not trained."

    monkeypatch.setenv("VACANCY_MCP_URL", "https://vacancy-agent.example.test/mcp")
    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", fake_call)
    put_memory_roll(
        "ada",
        {
            "property_name": "Bay View Gardens Apartments-20210930-040414 - 250",
            "as_of": "2021-05-25",
            "layout": "one_row",
            "units": [
                {"unit_id": "1", "unit_type": "1x1", "occupancy": "Occupied", "vacant": False},
                {"unit_id": "2", "unit_type": "1x1", "occupancy": "Vacant", "vacant": True},
            ],
        },
    )
    body = json.loads(
        ask_prediction_agent(
            question="What's the predicted vacancy for Bay View Gardens Apartments?",
            username="ada",
        )
    )
    assert body["ok"] is True
    assert "plan_table" not in seen["arguments"]
    prompt = seen["arguments"]["question"]
    assert "The question names Bay View Gardens Apartments" in prompt
    assert "say Bay View Gardens Apartments is not trained" in prompt
    assert "Score occupancy for Bay View Gardens Apartments" not in prompt


def test_ask_prediction_agent_trained_building_scores_from_the_saved_fit(tmp_path, monkeypatch):
    reset_predict_state()
    seen: dict = {}

    def fake_call(url, name, arguments, client_name="x"):
        seen["arguments"] = arguments
        return "Which floor plan? 1x1 or 2x1"

    monkeypatch.setenv("VACANCY_MCP_URL", "https://vacancy-agent.example.test/mcp")
    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", fake_call)
    DirectoryFitStore(tmp_path).save(
        {"property": "Bay View Gardens Apartments", "as_of": "2021-05-25", "groups": []}
    )
    reset_store()
    put_memory_roll(
        "ada",
        {
            "property_name": "Bay View Gardens Apartments-20210930-040414 - 250",
            "as_of": "2021-09-30",
            "layout": "one_row",
            "units": [
                {"unit_id": "1", "unit_type": "1", "occupancy": "Occupied", "vacant": False},
                {"unit_id": "2", "unit_type": "2", "occupancy": "Vacant", "vacant": True},
            ],
        },
    )
    body = json.loads(
        ask_prediction_agent(
            question="What occupancy do you predict for Bay View Gardens Apartments?",
            username="ada",
        )
    )
    assert body["ok"] is True
    assert "plan_table" not in seen["arguments"]
    assert "Score occupancy for Bay View Gardens Apartments" in seen["arguments"]["question"]


def test_ask_prediction_agent_skips_plan_table_for_another_building(monkeypatch):
    reset_predict_state()
    seen: dict = {}

    def fake_call(url, name, arguments, client_name="x"):
        seen["arguments"] = arguments
        return "Bay View is not trained."

    monkeypatch.setenv("VACANCY_MCP_URL", "https://vacancy-agent.example.test/mcp")
    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", fake_call)
    put_memory_roll(
        "ada",
        {
            "property_name": "Hill",
            "as_of": "2021-05-25",
            "layout": "one_row",
            "units": [
                {"unit_id": "1", "unit_type": "1x1", "occupancy": "Occupied", "vacant": False},
            ],
        },
    )
    body = json.loads(
        ask_prediction_agent(
            question="What occupancy do you predict for Bay View?",
            username="ada",
        )
    )
    assert body["ok"] is True
    # A different building keeps today's trained-store behavior.
    assert "plan_table" not in seen["arguments"]
    assert "The question names Bay View" in seen["arguments"]["question"]
    assert "Call load_fit with that name" in seen["arguments"]["question"]


def test_ask_prediction_agent_without_a_roll_sends_no_plan_table(monkeypatch):
    reset_predict_state()
    seen: dict = {}

    def fake_call(url, name, arguments, client_name="x"):
        seen["arguments"] = arguments
        return "no properties are trained yet"

    monkeypatch.setenv("VACANCY_MCP_URL", "https://vacancy-agent.example.test/mcp")
    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", fake_call)
    body = json.loads(
        ask_prediction_agent(
            question="What occupancy do you predict?",
            username="nobody",
        )
    )
    assert body["ok"] is True
    assert "plan_table" not in seen["arguments"]
    assert "list_trained_properties" in seen["arguments"]["question"]


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
    first = forecast("tester", "What occupancy do you predict?", vault={"property_name": "Fixture Towers"}, trained=True)
    second = forecast("tester", "Plan A")
    assert "Which floor plan?" in first["answer"]
    assert "0.12" in second["answer"]
    assert "Score occupancy for Fixture Towers" in prompts[0]
    assert prompts[1] == "Plan A"
    assert ids[0] == ids[1]


def test_aggregate_plan_label_is_a_clarification():
    text = (
        'Your label ("average of the 1x1 renovated and 2x1 renovated plans") '
        "covers more than one saved group — I can't score an aggregate label "
        "directly. Which would you like me to score? Pick one exact plan_key."
    )
    assert looks_like_clarification(text)
    assert not looks_like_clarification(
        "Predicted occupancy for 1x1 renovated is 21.4% as of 2021-05-25."
    )


def test_forecast_question_uses_vault_when_question_omits_the_building():
    unnamed = build_forecast_question(
        "What occupancy do you predict?",
        vault={
            "property_name": "La Cordoba",
            "as_of": "2024-06-01",
            "unit_count": 164,
            "occupancy_pct": 0.92,
            "vacant_count": 13,
        },
        trained=True,
    )
    assert "Score occupancy for La Cordoba as of 2024-06-01" in unnamed
    assert "for La Cordoba" in unnamed
    named = build_forecast_question(
        "What occupancy do you predict for La Cordoba?",
        vault={"property_name": "La Cordoba", "as_of": "2024-06-01", "unit_count": 164, "occupancy_pct": 0.92, "vacant_count": 13},
        trained=True,
    )
    assert "Score occupancy for La Cordoba as of 2024-06-01" in named
    assert "unit_count=164" in named


def test_forecast_question_strips_vault_filename_suffix():
    prompt = build_forecast_question(
        "What occupancy do you predict for Bay View Gardens Apartments-20210930-040414 - 250?",
        vault={
            "property_name": "Bay View Gardens Apartments-20210930-040414 - 250",
            "as_of": "2021-09-30",
            "unit_count": 250,
            "occupancy_pct": 0.9,
            "vacant_count": 25,
        },
        trained=True,
    )
    assert "Score occupancy for Bay View Gardens Apartments as of 2021-09-30" in prompt
    assert "Score occupancy for Bay View Gardens Apartments-20210930" not in prompt


def test_forecast_question_loads_a_building_that_is_not_the_vault():
    prompt = build_forecast_question(
        "What occupancy do you predict for LA Cordoba?",
        vault={
            "property_name": "Chambers Hill Elementary School-20231024-180834 - 252",
            "as_of": "2023-10-24",
            "unit_count": 252,
            "occupancy_pct": 0.8849,
            "vacant_count": 29,
        },
    )
    assert "The question names LA Cordoba" in prompt
    assert "Call load_fit with that name" in prompt
    assert "list_trained_properties" in prompt
    assert "no properties are trained yet" in prompt
    assert "no building is named" not in prompt.lower()
    assert "Chambers Hill" not in prompt
    assert "0.8849" not in prompt
    assert "What occupancy do you predict for LA Cordoba?" in prompt


def test_forecast_strips_skill_narration(monkeypatch):
    reset_predict_state()

    def fake_call(url, name, arguments, client_name="x"):
        return (
            "I loaded the vacancy skill. LA Cordoba is not trained. "
            "No properties are trained yet."
        )

    monkeypatch.setenv("VACANCY_MCP_URL", "https://vacancy-agent.example.test/mcp")
    monkeypatch.setattr("capabilities_gateway.deal.forward.call_tool", fake_call)
    body = forecast("ada", "What occupancy do you predict for LA Cordoba?")
    assert body["answer"] == "LA Cordoba is not trained. No properties are trained yet."
    assert body["awaiting_followup"] is True
