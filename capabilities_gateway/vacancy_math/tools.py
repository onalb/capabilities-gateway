"""Vacancy math tools. Parse, fit, load, save, and score run in this process."""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from capabilities_gateway.vacancy_math.fit import fit_vacancy as fit_model
from capabilities_gateway.vacancy_math.fit import plan_catalog
from capabilities_gateway.vacancy_math.fit import score_vacancy as score_model
from capabilities_gateway.vacancy_math.parse import parse_rent_roll
from capabilities_gateway.vacancy_math.store import FitStore, open_store

VACANCY_TOOL_NAMES = (
    "parse_rent_roll_file",
    "fit_vacancy",
    "load_fit",
    "save_fit",
    "score_vacancy",
)

_store: FitStore | None = None


def reset_store() -> None:
    global _store
    _store = None


def fits() -> FitStore:
    global _store
    if _store is None:
        _store = open_store()
    return _store


def parse_rent_roll_file(
    file_id: str = "",
    filename: str = "",
    content_base64: str = "",
) -> dict:
    """Parse workbook bytes. The vacancy app reads the upload and sends them."""
    raw_b64 = (content_base64 or "").strip()
    if not raw_b64:
        upload_dir = os.environ.get("VACANCY_UPLOAD_DIR", "").strip()
        if upload_dir and file_id:
            folder = Path(upload_dir)
            matches = list(folder.glob(f"{file_id}.*")) if folder.is_dir() else []
            if matches:
                parsed = parse_rent_roll(matches[0])
                return {"file_id": file_id, **parsed}
        return {"error": "file_not_found", "file_id": file_id}
    raw = base64.b64decode(raw_b64)
    suffix = Path(filename or "roll.xlsx").suffix or ".xlsx"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        Path(path).write_bytes(raw)
        parsed = parse_rent_roll(path)
    finally:
        Path(path).unlink(missing_ok=True)
    return {"file_id": file_id, **parsed}


def fit_vacancy(plans: list[dict]) -> dict:
    """Fit logistic regression. Does not save."""
    return fit_model(plans)


def load_fit(property_name: str = "") -> dict:
    """List saved buildings, or one building's plan catalog (no probabilities)."""
    store = fits()
    if not (property_name or "").strip():
        return {"buildings": store.names()}
    record = store.load(property_name.strip())
    if record is None:
        return {
            "error": "not_saved",
            "property": property_name.strip(),
            "buildings": store.names(),
        }
    return {
        "property": record.get("property"),
        "as_of": record.get("as_of"),
        **plan_catalog(record),
    }


def save_fit(property_name: str, as_of: str, model: dict) -> dict:
    """Write one building fit. model is the object returned by fit_vacancy."""
    record = {
        "property": property_name.strip(),
        "as_of": as_of,
        "reference_plan": model["reference_plan"],
        "beta0": model["beta0"],
        "beta_plan": model["beta_plan"],
        "beta_reno": model["beta_reno"],
        "groups": model["groups"],
    }
    return fits().save(record)


def score_vacancy(building: str, plan: str = "", renovated: int | None = None) -> dict:
    """Score one saved building and one floor plan."""
    name = (building or "").strip()
    store = fits()
    if not name:
        return {"error": "building_required", "buildings": store.names()}
    record = store.load(name)
    if record is None:
        return {"error": "not_saved", "property": name, "buildings": store.names()}
    return score_model(record, plan, renovated)
