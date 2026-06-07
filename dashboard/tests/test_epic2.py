import asyncio
import httpx
import sys
import pytest

@pytest.mark.asyncio
async def test_epic2():
    print("Testing EPIC-002: Rich Dashboard Views")
    
    async with httpx.AsyncClient(base_url="http://127.0.0.1:9001") as client:
        try:
            # 1. Test Plan Queue (GET /api/plans)
            print("\n1. Testing Plan Queue API...")
            res = await client.get("/api/plans")
            assert res.status_code == 200, f"Expected 200, got {res.status_code}"
            data = res.json()
            assert "plans" in data, "Response should contain 'plans'"
            print("✓ GET /api/plans successful")
            
            # 2. Test War-Room Grid (GET /api/rooms)
            print("\n2. Testing War-Room Grid API...")
            res = await client.get("/api/rooms")
            assert res.status_code == 200, f"Expected 200, got {res.status_code}"
            data = res.json()
            assert "rooms" in data, "Response should contain 'rooms'"
            print("✓ GET /api/rooms successful")
            
            if data["rooms"]:
                room_id = data["rooms"][0]["room_id"]
                
                # 3. Test Room Detail Channel Viewer (GET /api/rooms/{room_id}/channel)
                print(f"\n3. Testing Room Detail Channel API for {room_id}...")
                res = await client.get(f"/api/rooms/{room_id}/channel")
                assert res.status_code == 200, f"Expected 200, got {res.status_code}"
                ch_data = res.json()
                assert "messages" in ch_data, "Response should contain 'messages'"
                print(f"✓ GET /api/rooms/{room_id}/channel successful")
                
                # 4. Test Interactive Controls (POST /api/rooms/{room_id}/action)
                print(f"\n4. Testing Interactive Controls API for {room_id}...")
                # Try pausing the room
                res = await client.post(f"/api/rooms/{room_id}/action", params={"action": "pause"})
                assert res.status_code == 200, f"Expected 200, got {res.status_code}"
                print(f"✓ POST /api/rooms/{room_id}/action?action=pause successful")
                
                # Try resuming the room
                res = await client.post(f"/api/rooms/{room_id}/action", params={"action": "resume"})
                assert res.status_code == 200, f"Expected 200, got {res.status_code}"
                print(f"✓ POST /api/rooms/{room_id}/action?action=resume successful")

            print("\nAll EPIC-002 tests passed! ✨")
            
        except AssertionError as e:
            print(f"✗ Test failed: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_epic2())
