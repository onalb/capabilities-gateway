"""list_trained_properties is a vacancy-only read of the fit store."""

from __future__ import annotations

import json
from pathlib import Path

from capabilities_gateway.vacancy_math.store import (
    BlobFitStore,
    DirectoryFitStore,
    resolve_trained_name,
)
from capabilities_gateway.vacancy_math.tools import list_trained_properties, load_fit, reset_store
from test_allowlist import _call, _tool_names
from test_checklist import _body

SKILL = (
    Path(__file__).resolve().parents[1] / "skills" / "vacancy" / "SKILL.md"
).read_text(encoding="utf-8")


def _record(name: str) -> dict:
    return {"property": name, "as_of": "2024-01-01", "groups": []}


def _use_dir(monkeypatch, root: Path) -> None:
    monkeypatch.setenv("VACANCY_FIT_DIR", str(root))
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT", raising=False)
    reset_store()


def test_two_saved_fits_return_both_property_names(tmp_path, monkeypatch):
    _use_dir(monkeypatch, tmp_path)
    DirectoryFitStore(tmp_path).save(_record("North Tower"))
    DirectoryFitStore(tmp_path).save(_record("South Annex"))
    result = list_trained_properties()
    assert result["properties"] == ["North Tower", "South Annex"]
    assert result["text"] == "North Tower, South Annex"
    assert "north-tower" not in result["properties"]
    assert "probability" not in result
    assert "deleted" not in result
    assert (tmp_path / "north-tower.json").is_file()
    assert (tmp_path / "south-annex.json").is_file()
    reset_store()


def test_resolve_trained_name_maps_vault_filename_to_saved_property():
    names = ["Bay View Gardens Apartments"]
    assert (
        resolve_trained_name(
            "Bay View Gardens Apartments-20210930-040414 - 250", names
        )
        == "Bay View Gardens Apartments"
    )
    assert resolve_trained_name("bay-view-gardens-apartments", names) == (
        "Bay View Gardens Apartments"
    )
    assert resolve_trained_name("Bay View Gardens Apartments", names) == (
        "Bay View Gardens Apartments"
    )
    assert resolve_trained_name("Chambers Hill", names) is None
    assert (
        resolve_trained_name("Bay View", ["Bay View Gardens Apartments", "Bay View Court"])
        is None
    )


def test_load_fit_accepts_rent_roll_filename(tmp_path, monkeypatch):
    _use_dir(monkeypatch, tmp_path)
    DirectoryFitStore(tmp_path).save(_record("Bay View Gardens Apartments"))
    result = load_fit("Bay View Gardens Apartments-20210930-040414 - 250")
    assert result["property"] == "Bay View Gardens Apartments"
    assert "error" not in result
    reset_store()


def test_empty_directory_says_none_are_trained(tmp_path, monkeypatch):
    _use_dir(monkeypatch, tmp_path)
    result = list_trained_properties()
    assert result == {"properties": [], "text": "No properties are trained yet."}
    blob = json.dumps(result).lower()
    assert "north tower" not in blob
    assert "south annex" not in blob
    assert list(tmp_path.glob("*.json")) == []
    reset_store()


def test_property_field_wins_and_slug_is_the_fallback(tmp_path, monkeypatch):
    _use_dir(monkeypatch, tmp_path)
    (tmp_path / "other-slug.json").write_text(
        json.dumps({"property": "North Tower", "as_of": "2024-01-01"}),
        encoding="utf-8",
    )
    (tmp_path / "west-court.json").write_text(
        json.dumps({"as_of": "2024-01-01"}),
        encoding="utf-8",
    )
    result = list_trained_properties()
    assert result["properties"] == ["North Tower", "west-court"]
    assert "other-slug" not in result["properties"]
    reset_store()


class _Blob:
    def __init__(self, container: "_Container", name: str) -> None:
        self.container = container
        self.name = name

    def exists(self) -> bool:
        return self.name in self.container.blobs

    def download_blob(self):
        data = self.container.blobs[self.name]

        class _Download:
            def readall(_self):
                return data

        return _Download()


class _Container:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def get_blob_client(self, name: str) -> _Blob:
        return _Blob(self, name)

    def upload_blob(self, name: str, data, overwrite: bool = False) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.blobs[name] = data

    def list_blobs(self):
        return [type("Item", (), {"name": name})() for name in list(self.blobs)]


def test_azure_store_returns_property_names_not_slugs():
    store = BlobFitStore.__new__(BlobFitStore)
    store.container = _Container()
    store.save(_record("North Tower"))
    store.container.blobs["west-court.json"] = b'{"as_of": "2024-01-01"}'
    assert store.property_names() == ["North Tower", "west-court"]


def test_mcp_empty_store_does_not_name_a_building(client, tmp_path, monkeypatch):
    _use_dir(monkeypatch, tmp_path)
    payload = _call(client, "/mcp/vacancy", "list_trained_properties", {})
    assert payload.get("error") is None
    body = json.loads(payload["result"]["content"][0]["text"])
    assert body == {"properties": [], "text": "No properties are trained yet."}
    assert "north tower" not in json.dumps(body).lower()
    reset_store()


def test_list_trained_properties_is_vacancy_only(client):
    assert "list_trained_properties" in _tool_names(client, "/mcp/vacancy")
    assert "list_trained_properties" not in _tool_names(client, "/mcp/deal")
    missed = _call(client, "/mcp/deal", "list_trained_properties", {})
    text = json.dumps(missed).lower()
    assert missed.get("error") or "unknown tool" in text or "not found" in text or "invalid" in text


def test_update_plan_status_accepts_list_trained_properties(client):
    created = _body(
        client,
        "/mcp/vacancy",
        "create_plan",
        {"tasks": "1. [in_progress] list_trained_properties"},
    )
    marked = _body(
        client,
        "/mcp/vacancy",
        "update_plan_status",
        {
            "tasks": "1. list_trained_properties",
            "checklist": created["checklist"],
            "last_work_tool": "list_trained_properties",
            "last_work_status": "ok",
        },
    )
    assert marked["ok"] is True
    assert marked["checklist"] == [{"text": "list_trained_properties", "status": "completed"}]


def test_skill_tells_the_model_to_list_trained_properties():
    lowered = SKILL.lower()
    start = lowered.index("when the user asks which properties are trained")
    end = lowered.index("answer starts from a text question")
    paragraph = lowered[start:end]
    assert "list_trained_properties" in paragraph
    assert "the plan contains list_trained_properties" in paragraph
    assert "no properties are trained yet" in paragraph
    assert "do not use load_fit with an empty name for that question" in paragraph
    for banned in ("la cordoba", "bay view", "chambers"):
        assert banned not in lowered
