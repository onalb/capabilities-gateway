"""Deal capability tools. Same JSON the deal app's in-process tools return."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from capabilities_gateway.deal.roll import CanonicalRentRoll, mean_positive_sqft
from capabilities_gateway.deal import vault

NOMINATIM = "https://nominatim.openstreetmap.org/search"
NEED_FILE_TEXT = (
    "Please attach a rent-roll CSV or Excel file first. "
    "Once it is saved, I can answer follow-up questions about it."
)
HEADLINE_COUNTS_NOTE = (
    "These headline counts are complete in this result (including avg_sqft); "
    "another query_units is only needed to LIST a filtered subset of unit rows, "
    "not to re-fetch counts."
)

DEAL_TOOL_NAMES = (
    "query_units",
    "compute_income",
    "compute_noi",
    "compute_cap_rate",
    "osm_geocode",
    "web_search",
    "publish_memo",
    "ask_prediction_agent",
)
VACANCY_ONLY_TOOL_NAMES = (
    "parse_rent_roll_file",
    "fit_vacancy",
    "load_fit",
    "list_trained_properties",
    "save_fit",
    "score_vacancy",
)


def _need_file(name: str) -> str:
    return json.dumps({"need_file": True, "ok": True, "message": NEED_FILE_TEXT, "tool": name})


def _roll(username: str) -> CanonicalRentRoll | None:
    return vault.load_roll(username)


def _vacant_asking_rent(unit: Any) -> float:
    rent = float(getattr(unit, "in_place_rent", 0) or 0)
    if rent > 0:
        return rent
    extras = getattr(unit, "charge_codes", None) or {}
    if not isinstance(extras, dict):
        return 0.0
    for key, val in extras.items():
        lk = str(key).lower()
        if "market" not in lk and lk not in {"asking", "ask", "_market_rent"}:
            continue
        try:
            n = float(val or 0)
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return 0.0


def query_units(
    occupancy: str | None = None,
    vacant_only: bool = False,
    username: str = "",
    as_of: str = "",
) -> str:
    """Vault unit counts for one deal user. username is injected by the deal app."""
    roll = _roll(username)
    if roll is None:
        return _need_file("query_units")
    units = roll.units
    day = (as_of or "").strip() or roll.as_of
    if vacant_only:
        units = [u for u in units if u.vacant_on(day)]
    if occupancy and occupancy.strip().lower() not in {"all", ""}:
        units = [u for u in units if (u.occupancy or "").lower() == occupancy.lower()]
    unfiltered = (not occupancy or occupancy.strip().lower() in {"all", ""}) and not vacant_only
    payload: dict[str, Any] = {
        "property_name": roll.property_name,
        "as_of": day,
        "geo_confidence": roll.geo_confidence,
        "suggested_address": roll.suggested_address,
        "unit_count": roll.unit_count,
        "occupied_count": roll.occupied_count_on(day),
        "vacant_count": roll.vacant_count_on(day),
        "occupancy_pct": round(roll.occupancy_pct_on(day), 4) if roll.unit_count else 0.0,
        "mtm_count": roll.mtm_count,
        "avg_sqft": mean_positive_sqft(units),
        "sqft_n": sum(1 for u in units if u.sqft is not None and float(u.sqft) > 0),
        "units": [u.model_dump() for u in units[:400]],
    }
    if unfiltered:
        payload["note"] = HEADLINE_COUNTS_NOTE
    return json.dumps(payload)


def compute_income(
    vacant_fill_rent: float | None = None,
    username: str = "",
    as_of: str = "",
) -> str:
    """In-place and full-occupancy income from the vaulted roll."""
    roll = _roll(username)
    if roll is None:
        return _need_file("compute_income")
    day = (as_of or "").strip() or roll.as_of
    monthly = roll.in_place_monthly_on(day)
    occupied = roll.occupied_count_on(day)
    vacant = roll.vacant_count_on(day)
    occ_pct = round(occupied / roll.unit_count, 4) if roll.unit_count else 0.0
    mean_occ = round(monthly / occupied, 2) if occupied else None
    vacant_asking = round(
        sum(_vacant_asking_rent(u) for u in roll.units if u.vacant_on(day)),
        2,
    )
    if vacant_asking > 0:
        full_occ = round(monthly + vacant_asking, 2)
        full_occ_method = "in_place_monthly + vacant_asking_monthly"
    elif occupied and roll.unit_count:
        full_occ = round((monthly / occupied) * roll.unit_count, 2)
        full_occ_method = "mean_occupied_rent * unit_count"
    else:
        full_occ = None
        full_occ_method = None
    payload: dict[str, Any] = {
        "in_place_monthly": round(monthly, 2),
        "in_place_annual": round(monthly * 12, 2),
        "occupied_count": occupied,
        "vacant_count": vacant,
        "unit_count": roll.unit_count,
        "occupancy_pct": occ_pct,
        "mean_occupied_rent": mean_occ,
        "vacant_asking_monthly": vacant_asking,
        "estimated_full_occupancy_monthly": full_occ,
        "estimated_full_occupancy_method": full_occ_method,
        "note": (
            "in_place_monthly is occupied units only. For 100% occupancy / all "
            "units occupied / no-vacant income, use estimated_full_occupancy_monthly "
            "(not in_place_monthly)."
        ),
        "mtm_count": roll.mtm_count,
        "as_of": day,
        "property_name": roll.property_name,
    }
    if vacant_fill_rent is not None:
        fill = float(vacant_fill_rent)
        fill_m = round(vacant * fill, 2)
        payload["vacant_fill_rent"] = round(fill, 2)
        payload["vacant_fill_monthly"] = fill_m
        payload["vacant_fill_annual"] = round(fill_m * 12, 2)
        payload["scenario_full_occupancy_monthly"] = round(monthly + fill_m, 2)
        payload["scenario_full_occupancy_annual"] = round((monthly + fill_m) * 12, 2)
        payload["note"] = (
            payload["note"]
            + " User-stated vacant fill: cite scenario_full_occupancy_annual "
            "(in_place_annual + vacant_fill_annual), not vacant_fill_annual alone."
        )
    return json.dumps(payload)


def compute_noi(
    operating_expenses: float | None = None,
    username: str = "",
    as_of: str = "",
) -> str:
    """NOI = annualized in-place income minus stated operating expenses."""
    del as_of  # deal app uses the roll as-of, not the question as-of
    roll = _roll(username)
    if roll is None:
        return _need_file("compute_noi")
    income = round(roll.in_place_monthly * 12, 2)
    incomplete = operating_expenses is None
    noi = None if incomplete else round(income - float(operating_expenses), 2)
    return json.dumps(
        {
            "in_place_annual": income,
            "operating_expenses": operating_expenses,
            "noi": noi,
            "noi_incomplete": incomplete,
        }
    )


def compute_cap_rate(
    ask_price: float,
    noi: float | None = None,
    username: str = "",
    as_of: str = "",
) -> str:
    """Implied cap = NOI / ask. Uses annualized income when NOI was not passed."""
    del as_of
    roll = _roll(username)
    if roll is None:
        return _need_file("compute_cap_rate")
    if ask_price <= 0:
        return json.dumps({"ok": False, "error": "ask_price must be positive"})
    income = roll.in_place_monthly * 12
    basis = float(noi) if noi is not None else income
    return json.dumps(
        {
            "ask_price": ask_price,
            "basis": round(basis, 2),
            "implied_cap": round(basis / ask_price, 6),
            "implied_on_income": noi is None,
            "note": "NOI incomplete — cap uses in-place income" if noi is None else "cap uses NOI",
        }
    )


def osm_geocode(query: str, username: str = "") -> str:
    """Geocode a street or place with OpenStreetMap Nominatim."""
    del username
    q = (query or "").strip()
    if not q:
        return json.dumps({"ok": False, "error": "geocode query is empty"})
    headers = {"User-Agent": "cre-deal-rentroll/0.1 (capabilities-gateway)"}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            response = client.get(
                NOMINATIM,
                params={"q": q, "format": "json", "limit": 1},
                headers=headers,
            )
            response.raise_for_status()
            hits = response.json()
    except Exception as exc:  # noqa: BLE001 — same surface as the deal tool
        return json.dumps({"ok": False, "error": str(exc)})
    if not hits:
        return json.dumps({"ok": False, "error": "no OSM hits", "query": q})
    hit = hits[0]
    return json.dumps(
        {
            "ok": True,
            "display_name": hit.get("display_name"),
            "lat": float(hit["lat"]),
            "lon": float(hit["lon"]),
            "osm_id": hit.get("osm_id"),
        }
    )


def web_search(query: str, max_results: int = 5, username: str = "") -> str:
    """Public web search."""
    del username
    try:
        from ddgs import DDGS

        rows = list(DDGS().text(query, max_results=max_results))
        return json.dumps(
            {
                "ok": True,
                "results": [
                    {"title": r.get("title"), "href": r.get("href"), "body": r.get("body")}
                    for r in rows
                ],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": str(exc)})


def publish_memo(
    title: str,
    body: str,
    username: str = "",
    hitl_allow: bool = False,
) -> str:
    """Publish a memo after the deal app's HITL approval. Otherwise return pending."""
    if not hitl_allow:
        return json.dumps({"status": "pending_hitl", "title": title})
    if not (username or "").strip():
        return json.dumps({"ok": False, "error": "username required to publish a memo"})
    saved = vault.save_memo(username, title, body)
    return json.dumps(
        {
            "status": "published",
            "title": title,
            "bytes": len(body or ""),
            "ts": saved.get("ts"),
        }
    )


