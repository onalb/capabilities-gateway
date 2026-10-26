"""Environment for the local capabilities gateway."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = Path(os.environ.get("CAPABILITIES_SKILLS_DIR", str(ROOT / "skills")))

DEFAULT_VACANCY_MCP_URL = (
    "https://vacancy-agent.purplegrass-79f82a02.eastus.azurecontainerapps.io/mcp"
)


def vacancy_mcp_url() -> str:
    return os.environ.get("VACANCY_MCP_URL", DEFAULT_VACANCY_MCP_URL).strip().rstrip("/")


def port() -> int:
    raw = os.environ.get("PORT", "8010").strip() or "8010"
    return int(raw)
