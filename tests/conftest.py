"""One MCP lifespan for the whole test session.

The streamable HTTP session manager can only be started once per server.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from capabilities_gateway.app import app
from capabilities_gateway.deal.vault import reset_memory


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as http:
        yield http


@pytest.fixture(autouse=True)
def _reset_vault_memory():
    reset_memory()
    yield
    reset_memory()
