"""One MCP, two identities. Cedar permits are the tool allowlist.

The AgentCore gateway authenticates with AWS_IAM. Each app assumes the IAM
role named for its workload identity, and the permit matches that role.
"""

from __future__ import annotations

ACCOUNT = "226721156429"
REGION = "us-east-1"
GATEWAY_ID = "credealrentroll-25yvwacjrd"
GATEWAY_ARN = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:gateway/{GATEWAY_ID}"
TARGET = "cretools"

DEAL_IDENTITY = "cre_deal_rentroll_wli"
VACANCY_IDENTITY = "cre_vacancy_wli"
DEAL_ROLE = "CreDealRentrollWli"
VACANCY_ROLE = "CreVacancyWli"

CHECKLIST = frozenset(
    {"create_plan", "update_plan", "update_plan_status", "reflection"}
)
DEAL_TOOLS = frozenset(
    {
        "cre_ping",
        "query_units",
        "compute_income",
        "compute_noi",
        "compute_cap_rate",
        "osm_geocode",
        "web_search",
        "publish_memo",
        "ask_prediction_agent",
        *CHECKLIST,
    }
)
VACANCY_TOOLS = frozenset(
    {
        "parse_rent_roll_file",
        "fit_vacancy",
        "load_fit",
        "list_trained_properties",
        "save_fit",
        "delete_fit",
        "score_vacancy",
        *CHECKLIST,
    }
)

_DESCRIPTIONS = {
    "cre_ping": "Gateway health ping. Not a model tool.",
    "query_units": "Vault unit counts and occupancy for the injected username.",
    "compute_income": "In-place monthly income from the vault roll.",
    "compute_noi": "NOI from in-place income and optional expenses.",
    "compute_cap_rate": "Implied cap rate from ask price and NOI.",
    "osm_geocode": "Geocode a street address.",
    "web_search": "Web search for market context.",
    "publish_memo": "Publish a memo after the deal app sets hitl_allow.",
    "ask_prediction_agent": (
        "Forward a forecast or floor-plan vacancy question to the vacancy app "
        "ask_vacancy. The vacancy app answers from its trained store only."
    ),
    "parse_rent_roll_file": "Parse a rent-roll spreadsheet.",
    "fit_vacancy": "Fit a vacancy model from plan counts.",
    "load_fit": "Load a saved vacancy fit.",
    "list_trained_properties": "List properties that have a saved fit.",
    "save_fit": "Save a vacancy fit.",
    "delete_fit": "Delete a saved fit when confirm is true.",
    "score_vacancy": "Score one plan on a saved fit.",
    "create_plan": "Store this turn's checklist.",
    "update_plan": "Replace the remaining checklist items.",
    "update_plan_status": "Mark checklist rows completed or pending.",
    "reflection": "Store a short reflection on the checklist.",
}


def identity_for(route: str) -> str:
    return VACANCY_IDENTITY if route == "vacancy" else DEAL_IDENTITY


def role_for(route: str) -> str:
    return VACANCY_ROLE if route == "vacancy" else DEAL_ROLE


def tools_for(route: str) -> frozenset[str]:
    return VACANCY_TOOLS if route == "vacancy" else DEAL_TOOLS


def role_arn(role_name: str) -> str:
    return f"arn:aws:iam::{ACCOUNT}:role/{role_name}"


def caller_arn(role_name: str) -> str:
    """Cedar IAM entity id. The session name is stripped before evaluation."""
    return f"arn:aws:sts::{ACCOUNT}:assumed-role/{role_name}"


def cedar_statement(route: str) -> str:
    names = sorted(tools_for(route))
    actions = ",\n    ".join(f'AgentCore::Action::"{TARGET}___{name}"' for name in names)
    return (
        "permit(\n"
        f'  principal == AgentCore::IamEntity::"{caller_arn(role_for(route))}",\n'
        "  action in [\n"
        f"    {actions}\n"
        "  ],\n"
        f'  resource == AgentCore::Gateway::"{GATEWAY_ARN}"\n'
        ");"
    )


def gateway_tool_schemas() -> list[dict]:
    """Schemas for the one gateway target. Injected fields stay optional."""
    names = sorted(DEAL_TOOLS | VACANCY_TOOLS)
    schemas = []
    for name in names:
        schemas.append(
            {
                "name": name,
                "description": _DESCRIPTIONS.get(name, name),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                        "as_of": {"type": "string"},
                        "route": {"type": "string"},
                        "occupancy": {"type": "string"},
                        "vacant_only": {"type": "boolean"},
                        "vacant_fill_rent": {"type": "number"},
                        "operating_expenses": {"type": "number"},
                        "ask_price": {"type": "number"},
                        "noi": {"type": "number"},
                        "query": {"type": "string"},
                        "max_results": {"type": "integer"},
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "hitl_allow": {"type": "boolean"},
                        "horizon_months": {"type": "integer"},
                        "question": {"type": "string"},
                        "session_id": {"type": "string"},
                        "tasks": {"type": "string"},
                        "analysis": {"type": "string"},
                        "need_replan": {"type": "boolean"},
                        "last_work_tool": {"type": "string"},
                        "last_work_status": {"type": "string"},
                        "status_since_work": {"type": "boolean"},
                        "confirm": {"type": "boolean"},
                        "property_name": {"type": "string"},
                        "building": {"type": "string"},
                        "plan": {"type": "string"},
                        "file_id": {"type": "string"},
                        "filename": {"type": "string"},
                        "content_base64": {"type": "string"},
                        "renovated": {"type": "integer"},
                    },
                },
            }
        )
    return schemas
