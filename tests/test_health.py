"""GET /health reports the package version."""

from capabilities_gateway import __version__


def test_health_reports_version(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["version"] == __version__
