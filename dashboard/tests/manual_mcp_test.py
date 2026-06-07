
import asyncio
from dashboard.knowledge.mcp_server import mcp

async def test_mcp():
    print("Listing tools...")
    tools = await mcp.list_tools()
    for t in tools:
        print(f"- {t.name}: {t.description[:50]}...")
    
    print("\nCalling knowledge_list_namespaces...")
    res = await mcp.call_tool("knowledge_list_namespaces", {})
    print(f"Result: {res}")

if __name__ == "__main__":
    asyncio.run(test_mcp())
