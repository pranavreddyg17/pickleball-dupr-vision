import pytest
from fastapi.testclient import TestClient

from duprvision import app as web, core


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DATA", tmp_path)
    monkeypatch.setattr(core, "DB", tmp_path / "duprvision.sqlite3")
    monkeypatch.setattr(web, "DATA", tmp_path)
    monkeypatch.setenv("INVITE_CODE", "")
    monkeypatch.setenv("APP_TIMEZONE", "America/Chicago")
    monkeypatch.setenv("ANALYSIS_ENGINE", "local")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(web.app) as a, TestClient(web.app) as b:
        for client, name in ((a,"Alice"),(b,"Bob")):
            assert client.post("/api/register", json={"email": f"{name}@example.com", "password": "a-long-password", "display_name": name}).status_code == 200
        yield a, b
