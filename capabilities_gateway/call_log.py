"""One stdout line per MCP tools/call.

App Runner ships container stdout to the application log group. The line names
the path, the tool, and ok or error. Argument text is an allowlist: property,
plan, file_id, and a truncated question. File bytes, memo text, queries,
usernames, and anything that looks like an email, phone number, or secret
stay off the line.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

_LOG = logging.getLogger("capabilities.tool")

_PATHS = {"/mcp/deal", "/mcp/vacancy"}
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}")
_LONG_DIGITS = re.compile(r"\d{7,}")
_UNSAFE = re.compile(r"[^A-Za-z0-9 ./:_-]")

_QUESTION_LIMIT = 80
_ID_LIMIT = 80


class _StdoutLine(logging.Handler):
    """Write to the process stdout at emit time so App Runner and pytest both see it."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


def _ensure_log() -> None:
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = False
    if _LOG.handlers:
        return
    handler = _StdoutLine()
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOG.addHandler(handler)


def _clean(value: object, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = _EMAIL.sub("redacted", text)
    text = _PHONE.sub("redacted", text)
    text = _LONG_DIGITS.sub("redacted", text)
    text = _UNSAFE.sub("", text)
    text = re.sub(r" {2,}", " ", text).strip()
    return text[:limit].strip()


def _arguments(params: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(params, Mapping):
        return {}
    raw = params.get("arguments")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


def _tool_name(params: Mapping[str, Any] | None) -> str:
    if not isinstance(params, Mapping):
        return "-"
    name = params.get("name")
    if isinstance(name, str) and _TOOL_NAME.fullmatch(name):
        return name
    return "-"


def _first(args: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if not isinstance(value, (str, int, float)):
            continue
        # Ids and names longer than this are file payloads or pasted rolls, not labels.
        if isinstance(value, str) and key != "question" and len(value) > _ID_LIMIT:
            continue
        cleaned = _clean(value, limit=_QUESTION_LIMIT if key == "question" else _ID_LIMIT)
        if cleaned:
            return cleaned
    return ""


def argument_summary(params: Mapping[str, Any] | None) -> str:
    """Allowlisted argument fields only. Empty when the call has none of them."""
    args = _arguments(params)
    fields = (
        ("property", _first(args, "property", "property_name", "building")),
        ("plan", _first(args, "plan", "floor_plan")),
        ("file_id", _first(args, "file_id")),
        ("question", _first(args, "question")),
    )
    return " ".join(f'{key}="{value}"' for key, value in fields if value)


def format_tool_line(path: str, params: Mapping[str, Any] | None, status: str) -> str:
    path_token = path if path in _PATHS else "/mcp/unknown"
    status_token = "ok" if status == "ok" else "error"
    line = f"TOOL path={path_token} tool={_tool_name(params)} status={status_token}"
    summary = argument_summary(params)
    if summary:
        line = f"{line} {summary}"
    return line


def _payload_object(data: Mapping[str, Any]) -> Any:
    structured = data.get("structuredContent")
    if isinstance(structured, Mapping):
        if list(structured.keys()) == ["result"]:
            inner = structured.get("result")
            if isinstance(inner, Mapping):
                return dict(inner)
            if isinstance(inner, str):
                return _json_object(inner)
        return dict(structured)
    content = data.get("content")
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                texts.append(item["text"])
        if texts:
            return _json_object("\n".join(texts))
    return None


def _json_object(text: str) -> Any:
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _result_mapping(result: Any) -> Mapping[str, Any] | None:
    if isinstance(result, BaseModel):
        dumped = result.model_dump(by_alias=True, mode="json", exclude_none=True)
        return dumped if isinstance(dumped, dict) else None
    if isinstance(result, Mapping):
        return result
    return None


def status_for_result(result: Any) -> str:
    """ok when the tool result is a normal payload. error on isError or an error object."""
    data = _result_mapping(result)
    if data is None:
        return "ok"
    if data.get("isError") is True or data.get("is_error") is True:
        return "error"
    payload = _payload_object(data)
    if isinstance(payload, Mapping):
        if payload.get("ok") is False:
            return "error"
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return "error"
        if error not in (None, "", False):
            return "error"
    return "ok"


def emit_tool_line(path: str, params: Mapping[str, Any] | None, status: str) -> None:
    _ensure_log()
    _LOG.info("%s", format_tool_line(path, params, status))


class ToolCallLog:
    """MCP middleware: one line for each tools/call on this path."""

    def __init__(self, path: str) -> None:
        self.path = path

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if getattr(ctx, "method", None) != "tools/call":
            return await call_next(ctx)
        params = getattr(ctx, "params", None)
        try:
            result = await call_next(ctx)
        except Exception:
            emit_tool_line(self.path, params, "error")
            raise
        emit_tool_line(self.path, params, status_for_result(result))
        return result
