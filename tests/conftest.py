"""One MCP lifespan for the whole test session.

The streamable HTTP session manager can only be started once per server.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from capabilities_gateway.app import app
from capabilities_gateway.deal.predict import reset_predict_state
from capabilities_gateway.deal.vault import reset_memory


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as http:
        yield http


@pytest.fixture(autouse=True)
def _reset_vault_memory(monkeypatch):
    monkeypatch.delenv("TOOLS_LAMBDA_ARN", raising=False)
    reset_memory()
    reset_predict_state()
    yield
    reset_memory()
    reset_predict_state()
