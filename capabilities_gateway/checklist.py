"""Stateless checklist tools for /mcp/deal and /mcp/vacancy.

The app holds the rows. Each call sends the current checklist plus the last
work tool and returns the next checklist. Nothing is stored here.

`ran_ok` and `status_since_work` are harness fields the app computes from this
turn's traces. The model does not type them. They exist so a stateless call
can keep the deal rules: untagged status inference after every successful work
tool, and a second update_plan_status with no intervening work tool.
"""

from __future__ import annotations

import json
import re
from typing import Any

DEAL_WORK_TOOLS = frozenset(
    {
        "query_units",
        "compute_income",
        "compute_noi",
        "compute_cap_rate",
        "osm_geocode",
        "web_search",
        "publish_memo",
        "ask_prediction_agent",
    }
)
VACANCY_WORK_TOOLS = frozenset(
    {
        "parse_rent_roll_file",
        "fit_vacancy",
        "load_fit",
        "list_trained_properties",
        "save_fit",
        "delete_fit",
        "score_vacancy",
    }
)

_TASK_STATUSES = ("completed", "incomplete", "in_progress", "pending")
_TERMINAL_STATUSES = frozenset({"completed", "incomplete"})
_NUM_PREFIX = re.compile(r"^\s*\d+[.)\-:]\s*")
_ITEM_BREAK = re.compile(r"(?:^|\s+)(?=\d+[.)\-:]\s+\S)")
_BULLET_PREFIX = re.compile(r"^[-*+]\s+")
_LEAD_TAG = re.compile(r"^(?:\[(?P<br>[^\]]*)\]|\*\*(?P<bd>[^*]+)\*\*)\s*", re.I)
_ANY_TAG = re.compile(r"\[(?P<br>[^\]]*)\]|\*\*(?P<bd>[^*]+)\*\*", re.I)
_TRAIL_WORD = re.compile(
    r"[\s:;(—–-]+(?P<w>completed|complete|done|finished|incomplete|incomplet|"
    r"cannot_complete|unanswerable|unavailable|blocked|"
    r"in[_-]?progress|pending|todo)\s*$",
    re.I,
)
_STATUS_MAP = {
    "completed": "completed",
    "complete": "completed",
    "done": "completed",
    "finished": "completed",
    "checked": "completed",
    "x": "completed",
    "✓": "completed",
    "✔": "completed",
    "✅": "completed",
    "in_progress": "in_progress",
    "in-progress": "in_progress",
    "inprogress": "in_progress",
    "doing": "in_progress",
    "current": "in_progress",
    "wip": "in_progress",
    "working": "in_progress",
    "pending": "pending",
    "todo": "pending",
    "open": "pending",
    "unchecked": "pending",
    "incomplete": "incomplete",
    "incomplet": "incomplete",
    "cannot_complete": "incomplete",
    "unanswerable": "incomplete",
    "unavailable": "incomplete",
    "blocked": "incomplete",
    "n/a": "incomplete",
    "na": "incomplete",
    "": "pending",
}
_HEADLINE_COUNT_RE = re.compile(
    r"\b(unit_count|unit count|occupied_count|vacant_count|occupancy_pct|"
    r"occupancy|occupied|vacant|units|mtm_count|mtm|month[\s-]*to[\s-]*month|"
    r"avg_sqft|average\s+sqft|typical unit size|square footage|\bsqft\b)\b",
    re.I,
)
_LIST_UNITS_RE = re.compile(
    r"\b(list|enumerat\w*|unit rows|unit ids?|row-by-row|names of)\b",
    re.I,
)
_INCOME_ITEM_RE = re.compile(
    r"\b(compute[\s_-]*income|in[\s_-]*place|monthly)\b",
    re.I,
)
_QUERY_UNITS_PHRASE_RE = re.compile(r"\bquery[\s_-]*units\b", re.I)
_DEAL_NON_HEADLINE_RE = re.compile(
    r"\b(compute_income|compute_noi|compute_cap_rate|ask_vacancy|"
    r"ask_prediction_agent|osm_geocode|web_search|publish_memo|score_gcr|reflection)\b",
    re.I,
)

PLAN_TOOL_NAMES = frozenset(
    {"create_plan", "update_plan", "update_plan_status", "reflection"}
)


