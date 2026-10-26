"""Dynamo access matching the deal app (USER# / VAULT#default / MEMO#)."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

TABLE = os.environ.get("DDB_TABLE", "ml_interview")


def _resource():
    import boto3

    kwargs: dict[str, Any] = {"region_name": os.environ.get("AWS_REGION", "us-east-1")}
    endpoint = os.environ.get("DDB_ENDPOINT") or ""
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID", "local")
        kwargs["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY", "local")
    return boto3.resource("dynamodb", **kwargs)


def pk_user(username: str) -> str:
    return f"USER#{username.strip().lower()}"


def _jsonable(val: Any) -> Any:
    if isinstance(val, Decimal):
        return int(val) if val % 1 == 0 else float(val)
    if isinstance(val, dict):
        return {k: _jsonable(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_jsonable(v) for v in val]
    return val


def _to_ddb(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, float):
        return Decimal(str(val))
    if isinstance(val, dict):
        return {k: _to_ddb(v) for k, v in val.items() if v is not None}
    if isinstance(val, list):
        return [_to_ddb(v) for v in val]
    return val


def get_item(username: str, sk: str) -> dict[str, Any] | None:
    item = _resource().Table(TABLE).get_item(Key={"pk": pk_user(username), "sk": sk}).get("Item")
    return _jsonable(item) if item else None


def put_item(username: str, sk: str, attrs: dict[str, Any]) -> None:
    item = _to_ddb({"pk": pk_user(username), "sk": sk, **attrs})
    _resource().Table(TABLE).put_item(Item=item)
