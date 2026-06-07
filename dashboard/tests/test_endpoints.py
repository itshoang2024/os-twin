
import httpx
import asyncio

async def check():
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get("http://localhost:3366/api/telegram/config")
            print(f"GET /api/telegram/config: {res.status_code} {res.json()}")
            
            res = await client.post("http://localhost:3366/api/telegram/config", json={"bot_token": "test", "chat_id": "123"})
            print(f"POST /api/telegram/config: {res.status_code} {res.json()}")
            
            res = await client.get("http://localhost:3366/api/telegram/config")
            print(f"GET /api/telegram/config after save: {res.status_code} {res.json()}")
            
            res = await client.post("http://localhost:3366/api/telegram/test")
            print(f"POST /api/telegram/test: {res.status_code} {res.json()}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())
