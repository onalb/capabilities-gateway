"""Vacancy math tools. Parse, fit, load, list, save, delete, and score run in this process.

delete_fit on this gateway removes a file only when confirm is true. The vacancy
app holds the pending user confirmation. This process is stateless, so a direct
call here is not a user prompt. The model-facing vacancy tool withholds confirm
until that session gate passes.
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from capabilities_gateway.vacancy_math.fit import fit_vacancy as fit_model
from capabilities_gateway.vacancy_math.fit import plan_catalog
from capabilities_gateway.vacancy_math.fit import score_vacancy as score_model
from capabilities_gateway.vacancy_math.parse import parse_rent_roll
from capabilities_gateway.vacancy_math.store import FitStore, open_store, without_group_probability

VACANCY_TOOL_NAMES = (
    "parse_rent_roll_file",
    "fit_vacancy",
    "load_fit",
    "list_trained_properties",
    "save_fit",
    "delete_fit",
    "score_vacancy",
)

NOT_TRAINED_TEXT = "No properties are trained yet."

_store: FitStore | None = None


def reset_store() -> None:
    global _store
    _store = None


def fits() -> FitStore:
    """Client for ``VACANCY_FIT_DIR`` or Azure Blob. Each call reads that store.

    The cached object is the client, not the fit JSON. A Lambda warm start
    does not reuse a previous call's records from memory. Local runs and
    pytest use the directory and do not need AWS. A deployed tools Lambda
    should set ``AZURE_STORAGE_ACCOUNT`` or a durable ``VACANCY_FIT_DIR``.
    """
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


def _trained_payload(names: list) -> dict:
    cleaned = [str(name).strip() for name in names if str(name).strip()]
    if not cleaned:
        return {"properties": [], "text": NOT_TRAINED_TEXT}
    return {"properties": cleaned, "text": ", ".join(cleaned)}


def list_trained_properties() -> dict:
    """Names of properties this model is trained on.

    Returns the saved property field, or the file slug when that field is
    missing. If none are saved, say no properties are trained yet. Does not
    score, fit, or delete, and does not invent a building.
    """
    return _trained_payload(fits().property_names())


def load_fit(property_name: str = "") -> dict:
    """One named building's plan catalog (no probabilities).

    An empty name is not how you list trained properties. Use
    list_trained_properties for that question.
    """
    store = fits()
    if not (property_name or "").strip():
        return {"buildings": store.names()}
    needle = property_name.strip()
    record = store.load(needle)
    if record is None:
        return {
            "error": "not_saved",
            "property": needle,
            "buildings": store.names(),
        }
    return {
        "property": record.get("property"),
        "as_of": record.get("as_of"),
        **plan_catalog(record),
    }


def delete_fit(
    property_name: str = "",
    all_properties: bool = False,
    confirm: bool = False,
) -> dict:
    """Delete fit JSON. Does nothing unless confirm is true.

    The vacancy app sends confirm only after the user agrees to the same
    pending scope. Omitting confirm does not delete, so a direct call cannot
    skip that session gate by itself.
    """
    if not _flag(confirm):
        return {
            "deleted": False,
            "pending": False,
            "error": "confirm_required",
            "text": (
                "Nothing was removed. This gateway deletes a fit only when the "
                "vacancy app sends confirm=true after the user agrees in that session."
            ),
        }
    store = fits()
    if _flag(all_properties):
        result = store.delete_all()
        count = int(result.get("count") or 0)
        return {
            "deleted": True,
            "pending": False,
            "scope": "all",
            "count": count,
            "text": f"Deleted every trained property. {count} JSON files were deleted.",
        }
    name = (property_name or "").strip()
    if not name:
        return {
            "deleted": False,
            "error": "property_required",
            "text": "Name a trained property, or remove every trained property.",
        }
    result = store.delete(name)
    if not result.get("deleted"):
        return {
            "deleted": False,
            "error": "not_found",
            "property": name,
            "text": f"{name} is not trained.",
        }
    saved = str(result.get("property") or name)
    return {
        "deleted": True,
        "pending": False,
        "scope": "one",
        "property": saved,
        "text": f"Removed {saved} from the trained model. The JSON file was deleted.",
    }


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def save_fit(property_name: str, as_of: str, model: dict) -> dict:
    """Write one building fit. model is the object returned by fit_vacancy."""
    record = without_group_probability(
        {
            "property": property_name.strip(),
            "as_of": as_of,
            "reference_plan": model["reference_plan"],
            "beta0": model["beta0"],
            "beta_plan": model["beta_plan"],
            "beta_reno": model["beta_reno"],
            "groups": model["groups"],
        }
    )
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
