from fastapi.testclient import TestClient

from dashboard.api import app


HEADERS = {"X-API-Key": "test-key"}


def test_epic2():
    """Smoke-test EPIC-002 dashboard endpoints without requiring a live server."""
    client = TestClient(app)

    res = client.get("/api/plans", headers=HEADERS)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    plans_data = res.json()
    assert "plans" in plans_data

    res = client.get("/api/rooms", headers=HEADERS)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    rooms_data = res.json()
    assert "rooms" in rooms_data

    if rooms_data["rooms"]:
        room_id = rooms_data["rooms"][0]["room_id"]

        res = client.get(f"/api/rooms/{room_id}/channel", headers=HEADERS)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        assert "messages" in res.json()

        res = client.post(f"/api/rooms/{room_id}/action", params={"action": "pause"}, headers=HEADERS)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

        res = client.post(f"/api/rooms/{room_id}/action", params={"action": "resume"}, headers=HEADERS)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