def work_tools_for(route: str) -> frozenset[str]:
    if route == "vacancy":
        return VACANCY_WORK_TOOLS
    return DEAL_WORK_TOOLS


def _norm_task_text(raw: str) -> str:
    text = re.sub(r"\s+", " ", str(raw or "").strip()).strip(" -:;—–,")
    text = re.sub(r"\s*\(\s*MCP\s*\)", "", text, flags=re.I)
    return text.strip(" -:;—–,")


def _token_status(token: str) -> str | None:
    raw = str(token or "").strip().lower()
    if raw in {"x", "✓", "✔", "✅"}:
        return "completed"
    key = re.sub(r"[\s\-]+", "_", raw)
    if key in _STATUS_MAP:
        return _STATUS_MAP[key]
    return _STATUS_MAP.get(key.replace("_", ""))


def _coerce_status(value: Any) -> str:
    return _token_status(str(value or "")) or "pending"


def _split_status(text: str) -> tuple[str | None, str]:
    blob = str(text or "").strip()
    found: str | None = None
    lead = _LEAD_TAG.match(blob)
    if lead:
        tok = lead.group("br") if lead.group("br") is not None else lead.group("bd")
        status = _token_status(tok if tok is not None else "")
        if status:
            found = status
            blob = blob[lead.end() :].strip()

    def _keep_or_strip(match: re.Match[str]) -> str:
        nonlocal found
        tok = match.group("br") if match.group("br") is not None else match.group("bd")
        status = _token_status(tok if tok is not None else "")
        if not status:
            return match.group(0)
        if found is None:
            found = status
        return " "

    blob = _ANY_TAG.sub(_keep_or_strip, blob)
    if found is None:
        trail = _TRAIL_WORD.search(blob)
        if trail:
            found = _token_status(trail.group("w"))
            blob = blob[: trail.start()].strip()
    return found, _norm_task_text(blob)


def _task_item(text: Any, status: Any = None) -> dict[str, str] | None:
    raw = str(text or "").strip()
    stripped = _BULLET_PREFIX.sub("", _NUM_PREFIX.sub("", raw))
    tagged, body = _split_status(stripped)
    if not body:
        return None
    explicit = None
    if status is not None and str(status).strip() != "":
        explicit = _token_status(str(status))
    chosen = explicit or tagged
    return {"text": body, "status": chosen if chosen in _TASK_STATUSES else "pending"}


def _task_lines(blob: str) -> list[str]:
    out: list[str] = []
    for line in str(blob or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in _ITEM_BREAK.split(line) if part and part.strip()]
        out.extend(parts or [line])
    return out


def _split_joined_tool_blob(blob: str, work_tools: frozenset[str]) -> str:
    names = sorted(work_tools, key=len, reverse=True)
    if not names:
        return str(blob or "")
    alt = "|".join(re.escape(name) for name in names)
    mcp = r"(?:\s*\(\s*MCP\s*\))?"
    tagged = r"(?:\s*\[[^\]]+\])?"
    return re.sub(
        rf"((?:{alt}){mcp}{tagged})\s*(?:,|/|;|\band\b|\bthen\b|\+)\s*(?=(?:{alt}))",
        r"\1\n",
        str(blob or ""),
        flags=re.I,
    )


