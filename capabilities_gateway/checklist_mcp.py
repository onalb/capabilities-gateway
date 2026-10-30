"""Register the four checklist tools on the one MCP route.

``route`` (deal or vacancy) is stamped by the calling app on every call —
the same argument that selects the permit allowlist. The app injects the
checklist and last work tool; this server does not keep state.
"""

from __future__ import annotations

from typing import Any

from capabilities_gateway.invoke import call_tool


def mount_checklist_tools(mcp: Any) -> None:

    @mcp.tool()
    def create_plan(
        tasks: str | list | dict | None = None,
        checklist: list | None = None,
        last_work_tool: str = "",
        last_work_status: str = "",
        ran_ok: list[str] | None = None,
        status_since_work: bool = False,
        route: str = "",
    ) -> dict:
        """Store this turn's checklist once. A second call is rejected.

        The app sends checklist, last_work_tool, and last_work_status.
        This server does not keep the checklist.
        """
        return call_tool(
            "create_plan",
            {
                "tasks": tasks,
                "checklist": checklist,
                "last_work_tool": last_work_tool,
                "last_work_status": last_work_status,
                "ran_ok": ran_ok,
                "status_since_work": status_since_work,
            },
            route=route,
        )

    @mcp.tool()
    def update_plan(
        tasks: str | list | dict | None = None,
        checklist: list | None = None,
        last_work_tool: str = "",
        last_work_status: str = "",
        ran_ok: list[str] | None = None,
        status_since_work: bool = False,
        route: str = "",
    ) -> dict:
        """Replace remaining work. Keeps completed and incomplete rows.

        Rejects an empty replacement and a call with no checklist
        (except the planless seed on the deal route).
        """
        return call_tool(
            "update_plan",
            {
                "tasks": tasks,
                "checklist": checklist,
                "last_work_tool": last_work_tool,
                "last_work_status": last_work_status,
                "ran_ok": ran_ok,
                "status_since_work": status_since_work,
            },
            route=route,
        )

    @mcp.tool()
    def update_plan_status(
        tasks: str | list | dict | None = None,
        checklist: list | None = None,
        last_work_tool: str = "",
        last_work_status: str = "",
        ran_ok: list[str] | None = None,
        status_since_work: bool = False,
        route: str = "",
    ) -> dict:
        """Apply statuses to the existing rows. A wholly new list is rejected.

        status_since_work is true when this turn already called
        update_plan_status and no work tool has run since that call.
        """
        return call_tool(
            "update_plan_status",
            {
                "tasks": tasks,
                "checklist": checklist,
                "last_work_tool": last_work_tool,
                "last_work_status": last_work_status,
                "ran_ok": ran_ok,
                "status_since_work": status_since_work,
            },
            route=route,
        )

    @mcp.tool()
    def reflection(
        analysis: str = "",
        need_replan: bool = False,
        checklist: list | None = None,
        last_work_tool: str = "",
        last_work_status: str = "",
        ran_ok: list[str] | None = None,
        status_since_work: bool = False,
        route: str = "",
    ) -> dict:
        """Store need_replan. Does not change the checklist.

        Hint sentences are appended by the calling app, not here.
        """
        return call_tool(
            "reflection",
            {
                "analysis": analysis,
                "need_replan": need_replan,
                "checklist": checklist,
                "last_work_tool": last_work_tool,
                "last_work_status": last_work_status,
                "ran_ok": ran_ok,
                "status_since_work": status_since_work,
            },
            route=route,
        )