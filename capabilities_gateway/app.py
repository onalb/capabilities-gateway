"""One process, two MCP paths, plus skill markdown."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from capabilities_gateway.deal_mcp import http_app as deal_http_app
from capabilities_gateway.deal_mcp import mcp as deal_mcp
from capabilities_gateway.settings import SKILLS_DIR
from capabilities_gateway.vacancy_mcp import http_app as vacancy_http_app
from capabilities_gateway.vacancy_mcp import mcp as vacancy_mcp

_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

_deal_http = deal_http_app()
_vacancy_http = vacancy_http_app()


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
            "mcp": {"deal": "/mcp/deal", "vacancy": "/mcp/vacancy"},
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
async def lifespan(_app: Starlette):
    async with deal_mcp.session_manager.run():
        async with vacancy_mcp.session_manager.run():
            yield


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/skills", list_skills, methods=["GET"]),
        Route("/skills/{name}", get_skill, methods=["GET"]),
        *_deal_http.routes,
        *_vacancy_http.routes,
    ],
)