def _trained_property(name: str) -> str:
    """Saved fit property for a spoken or vault label, or empty if none."""
    needle = (name or "").strip()
    if not needle:
        return ""
    from capabilities_gateway.vacancy_math.tools import load_fit

    view = load_fit(needle)
    if not isinstance(view, dict) or view.get("error") == "not_saved":
        return ""
    return str(view.get("property") or "").strip()


def _roll_plan_table(roll: Any, as_of: str = "") -> list[dict[str, Any]]:
    """Aggregated per-plan groups of a vault roll: {plan, renovated, units, vacant}.

    Same filtering the old in-gateway fit used: units whose occupancy contains
    'model' or 'excluded' are skipped. This table is fit transiently by the
    vacancy app; it is never saved.
    """
    day = (as_of or "").strip() or getattr(roll, "as_of", "")
    counts: dict[tuple[str, int], list[int]] = {}
    for unit in getattr(roll, "units", None) or []:
        occ = (getattr(unit, "occupancy", None) or "").lower()
        if "model" in occ or "excluded" in occ:
            continue
        plan = (getattr(unit, "unit_type", None) or "").strip() or "unknown"
        renovated = 1 if int(getattr(unit, "renovated", 0) or 0) else 0
        bucket = counts.setdefault((plan, renovated), [0, 0])
        bucket[0] += 1
        bucket[1] += 1 if unit.vacant_on(day) else 0
    return [
        {"plan": plan, "renovated": renovated, "units": total, "vacant": vacant}
        for (plan, renovated), (total, vacant) in sorted(counts.items())
    ]


