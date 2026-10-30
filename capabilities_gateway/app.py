"""Skills HTTP + the one MCP route. Tool calls go through /mcp with route=deal|vacancy."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from capabilities_gateway.settings import SKILLS_DIR
from capabilities_gateway.mcp_server import http_app as mcp_http_app, mcp

_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _skill_names() -> list[str]:
    if not SKILLS_DIR.is_dir():
        return []
    names = []
    for path in sorted(SKILLS_DIR.iterdir()):
        if path.is_dir() and (path / "SKILL.md").is_file() and _SKILL_NAME.match(path.name):
            names.append(path.name)
    return names


def health(_request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "mcp": "https://credealrentroll-25yvwacjrd.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
            "local_mcp": "/mcp (route=deal|vacancy per call)",
            "skills": "/skills",
        }
    )


def list_skills(_request: Request) -> JSONResponse:
    return JSONResponse({"skills": _skill_names()})


def get_skill(request: Request) -> Response:
    name = str(request.path_params.get("name") or "")
    if not _SKILL_NAME.match(name):
        return JSONResponse({"error": "not_found"}, status_code=404)
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.is_file():
        return JSONResponse({"error": "not_found"}, status_code=404)
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")


@asynccontextmanager
async def _lifespan(_app):
    async with mcp.session_manager.run():
        yield


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/skills", list_skills, methods=["GET"]),
        Route("/skills/{name}", get_skill, methods=["GET"]),
    ],
    lifespan=_lifespan,
)

# The one MCP route: /mcp with route=deal|vacancy stamped per call.
app.router.routes.extend(mcp_http_app().routes)
