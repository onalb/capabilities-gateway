"""Directory and blob fit deletes, plus POST /mcp/vacancy delete_fit."""

from __future__ import annotations

import json
from pathlib import Path

from capabilities_gateway.vacancy_math.store import BlobFitStore, DirectoryFitStore
from capabilities_gateway.vacancy_math.tools import delete_fit, reset_store
from test_allowlist import _call
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


def test_directory_delete_missing_is_not_found(tmp_path):
    store = DirectoryFitStore(tmp_path)
    store.save(_record("North Tower"))
    missing = store.delete("No Such Place")
    assert missing["deleted"] is False
    assert missing["error"] == "not_found"
    assert (tmp_path / "north-tower.json").is_file()


def test_directory_delete_one_leaves_the_other_file(tmp_path):
    store = DirectoryFitStore(tmp_path)
    store.save(_record("North Tower"))
    store.save(_record("South Annex"))
    removed = store.delete("north-tower")
    assert removed == {"deleted": True, "property": "North Tower"}
    assert not (tmp_path / "north-tower.json").is_file()
    assert (tmp_path / "south-annex.json").is_file()


def test_directory_delete_all_reports_count(tmp_path):
    store = DirectoryFitStore(tmp_path)
    store.save(_record("North Tower"))
    store.save(_record("South Annex"))
    result = store.delete_all()
    assert result == {"deleted": True, "count": 2}
    assert list(tmp_path.glob("*.json")) == []


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

    def delete_blob(self) -> None:
        if self.name not in self.container.blobs:
            raise FileNotFoundError(self.name)
        del self.container.blobs[self.name]


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


def test_blob_delete_removes_the_slug_and_reports_missing():
    store = BlobFitStore.__new__(BlobFitStore)
    store.container = _Container()
    store.save(_record("North Tower"))
    store.save(_record("South Annex"))
    assert "north-tower.json" in store.container.blobs
    missing = store.delete("No Such Place")
    assert missing["deleted"] is False
    assert missing["error"] == "not_found"
    assert "north-tower.json" in store.container.blobs
    removed = store.delete("NORTH TOWER")
    assert removed == {"deleted": True, "property": "North Tower"}
    assert "north-tower.json" not in store.container.blobs
    assert "south-annex.json" in store.container.blobs
    wiped = store.delete_all()
    assert wiped == {"deleted": True, "count": 1}
    assert store.container.blobs == {}


def test_gateway_delete_waits_for_confirm(tmp_path, monkeypatch):
    _use_dir(monkeypatch, tmp_path)
    DirectoryFitStore(tmp_path).save(_record("North Tower"))
    held = delete_fit("North Tower", confirm=False)
    assert held["deleted"] is False
    assert held["error"] == "confirm_required"
    assert (tmp_path / "north-tower.json").is_file()
    gone = delete_fit("north-tower", confirm=True)
    assert gone["deleted"] is True
    assert gone["property"] == "North Tower"
    assert "The JSON file was deleted." in gone["text"]
    assert not (tmp_path / "north-tower.json").is_file()
    reset_store()


def test_mcp_delete_fit_confirm_removes_one_file(client, tmp_path, monkeypatch):
    _use_dir(monkeypatch, tmp_path)
    DirectoryFitStore(tmp_path).save(_record("North Tower"))
    DirectoryFitStore(tmp_path).save(_record("South Annex"))
    held = _call(client, "/mcp/vacancy", "delete_fit", {"property_name": "North Tower"})
    assert held.get("error") is None
    body = json.loads(held["result"]["content"][0]["text"])
    assert body["deleted"] is False
    assert (tmp_path / "north-tower.json").is_file()
    gone = _call(
        client,
        "/mcp/vacancy",
        "delete_fit",
        {"property_name": "north-tower", "confirm": True},
    )
    deleted = json.loads(gone["result"]["content"][0]["text"])
    assert deleted["deleted"] is True
    assert deleted["property"] == "North Tower"
    assert not (tmp_path / "north-tower.json").is_file()
    assert (tmp_path / "south-annex.json").is_file()
    missing = _call(
        client,
        "/mcp/vacancy",
        "delete_fit",
        {"property_name": "No Such Place", "confirm": True},
    )
    unknown = json.loads(missing["result"]["content"][0]["text"])
    assert unknown["error"] == "not_found"
    assert unknown["deleted"] is False
    reset_store()


def test_mcp_delete_all_reports_how_many_json_files(client, tmp_path, monkeypatch):
    _use_dir(monkeypatch, tmp_path)
    DirectoryFitStore(tmp_path).save(_record("North Tower"))
    DirectoryFitStore(tmp_path).save(_record("South Annex"))
    asked = _call(
        client,
        "/mcp/vacancy",
        "delete_fit",
        {"all_properties": True, "confirm": False},
    )
    assert json.loads(asked["result"]["content"][0]["text"])["deleted"] is False
    assert (tmp_path / "north-tower.json").is_file()
    wiped = _call(
        client,
        "/mcp/vacancy",
        "delete_fit",
        {"all_properties": True, "confirm": True},
    )
    body = json.loads(wiped["result"]["content"][0]["text"])
    assert body["deleted"] is True
    assert body["count"] == 2
    assert "2 JSON files were deleted." in body["text"]
    assert list(tmp_path.glob("*.json")) == []
    reset_store()


def test_update_plan_status_accepts_delete_fit(client):
    created = _body(
        client,
        "/mcp/vacancy",
        "create_plan",
        {"tasks": "1. [in_progress] delete_fit"},
    )
    marked = _body(
        client,
        "/mcp/vacancy",
        "update_plan_status",
        {
            "tasks": "1. delete_fit",
            "checklist": created["checklist"],
            "last_work_tool": "delete_fit",
            "last_work_status": "ok",
        },
    )
    assert marked["ok"] is True
    assert marked["checklist"] == [{"text": "delete_fit", "status": "completed"}]


def test_vacancy_skill_has_no_real_building_names():
    lowered = SKILL.lower()
    assert "delete_fit" in SKILL
    for banned in ("la cordoba", "bay view", "chambers"):
        assert banned not in lowered