def _explode_task_items(
    items: list[dict[str, str]], work_tools: frozenset[str]
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in items:
        blob = _split_joined_tool_blob(str(item.get("text") or ""), work_tools)
        parts = [part for part in (_task_item(line) for line in _task_lines(blob)) if part]
        if len(parts) <= 1:
            out.append({"text": item["text"], "status": item["status"]})
            continue
        for index, part in enumerate(parts):
            if index == 0 and item.get("status") in _TASK_STATUSES and part["status"] == "pending":
                part = {**part, "status": item["status"]}
            out.append(part)
    return out


def parse_task_items(tasks: Any, work_tools: frozenset[str]) -> list[dict[str, str]]:
    if isinstance(tasks, dict) and "tasks" in tasks:
        return parse_task_items(tasks.get("tasks"), work_tools)
    if isinstance(tasks, (list, tuple)):
        items: list[dict[str, str]] = []
        for row in tasks:
            if isinstance(row, dict):
                item = _task_item(
                    row.get("text") or row.get("task") or row.get("title") or "",
                    row.get("status"),
                )
            else:
                item = _task_item(row)
            if item:
                items.append(item)
        return items
    blob = str(tasks or "").strip()
    if blob.startswith("[") or blob.startswith("{"):
        try:
            return parse_task_items(json.loads(blob), work_tools)
        except json.JSONDecodeError:
            pass
    blob = _split_joined_tool_blob(blob, work_tools)
    items = [item for item in (_task_item(line) for line in _task_lines(blob)) if item]
    return _explode_task_items(items, work_tools)


def _coerce_checklist(value: Any, work_tools: frozenset[str]) -> list[dict[str, str]]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return parse_task_items(text, work_tools)
    if isinstance(value, dict) and "checklist" in value:
        return _coerce_checklist(value.get("checklist"), work_tools)
    if not isinstance(value, (list, tuple)):
        return []
    out: list[dict[str, str]] = []
    for row in value:
        if isinstance(row, dict) and ("text" in row or "task" in row or "title" in row):
            item = _task_item(
                row.get("text") or row.get("task") or row.get("title") or "",
                row.get("status"),
            )
        else:
            item = _task_item(row)
        if item:
            out.append(item)
    return out


def format_checklist(items: list[dict[str, str]]) -> str:
    if not items:
        return ""
    return "\n".join(f"{index}. [{item['status']}] {item['text']}" for index, item in enumerate(items, 1))


def _fingerprint(items: list[dict[str, str]]) -> list[tuple[str, str]]:
    return [(item["text"], item["status"]) for item in items]


def checklist_diff(previous: list[dict[str, str]], current: list[dict[str, str]]) -> dict[str, Any]:
    prev_map = {item["text"]: item for item in previous}
    newly_completed = [
        item["text"]
        for item in current
        if item["status"] == "completed" and (prev_map.get(item["text"]) or {}).get("status") != "completed"
    ]
    newly_incomplete = [
        item["text"]
        for item in current
        if item["status"] == "incomplete"
        and (prev_map.get(item["text"]) or {}).get("status") != "incomplete"
    ]
    new_items = [item["text"] for item in current if item["text"] not in prev_map]
    return {
        "initial": not previous,
        "changed": _fingerprint(previous) != _fingerprint(current),
        "completed": newly_completed,
        "incomplete": newly_incomplete,
        "new": new_items,
        "in_progress": [item["text"] for item in current if item["status"] == "in_progress"],
        "in_progress_was": [item["text"] for item in previous if item["status"] == "in_progress"],
    }


def _task_key(text: str) -> str:
    return _norm_task_text(text).lower()


def merge_replan_checklist(
    previous: list[dict[str, str]], incoming: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Keep completed/incomplete rows; append new work. Do not reset done items."""
    kept = [
        {"text": item["text"], "status": item["status"]}
        for item in previous
        if item.get("status") in _TERMINAL_STATUSES
    ]
    seen = {_task_key(item["text"]) for item in kept}
    added: list[dict[str, str]] = []
    for item in incoming:
        key = _task_key(item["text"])
        if not key or key in seen:
            continue
        status = item.get("status") or "pending"
        if status in _TERMINAL_STATUSES:
            status = "pending"
        added.append({"text": item["text"], "status": status})
        seen.add(key)
    return kept + added


def apply_status_updates(
    previous: list[dict[str, str]], incoming: list[dict[str, str]]
) -> tuple[list[dict[str, str]], int]:
    incoming_by_key: dict[str, dict[str, str]] = {}
    for item in incoming:
        incoming_by_key[_task_key(item["text"])] = item
    matched = 0
    result: list[dict[str, str]] = []
    for item in previous:
        key = _task_key(item["text"])
        hit = incoming_by_key.get(key)
        if hit:
            matched += 1
            result.append({"text": item["text"], "status": hit["status"]})
        else:
            result.append({"text": item["text"], "status": item["status"]})
    return result, matched


def _text_has_status_tag(raw: str) -> bool:
    stripped = _BULLET_PREFIX.sub("", _NUM_PREFIX.sub("", str(raw or "").strip()))
    tagged, _ = _split_status(stripped)
    return tagged is not None


def _tasks_omit_status_tags(tasks: Any) -> bool:
    if isinstance(tasks, dict) and "tasks" in tasks:
        if str(tasks.get("status") or "").strip():
            return False
        return _tasks_omit_status_tags(tasks.get("tasks"))
    if isinstance(tasks, (list, tuple)):
        if not tasks:
            return False
        for row in tasks:
            if isinstance(row, dict):
                if str(row.get("status") or "").strip():
                    return False
                blob = str(row.get("text") or row.get("task") or row.get("title") or "")
                if _text_has_status_tag(blob):
                    return False
            elif _text_has_status_tag(str(row)):
                return False
        return True
    blob = str(tasks or "").strip()
    if not blob:
        return False
    if blob.startswith("[") or blob.startswith("{"):
        try:
            return _tasks_omit_status_tags(json.loads(blob))
        except json.JSONDecodeError:
            pass
    lines = _task_lines(blob)
    if not lines:
        return False
    return not any(_text_has_status_tag(line) for line in lines)


def _is_headline_count_intent(text: str) -> bool:
    blob = _norm_task_text(text)
    lower = blob.lower()
    if not lower or _DEAL_NON_HEADLINE_RE.search(lower):
        return False
    if _LIST_UNITS_RE.search(lower):
        return False
    if re.search(r"\bquery_units\b", lower):
        return True
    return bool(_HEADLINE_COUNT_RE.search(lower))


def _tool_or_item_label(text: str, work_tools: frozenset[str], *, map_phrases: bool) -> str:
    blob = _norm_task_text(text)
    lower = blob.lower()
    for name in sorted(work_tools, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])", lower):
            return name
    if map_phrases:
        if _INCOME_ITEM_RE.search(lower):
            return "compute_income"
        if _is_headline_count_intent(text) or _QUERY_UNITS_PHRASE_RE.search(lower):
            return "query_units"
    return blob


def _infer_completed_from_untagged(
    previous: list[dict[str, str]],
    incoming: list[dict[str, str]],
    work_tools: frozenset[str],
    ran_ok: set[str],
    *,
    map_phrases: bool,
) -> list[dict[str, str]]:
    keys = {_task_key(item["text"]) for item in incoming}
    incoming_tools = {
        _tool_or_item_label(item["text"], work_tools, map_phrases=map_phrases)
        for item in incoming
        if _tool_or_item_label(item["text"], work_tools, map_phrases=map_phrases) in work_tools
    }
    out: list[dict[str, str]] = []
    inferred = False
    for item in previous:
        text = item.get("text") or ""
        status = item.get("status") or "pending"
        label = _tool_or_item_label(text, work_tools, map_phrases=map_phrases)
        hit = _task_key(text) in keys or label in incoming_tools
        if hit and status not in _TERMINAL_STATUSES and label in ran_ok:
            status = "completed"
            inferred = True
        out.append({"text": text, "status": status})
    if inferred:
        for index, item in enumerate(out):
            if item["status"] not in _TERMINAL_STATUSES:
                out[index] = {"text": item["text"], "status": "in_progress"}
                break
    return out


def plan_log_message(items: list[dict[str, str]], diff: dict[str, Any], *, tool: str) -> str:
    body = format_checklist(items) or "(empty checklist)"
    if diff.get("initial"):
        return f"{tool} — initial checklist\n{body}"
    if not diff.get("changed"):
        return f"{tool} — Plan unchanged\n{body}"
    bits: list[str] = []
    if diff.get("completed"):
        bits.append("completed: " + "; ".join(diff["completed"]))
    if diff.get("incomplete"):
        bits.append("incomplete: " + "; ".join(diff["incomplete"]))
    if diff.get("new"):
        bits.append("new: " + "; ".join(diff["new"]))
    was = list(diff.get("in_progress_was") or [])
    now = list(diff.get("in_progress") or [])
    if was != now:
        bits.append(f"in_progress: {', '.join(now) or '(none)'} (was {', '.join(was) or '(none)'})")
    delta = "; ".join(bits) if bits else "status/order change"
    return f"{tool} — checklist updated ({delta})\n{body}"


def _rows(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"text": item["text"], "status": item["status"]} for item in items]


def _envelope(
    *,
    ok: bool,
    rejected: bool,
    checklist: list[dict[str, str]],
    reason: str,
    text: str,
    plan: str = "",
    log: str = "",
    diff: dict[str, Any] | None = None,
    changed: bool = False,
    hint: str = "",
    **extra: Any,
) -> dict[str, Any]:
    rows = _rows(checklist)
    body: dict[str, Any] = {
        "ok": ok,
        "rejected": rejected,
        "checklist": rows,
        "items": rows,
        "reason": reason,
        "text": text,
        "plan": plan,
        "log": log,
        "diff": diff if diff is not None else checklist_diff(rows, rows),
        "changed": changed,
    }
    if hint:
        body["hint"] = hint
    body.update(extra)
    return body


def _next_open(
    items: list[dict[str, str]], work_tools: frozenset[str], *, map_phrases: bool
) -> tuple[str, bool]:
    """Return (next work-tool name or '', all_terminal)."""
    for item in items:
        if item.get("status") in _TERMINAL_STATUSES:
            continue
        label = _tool_or_item_label(str(item.get("text") or ""), work_tools, map_phrases=map_phrases)
        if label in work_tools:
            return label, False
        return "", False
    return "", True


def _consecutive_text(next_work: str, all_terminal: bool) -> str:
    if all_terminal:
        nxt = "Next is the pending work tool — do not loop update_plan_status."
    elif next_work:
        nxt = f"Next is {next_work} — do not loop update_plan_status."
    else:
        nxt = "Next is the pending work tool — do not loop update_plan_status."
    return (
        "Rejected consecutive update_plan_status with no intervening work tool. " + nxt
    )


def _ran_ok(arguments: dict[str, Any], last_work_tool: str, last_work_status: str, work_tools: frozenset[str]) -> set[str]:
    raw = arguments.get("ran_ok")
    names: set[str] = set()
    if isinstance(raw, (list, tuple, set)):
        for item in raw:
            name = str(item or "").strip()
            if name in work_tools:
                names.add(name)
        return names
    if last_work_tool in work_tools and last_work_status != "error":
        names.add(last_work_tool)
    return names


def _work_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in {"ok", "error"}:
        return status
    return ""


def apply_checklist(route: str, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Run one checklist tool. `route` is deal or vacancy."""
    args = dict(arguments or {})
    route_name = "vacancy" if route == "vacancy" else "deal"
    work_tools = work_tools_for(route_name)
    map_phrases = route_name == "deal"
    checklist = _coerce_checklist(args.get("checklist"), work_tools)
    last_work_tool = str(args.get("last_work_tool") or "").strip()
    last_work_status = _work_status(args.get("last_work_status"))
    ran_ok = _ran_ok(args, last_work_tool, last_work_status, work_tools)
    status_since_work = bool(args.get("status_since_work"))
    if name == "create_plan":
        return _create_plan(args.get("tasks"), checklist)
    if name == "update_plan":
        return _update_plan(
            args.get("tasks"),
            checklist,
            work_tools,
            route_name=route_name,
        )
    if name == "update_plan_status":
        return _update_plan_status(
            args.get("tasks"),
            checklist,
            work_tools,
            map_phrases=map_phrases,
            ran_ok=ran_ok,
            status_since_work=status_since_work,
        )
    if name == "reflection":
        return _reflection(args.get("analysis"), args.get("need_replan"), checklist)
    return _envelope(
        ok=False,
        rejected=True,
        checklist=checklist,
        reason="unknown_tool",
        text=f"Unknown checklist tool: {name}",
        plan=format_checklist(checklist),
    )


def _create_plan(tasks: Any, previous: list[dict[str, str]]) -> dict[str, Any]:
    if previous:
        plan = format_checklist(previous)
        hint = (
            "Checklist already exists. Use update_plan_status for statuses, "
            "or update_plan to replace the list — do not call create_plan again."
        )
        text = f"{hint}\n{plan}" if plan else hint
        return _envelope(
            ok=False,
            rejected=True,
            checklist=previous,
            reason="already_exists",
            text=text,
            plan=plan,
            log="",
            diff=checklist_diff(previous, previous),
            changed=False,
            hint=hint,
        )
    items = parse_task_items(tasks, DEAL_WORK_TOOLS | VACANCY_WORK_TOOLS)
    # Parse with both menus so a caller that has not selected a route still
    # splits joined names. The route-specific parser below replaces this.
    return _create_plan_parsed(tasks, previous)


def _create_plan_parsed(tasks: Any, previous: list[dict[str, str]]) -> dict[str, Any]:
    raise AssertionError("replaced")


def _create(route_tools: frozenset[str], tasks: Any, previous: list[dict[str, str]]) -> dict[str, Any]:
    if previous:
        plan = format_checklist(previous)
        hint = (
            "Checklist already exists. Use update_plan_status for statuses, "
            "or update_plan to replace the list — do not call create_plan again."
        )
        text = f"{hint}\n{plan}" if plan else hint
        return _envelope(
            ok=False,
            rejected=True,
            checklist=previous,
            reason="already_exists",
            text=text,
            plan=plan,
            log="",
            diff=checklist_diff(previous, previous),
            changed=False,
            hint=hint,
        )
    items = parse_task_items(tasks, route_tools)
    diff = checklist_diff([], items)
    plan = format_checklist(items)
    log = plan_log_message(items, diff, tool="create_plan")
    text = f"Plan stored (initial checklist):\n{plan}" if plan else "Plan stored (empty checklist)."
    return _envelope(
        ok=True,
        rejected=False,
        checklist=items,
        reason="created",
        text=text,
        plan=plan,
        log=log,
        diff=diff,
        changed=True,
    )


def _update_plan(
    tasks: Any,
    previous: list[dict[str, str]],
    work_tools: frozenset[str],
    *,
    route_name: str,
) -> dict[str, Any]:
    if not previous:
        incoming_seed = parse_task_items(tasks, work_tools)
        if route_name == "deal" and incoming_seed:
            # Planless escape hatch: a single-tool turn has no create_plan on
            # its menu, so the first plan tool it can call is update_plan.
            # Seed the checklist exactly like create_plan would have.
            diff = checklist_diff([], incoming_seed)
            plan = format_checklist(incoming_seed)
            log = plan_log_message(incoming_seed, diff, tool="update_plan")
            return _envelope(
                ok=True,
                rejected=False,
                checklist=incoming_seed,
                reason="seeded",
                text=f"Plan stored (planless seed):\n{plan}",
                plan=plan,
                log=log,
                diff=diff,
                changed=True,
            )
        hint = "No checklist yet. Call create_plan first with the full numbered list."
        return _envelope(
            ok=False,
            rejected=True,
            checklist=[],
            reason="no_checklist",
            text=hint,
            hint=hint,
            diff=checklist_diff([], []),
        )
    incoming = parse_task_items(tasks, work_tools)
    if not incoming:
        plan = format_checklist(previous)
        hint = "update_plan needs a numbered list of new tasks."
        return _envelope(
            ok=False,
            rejected=True,
            checklist=previous,
            reason="empty_replacement",
            text=f"Kept original checklist (empty replacement).\n{plan}",
            plan=plan,
            hint=hint,
            diff=checklist_diff(previous, previous),
        )
    items = merge_replan_checklist(previous, incoming)
    diff = checklist_diff(previous, items)
    plan = format_checklist(items)
    log = plan_log_message(items, diff, tool="update_plan")
    return _envelope(
        ok=True,
        rejected=False,
        checklist=items,
        reason="replaced",
        text=f"Plan replaced (kept completed/incomplete):\n{log}",
        plan=plan,
        log=log,
        diff=diff,
        changed=bool(diff["changed"]),
        replaced=True,
        kept_completed=[item["text"] for item in items if item["status"] in _TERMINAL_STATUSES],
    )


def _update_plan_status(
    tasks: Any,
    previous: list[dict[str, str]],
    work_tools: frozenset[str],
    *,
    map_phrases: bool,
    ran_ok: set[str],
    status_since_work: bool,
) -> dict[str, Any]:
    if not previous:
        hint = "No checklist yet. Call create_plan first with the full numbered list."
        return _envelope(
            ok=False,
            rejected=True,
            checklist=[],
            reason="no_checklist",
            text=hint,
            hint=hint,
            diff=checklist_diff([], []),
        )
    if status_since_work:
        plan = format_checklist(previous)
        next_work, all_terminal = _next_open(previous, work_tools, map_phrases=map_phrases)
        hint = _consecutive_text(next_work, all_terminal)
        log = f"update_plan_status — Plan unchanged\n{hint}\n{plan}"
        return _envelope(
            ok=False,
            rejected=True,
            checklist=previous,
            reason="consecutive_status",
            text=f"Plan unchanged. {hint}\n{plan}",
            plan=plan,
            log=log,
            diff=checklist_diff(previous, previous),
            hint=hint,
            next_work=next_work,
            all_terminal=all_terminal,
        )
    previous = _explode_task_items(previous, work_tools)
    incoming = parse_task_items(tasks, work_tools)
    if incoming and _tasks_omit_status_tags(tasks):
        items = _infer_completed_from_untagged(
            previous, incoming, work_tools, ran_ok, map_phrases=map_phrases
        )
        incoming_keys = {_task_key(item["text"]) for item in incoming}
        matched = sum(1 for item in previous if _task_key(item["text"]) in incoming_keys)
    else:
        items, matched = apply_status_updates(previous, incoming)
    diff = checklist_diff(previous, items)
    if not matched and incoming:
        diff = {**diff, "replaced_ignored": True}
    plan = format_checklist(items)
    log = plan_log_message(items, diff, tool="update_plan_status")
    if not matched and incoming:
        text = (
            "Kept original checklist (incoming items did not match). "
            "Use update_plan_status with the same items and new statuses — "
            "do not replace the list here. Call update_plan to write a new plan.\n"
            f"{plan}"
        )
        return _envelope(
            ok=False,
            rejected=True,
            checklist=previous,
            reason="new_list",
            text=text,
            plan=format_checklist(previous),
            log=log,
            diff=diff,
            changed=False,
            matched=matched,
            hint="Call update_plan to write a new plan.",
        )
    text = f"Plan updated:\n{log}" if diff["changed"] else log
    return _envelope(
        ok=True,
        rejected=False,
        checklist=items,
        reason="status_applied",
        text=text,
        plan=plan,
        log=log,
        diff=diff,
        changed=bool(diff["changed"]),
        matched=matched,
    )


def _reflection(analysis: Any, need_replan: Any, checklist: list[dict[str, str]]) -> dict[str, Any]:
    text = str(analysis or "").strip()
    flag = bool(need_replan)
    plan = format_checklist(checklist)
    stored = f"Reflection stored: {text}" if text else "Reflection stored."
    return _envelope(
        ok=True,
        rejected=False,
        checklist=checklist,
        reason="reflected",
        text=stored,
        plan=plan,
        log="",
        diff=checklist_diff(checklist, checklist),
        changed=False,
        need_replan=flag,
        analysis=text,
    )


def apply_checklist(route: str, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Run one checklist tool. `route` is deal or vacancy."""
    args = dict(arguments or {})
    route_name = "vacancy" if route == "vacancy" else "deal"
    work_tools = work_tools_for(route_name)
    map_phrases = route_name == "deal"
    checklist = _coerce_checklist(args.get("checklist"), work_tools)
    last_work_tool = str(args.get("last_work_tool") or "").strip()
    last_work_status = _work_status(args.get("last_work_status"))
    ran_ok = _ran_ok(args, last_work_tool, last_work_status, work_tools)
    status_since_work = bool(args.get("status_since_work"))
    if name == "create_plan":
        return _create(work_tools, args.get("tasks"), checklist)
    if name == "update_plan":
        return _update_plan(
            args.get("tasks"),
            checklist,
            work_tools,
            route_name=route_name,
        )
    if name == "update_plan_status":
        return _update_plan_status(
            args.get("tasks"),
            checklist,
            work_tools,
            map_phrases=map_phrases,
            ran_ok=ran_ok,
            status_since_work=status_since_work,
        )
    if name == "reflection":
        return _reflection(args.get("analysis"), args.get("need_replan"), checklist)
    return _envelope(
        ok=False,
        rejected=True,
        checklist=checklist,
        reason="unknown_tool",
        text=f"Unknown checklist tool: {name}",
        plan=format_checklist(checklist),
    )
