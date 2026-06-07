import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace
import httpx

from dashboard.api import app

client = TestClient(app)
HEADERS = {"X-API-Key": "test-key"}


def test_ollama_health_running_and_model_exists(monkeypatch):
    # Mock successful response with the model
    async def fake_list(self):
        return SimpleNamespace(
            models=[
                SimpleNamespace(model="llama3.2:latest"),
                SimpleNamespace(model="mistral:latest"),
            ]
        )

    monkeypatch.setattr("ollama.AsyncClient.list", fake_list)

    response = client.get("/api/settings/ollama/health?model=llama3.2", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is True
    assert data["model_exists"] is True


def test_ollama_health_running_but_model_missing(monkeypatch):
    # Mock successful response without the model
    async def fake_list(self):
        return SimpleNamespace(models=[SimpleNamespace(model="mistral:latest")])

    monkeypatch.setattr("ollama.AsyncClient.list", fake_list)

    response = client.get("/api/settings/ollama/health?model=llama3.2", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is True
    assert data["model_exists"] is False


def test_ollama_health_not_running(monkeypatch):
    # Mock connection error
    async def fake_list(self):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr("ollama.AsyncClient.list", fake_list)

    response = client.get("/api/settings/ollama/health?model=llama3.2", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["model_exists"] is False


def test_ollama_pull_model(monkeypatch):
    async def fake_progress():
        yield {"status": "pulling manifest"}
        yield {"status": "success"}

    async def fake_pull(self, model_name, stream=True):
        assert model_name == "llama3.2"
        assert stream is True
        return fake_progress()

    monkeypatch.setattr("ollama.AsyncClient.pull", fake_pull)

    response = client.post(
        "/api/settings/ollama/pull",
        json={"model": "llama3.2"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    content = response.text
    assert '{"status": "pulling manifest"}' in content
    assert '{"status": "success"}' in content
