import os
os.environ["OSTWIN_API_KEY"] = "DEBUG"

import pytest
import json
from fastapi.testclient import TestClient
from dashboard.api import app

client = TestClient(app)
HEADERS = {"X-API-Key": "DEBUG"}

@pytest.fixture
def mock_channels_config(tmp_path, monkeypatch):
    # Mock CHANNELS_CONFIG_PATH to a temp file
    mock_path = tmp_path / "channels.json"
    import dashboard.routes.channels
    monkeypatch.setattr(dashboard.routes.channels, "CHANNELS_CONFIG_PATH", mock_path)
    return mock_path

def test_list_channels_empty(mock_channels_config):
    response = client.get("/api/channels", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    platforms = [d["platform"] for d in data]
    assert "telegram" in platforms
    assert "discord" in platforms
    assert "slack" in platforms

def test_connect_channel(mock_channels_config):
    response = client.post("/api/channels/telegram/connect", 
                           json={"credentials": {"token": "test-token"}},
                           headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    
    # Verify file was written
    assert mock_channels_config.exists()
    with open(mock_channels_config, "r") as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]["platform"] == "telegram"
        assert data[0]["enabled"] == True
        assert data[0]["credentials"]["token"] == "test-token"
        assert data[0]["pairing_code"] != ""

def test_get_channel(mock_channels_config):
    # First connect
    client.post("/api/channels/telegram/connect", 
                json={"credentials": {"token": "t1"}},
                headers=HEADERS)
    
    response = client.get("/api/channels/telegram", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["platform"] == "telegram"
    assert response.json()["status"] == "connected"

def test_disconnect_channel(mock_channels_config):
    client.post("/api/channels/telegram/connect", 
                json={"credentials": {"token": "t1"}},
                headers=HEADERS)
    response = client.post("/api/channels/telegram/disconnect", headers=HEADERS)
    assert response.status_code == 200
    
    response = client.get("/api/channels/telegram", headers=HEADERS)
    assert response.json()["status"] == "disconnected"

def test_update_settings(mock_channels_config):
    client.post("/api/channels/telegram/connect", 
                json={"credentials": {"token": "t1"}},
                headers=HEADERS)
    response = client.put("/api/channels/telegram/settings", 
                          json={
                              "notification_preferences": {"events": ["plan_started"], "enabled": False},
                              "authorized_users": ["user123"]
                          },
                          headers=HEADERS)
    assert response.status_code == 200
    
    response = client.get("/api/channels/telegram", headers=HEADERS)
    config = response.json()["config"]
    assert config["notification_preferences"]["events"] == ["plan_started"]
    assert config["notification_preferences"]["enabled"] == False
    assert config["authorized_users"] == ["user123"]

def test_pairing_regenerate(mock_channels_config):
    client.post("/api/channels/telegram/connect", 
                json={"credentials": {"token": "t1"}},
                headers=HEADERS)
    res1 = client.get("/api/channels/telegram/pairing", headers=HEADERS)
    p1 = res1.json()["pairing_code"]
    
    res2 = client.post("/api/channels/telegram/pairing/regenerate", headers=HEADERS)
    p2 = res2.json()["pairing_code"]
    
    assert p1 != p2

def test_get_setup(mock_channels_config):
    response = client.get("/api/channels/telegram/setup", headers=HEADERS)
    assert response.status_code == 200
    assert len(response.json()) > 0
    assert response.json()[0]["title"] == "Create a Bot"
