"""Register the four checklist tools on one MCP server."""

from __future__ import annotations

from typing import Any

from capabilities_gateway.checklist import apply_checklist


def mount_checklist_tools(mcp: Any, route: str) -> None:
    """Model args are tasks / analysis. The app injects the checklist and last work tool."""

    @mcp.tool()
    def create_plan(
        tasks: str | list | dict | None = None,
        checklist: list | None = None,
        last_work_tool: str = "",
        last_work_status: str = "",
        ran_ok: list[str] | None = None,
        status_since_work: bool = False,
    ) -> dict:
        """Store this turn's checklist once. A second call is rejected.

        The app sends checklist, last_work_tool, and last_work_status.
        This server does not keep the checklist.
        """
        return apply_checklist(
            route,
            "create_plan",
            {
                "tasks": tasks,
                "checklist": checklist,
                "last_work_tool": last_work_tool,
                "last_work_status": last_work_status,
                "ran_ok": ran_ok,
                "status_since_work": status_since_work,
            },
        )

    @mcp.tool()
    def update_plan(
        tasks: str | list | dict | None = None,
        checklist: list | None = None,
        last_work_tool: str = "",
        last_work_status: str = "",
        ran_ok: list[str] | None = None,
        status_since_work: bool = False,
    ) -> dict:
        """Replace remaining work. Keeps completed and incomplete rows.

        Rejects an empty replacement and a call with no checklist.
        On /mcp/deal, a failed web_search whose replacement is only more
        search tasks is ok and does not install that list.
        """
        return apply_checklist(
            route,
            "update_plan",
            {
                "tasks": tasks,
                "checklist": checklist,
                "last_work_tool": last_work_tool,
                "last_work_status": last_work_status,
                "ran_ok": ran_ok,
                "status_since_work": status_since_work,
            },
        )

    @mcp.tool()
    def update_plan_status(
        tasks: str | list | dict | None = None,
        checklist: list | None = None,
        last_work_tool: str = "",
        last_work_status: str = "",
        ran_ok: list[str] | None = None,
        status_since_work: bool = False,
    ) -> dict:
        """Apply statuses to the existing rows. A wholly new list is rejected.

        status_since_work is true when this turn already called
        update_plan_status and no work tool has run since that call.
        """
        return apply_checklist(
            route,
            "update_plan_status",
            {
                "tasks": tasks,
                "checklist": checklist,
                "last_work_tool": last_work_tool,
                "last_work_status": last_work_status,
                "ran_ok": ran_ok,
                "status_since_work": status_since_work,
            },
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
    ) -> dict:
        """Store need_replan. Does not change the checklist.

        Hint sentences are appended by the calling app, not here.
        """
        return apply_checklist(
            route,
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
        )
