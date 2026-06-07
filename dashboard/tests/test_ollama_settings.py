import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from dashboard.api import app

client = TestClient(app)

# We need to bypass auth for testing, or mock the current user.
# The dashboard tests usually override the dependency.
from dashboard.auth import get_current_user
app.dependency_overrides[get_current_user] = lambda: {"sub": "test-user"}

@patch("httpx.AsyncClient.get")
def test_ollama_health_running_and_model_exists(mock_get):
    # Mock successful response with the model
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"models": [{"name": "llama3.2:latest"}, {"name": "mistral:latest"}]}
    mock_get.return_value = mock_response

    response = client.get("/api/settings/ollama/health?model=llama3.2")
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is True
    assert data["model_exists"] is True

@patch("httpx.AsyncClient.get")
def test_ollama_health_running_but_model_missing(mock_get):
    # Mock successful response without the model
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"models": [{"name": "mistral:latest"}]}
    mock_get.return_value = mock_response

    response = client.get("/api/settings/ollama/health?model=llama3.2")
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is True
    assert data["model_exists"] is False

@patch("httpx.AsyncClient.get")
def test_ollama_health_not_running(mock_get):
    # Mock connection error
    mock_get.side_effect = httpx.ConnectError("Connection refused")

    response = client.get("/api/settings/ollama/health?model=llama3.2")
    assert response.status_code == 200
    data = response.json()
    assert data["running"] is False
    assert data["model_exists"] is False

@patch("httpx.AsyncClient.stream")
def test_ollama_pull_model(mock_stream):
    class MockStreamContextManager:
        async def __aenter__(self):
            mock_response = MagicMock()
            mock_response.status_code = 200
            async def mock_aiter_lines():
                yield '{"status": "pulling manifest"}'
                yield '{"status": "success"}'
            mock_response.aiter_lines = mock_aiter_lines
            return mock_response

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_stream.return_value = MockStreamContextManager()

    response = client.post("/api/settings/ollama/pull", json={"model": "llama3.2"})
    assert response.status_code == 200
    content = response.text
    assert '{"status": "pulling manifest"}' in content
    assert '{"status": "success"}' in content