def ask_prediction_agent(
    horizon_months: int = 12,
    question: str = "",
    session_id: str = "",
    username: str = "",
    as_of: str = "",
) -> str:
    """Forward a forecast or floor-plan vacancy question to the vacancy app MCP
    tool ask_vacancy.

    VACANCY_MCP_URL is that app's POST /mcp. This tool does not parse, fit, or
    save. When the user has a vault roll and the building is not already
    trained, its aggregated plan table is attached as ask_vacancy plan_table
    so the vacancy app fits it transiently (never saved). A saved fit for
    that building — or a question that names a different building — stays
    on the trained store, never a substitute.
    """
    from capabilities_gateway.deal.predict import (
        building_phrase,
        display_building_label,
        forecast,
        user_named_property,
        vault_facts,
    )

    ctx = None
    plan_table: list[dict[str, Any]] = []
    try:
        roll = _roll(username)
        if roll is not None:
            day = (as_of or "").strip() or roll.as_of
            ctx = vault_facts(roll, day)
            # Attach this roll's plan groups unless the question names a different
            # building: that ask stays on the trained store, never a substitute.
            spoken = building_phrase(question or "")
            if not spoken or user_named_property(question or "", ctx["property_name"]):
                table = _roll_plan_table(roll, day)
                label = display_building_label(ctx["property_name"], spoken)
                trained = _trained_property(label) or _trained_property(ctx["property_name"])
                # A saved fit already has the trained plan_keys (1x1 / 2x1).
                # The vault table can be bedroom counts (1 / 2) — do not
                # override the catalog the vacancy UI would use.
                plan_table = [] if trained else table
        result = forecast(
            username,
            question,
            horizon_months=int(horizon_months or 12),
            vault=ctx,
            session_id=session_id,
            plan_table=plan_table,
        )
    except Exception as exc:  # noqa: BLE001 — tool error, do not crash the MCP call
        result = {"ok": False, "error": str(exc), "source": "vacancy-prediction-agent"}
    return json.dumps(result)
