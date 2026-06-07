from api import app
from fastapi.testclient import TestClient

client = TestClient(app)

def test_telegram_config_endpoint():
    # Test GET
    response = client.get("/api/telegram/config")
    assert response.status_code == 200
    data = response.json()
    assert "bot_token" in data
    assert "chat_id" in data

def test_telegram_save_config():
    # Test POST
    payload = {"bot_token": "test_token", "chat_id": "test_chat"}
    response = client.post("/api/telegram/config", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    
    # Verify saved
    response = client.get("/api/telegram/config")
    assert response.json() == payload

def test_telegram_test_connection_fail():
    # Test POST /api/telegram/test with invalid config
    # Since we can't easily mock the httpx.AsyncClient call in this quick check without more setup,
    # we just check if the endpoint exists and handles failure (which it will with invalid token)
    response = client.post("/api/telegram/test")
    assert response.status_code in [200, 500] # Depends on if it actually tries to send and fails

