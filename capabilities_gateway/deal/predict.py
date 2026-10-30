"""Forward ask_prediction_agent to the vacancy app's ask_vacancy MCP tool.

Question text, session id, and the do-not-parse wrapper live here. The deal
app only forwards the model's arguments to /mcp/deal.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from capabilities_gateway.deal.forward import forward_ask_vacancy

_OCCUPANCY_ONLY_RE = re.compile(
    r"^what occupancy do you predict(?:\s+for\s+.+?)?(?:\s+as of\s+.+?)?\??$",
    re.I,
)
_CLARIFY_RE = re.compile(
    r"(?is)("
    r"not trained|no (?:saved )?fit|not saved|"
    r"which (?:floor )?plan|which group|which variant|"
    r"which .{0,80}(?:renovat|score)|"
    r"which would you like|"
    r"ambiguous_plan|"
    r"more than one (?:saved )?(?:group|plan)|"
    r"covers more than one|"
    r"(?:can't|cannot) score an aggregate|"
    r"pick one exact|"
    r"which properties (?:are|have been) trained|"
    r"have not been trained"
    r")"
)
_NEW_PREDICT_RE = re.compile(
    r"(?is)\b("
    r"what occupancy do you predict|"
    r"over the next\s+\d+\s+months|"
    r"predicted occupancy|"
    r"predicted vacancy|"
    r"forecast occupancy"
    r")\b"
)

_state: dict[str, dict[str, Any]] = {}


def reset_predict_state() -> None:
    _state.clear()


def looks_like_clarification(text: str) -> bool:
    return bool(_CLARIFY_RE.search((text or "").strip()))


def _generic_property_label(name: str) -> bool:
    n = (name or "").strip().lower()
    return not n or n in {"this property", "the property", "this building", "the building"}


_VAULT_FILE_SUFFIX_RE = re.compile(r"-\d{8}-\d{6}(?:\s*-\s*\d+)?$")


def _same_building(spoken: str, property_name: str) -> bool:
    """True when the spoken label is this vault roll, not another building.

    Ingested names often carry a file suffix (as-of, unit count). 'Bay View
    Gardens Apartments' still names that roll.
    """
    a = (spoken or "").strip().lower()
    b = (property_name or "").strip().lower()
    if not a or not b or _generic_property_label(a) or _generic_property_label(b):
        return False
    return a == b or a in b or b in a


def strip_vault_suffix(label: str) -> str:
    """Drop ingest filename suffix so vacancy can match a trained name."""
    text = (label or "").strip()
    return _VAULT_FILE_SUFFIX_RE.sub("", text).strip() or text


def display_building_label(property_name: str, spoken: str = "") -> str:
    """Short same-building label for the vacancy prompt (never the file stem)."""
    name = (property_name or "").strip()
    phrase = (spoken or "").strip()
    if phrase and _same_building(phrase, name):
        return strip_vault_suffix(phrase)
    return strip_vault_suffix(name)


def prediction_building(question: str, vault_name: str = "") -> tuple[str, str]:
    """Property to score: question name wins, otherwise the vault roll.

    Returns (label, source) where source is 'question', 'vault', or ''.
    """
    asked = (question or "").strip()
    spoken = building_phrase(asked)
    raw_vault = (vault_name or "").strip()
    vault = strip_vault_suffix(raw_vault)
    if spoken and not _generic_property_label(spoken):
        return strip_vault_suffix(spoken), "question"
    if asked and raw_vault and not _generic_property_label(raw_vault):
        low = asked.lower()
        if raw_vault.lower() in low or (vault and vault.lower() in low):
            return vault, "question"
    if vault and not _generic_property_label(vault):
        return vault, "vault"
    return "", ""


def user_named_property(question: str, property_name: str = "") -> bool:
    asked = (question or "").strip()
    name = (property_name or "").strip()
    if not asked or _generic_property_label(name):
        return False
    if name.lower() in asked.lower():
        return True
    spoken = building_phrase(asked)
    return bool(spoken) and _same_building(spoken, name)


_TIME_PHRASE_RE = re.compile(
    r"^(?:the\s+)?(?:next|last|coming|following)\b|^\d+\s+months?$",
    re.I,
)
_SKILL_LEAK_RE = re.compile(r"^(?:i loaded the vacancy skill\.\s*)+", re.I)


def building_phrase(question: str) -> str:
    """Building written after 'for' in the user question. Empty when they named none."""
    asked = re.sub(r"\?+$", "", (question or "").strip()).strip()
    match = re.search(r"\bfor\s+(.+?)(?:\s+as of\s+.+)?$", asked, re.I)
    if not match:
        return ""
    name = match.group(1).strip(" .\"'")
    if not name or _generic_property_label(name) or _TIME_PHRASE_RE.match(name):
        return ""
    return name


def strip_skill_narration(answer: str) -> str:
    """Drop a leading 'I loaded the vacancy skill' so the deal quote stays the answer."""
    return _SKILL_LEAK_RE.sub("", (answer or "").strip()).strip()


def is_followup_reply(message: str) -> bool:
    asked = (message or "").strip()
    if not asked:
        return False
    if _OCCUPANCY_ONLY_RE.match(asked):
        return False
    if building_phrase(asked):
        return False
    if _NEW_PREDICT_RE.search(asked):
        return False
    return True


def _session(username: str) -> dict[str, Any]:
    key = username or "anon"
    row = _state.get(key)
    if not row:
        row = {"session_id": str(uuid.uuid4())}
        _state[key] = row
    return row


def vault_facts(roll: Any, as_of: str | None = None) -> dict[str, Any]:
    """Book facts for the MCP question. Never a file upload."""
    as_of = as_of or getattr(roll, "as_of", None)
    plans: list[str] = []
    seen: set[str] = set()
    for unit in getattr(roll, "units", None) or []:
        name = (getattr(unit, "unit_type", None) or "").strip()
        if name and name not in seen:
            seen.add(name)
            plans.append(name)
    property_name = (
        (getattr(roll, "property_name", None) or "").strip()
        or (getattr(roll, "source_filename", None) or "").strip()
        or "this property"
    )
    unit_count = int(getattr(roll, "unit_count", 0) or 0)
    occ_fn = getattr(roll, "occupancy_pct_on", None)
    vacant_fn = getattr(roll, "vacant_count_on", None)
    occupancy_pct = (
        round(float(occ_fn(as_of)), 4) if callable(occ_fn) and unit_count else 0.0
    )
    vacant_count = int(vacant_fn(as_of)) if callable(vacant_fn) else 0
    return {
        "property_name": property_name,
        "as_of": as_of or "",
        "unit_count": unit_count,
        "occupancy_pct": occupancy_pct,
        "vacant_count": vacant_count,
        "floor_plans": plans,
    }


def build_forecast_question(
    question: str = "",
    horizon_months: int = 12,
    vault: dict[str, Any] | None = None,
    trained: bool = False,
) -> str:
    """MCP ask_vacancy question: user text + do-not-parse. Never invent a building."""
    vault = vault or {}
    name = str(vault.get("property_name") or "").strip()
    as_of = str(vault.get("as_of") or "").strip()
    asked = (question or "").strip()
    label, source = prediction_building(asked, name)
    same_as_vault = bool(label) and (source == "vault" or _same_building(label, name))
    occupancy_only = bool(asked) and bool(_OCCUPANCY_ONLY_RE.match(asked))
    if occupancy_only:
        asked = asked or "What occupancy do you predict?"
    elif not asked:
        asked = (
            f"Over the next {horizon_months} months, how many units expire or are MTM, "
            "what monthly income is at risk, and what occupancy do you predict"
            + (f" for {label}" if label else "")
            + "?"
        )
    if label and label.lower() not in asked.lower():
        asked = asked.rstrip(" ?") + f" for {label}?"
    if occupancy_only:
        pass
    elif "do not request a rent roll" not in asked.lower():
        asked = asked.rstrip(" ?") + "? Do not request a rent roll file."
    if "do not parse" not in asked.lower() and "do not request a rent roll" not in asked.lower():
        asked = asked.rstrip(" ?") + "? Do not parse or train."
    lines = [
        "Do not parse, upload, or train. Do not request a rent roll file. "
        "This caller is questions-only (MCP ask_vacancy). A fit may already exist."
    ]
    if label and same_as_vault and trained:
        headed = f"Score occupancy for {label}"
        if as_of:
            headed += f" as of {as_of}"
        lines.append(headed + ".")
        bits = [
            f"unit_count={vault.get('unit_count')}",
            f"occupancy_pct={vault.get('occupancy_pct')}",
            f"vacant_count={vault.get('vacant_count')}",
        ]
        lines.append("Book snapshot for context only (not a file to parse): " + "; ".join(bits) + ".")
    elif label:
        lines.append(
            f"The question names {label}. Call load_fit with that name. "
            "If load_fit says it is not saved, call list_trained_properties and say "
            f"{label} is not trained, listing which properties are trained. "
            "If none are trained, say no properties are trained yet. "
            "Do not say that a skill was loaded. Do not ask for a different building "
            "when no properties are trained. Do not substitute the vault property. "
            "Do not call load_fit with an empty name."
        )
    else:
        lines.append(
            "If no building is named in the question and there is no vault property, "
            "call list_trained_properties and say which properties are trained, "
            "or ask which building to score. Do not call load_fit with an empty name."
        )
    lines.append("Question: " + asked)
    return "\n".join(lines)


def forecast(
    username: str,
    question: str,
    horizon_months: int = 12,
    vault: dict[str, Any] | None = None,
    session_id: str = "",
    trained: bool = False,
) -> dict[str, Any]:
    """POST the vacancy app ask_vacancy tool. Reuse one session id per username."""
    state = _session(username)
    if (session_id or "").strip():
        state["session_id"] = session_id.strip()
    asked = (question or "").strip()
    followup = bool(state.get("awaiting_followup")) and is_followup_reply(asked)
    if followup:
        prompt = asked
    else:
        prompt = build_forecast_question(
            question,
            horizon_months=horizon_months,
            vault=vault,
            trained=trained,
        )
    answer = strip_skill_narration(
        forward_ask_vacancy(prompt, state["session_id"])
    )
    awaiting = looks_like_clarification(answer)
    state["awaiting_followup"] = awaiting
    return {
        "source": "vacancy-prediction-agent",
        "horizon_months": horizon_months,
        "answer": answer,
        "ok": True,
        "awaiting_followup": awaiting,
        "session_id": state["session_id"],
    }
