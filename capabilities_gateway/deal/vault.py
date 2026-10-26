"""Session rent roll. Dynamo when DDB_ENDPOINT is set, else an in-memory store."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from capabilities_gateway.deal.roll import CanonicalRentRoll

SK = "VAULT#default"
MEMO_SK_PREFIX = "MEMO#"

_memory_rolls: dict[str, dict[str, Any]] = {}
_memory_memos: dict[str, list[dict[str, Any]]] = {}


def use_dynamo() -> bool:
    """Local deal Dynamo, or real AWS only when DDB_USE_AWS=1.

    DDB_ENDPOINT points at the deal app's dynamodb-local. Leaving it unset
    keeps unit tests and a bare local process off AWS.
    """
    if os.environ.get("DDB_ENDPOINT", "").strip():
        return True
    return os.environ.get("DDB_USE_AWS", "").strip().lower() in {"1", "true", "yes"}


def reset_memory() -> None:
    _memory_rolls.clear()
    _memory_memos.clear()


def put_memory_roll(username: str, roll: dict[str, Any]) -> None:
    _memory_rolls[username.strip().lower()] = roll


def load_roll(username: str) -> CanonicalRentRoll | None:
    key = (username or "").strip().lower()
    if not key:
        return None
    if use_dynamo():
        from capabilities_gateway.deal import dynamo

        item = dynamo.get_item(key, SK)
        raw = (item or {}).get("roll")
    else:
        raw = _memory_rolls.get(key)
    if not isinstance(raw, dict):
        return None
    return CanonicalRentRoll.model_validate(raw)


def save_memo(username: str, title: str, body: str, ts: str | None = None) -> dict[str, Any]:
    ts = ts or datetime.now(timezone.utc).isoformat()
    item = {"title": title, "body": body, "ts": ts}
    key = username.strip().lower()
    if use_dynamo():
        from capabilities_gateway.deal import dynamo

        dynamo.put_item(key, f"{MEMO_SK_PREFIX}{ts}", item)
        return item
    _memory_memos.setdefault(key, []).append(item)
    return item
