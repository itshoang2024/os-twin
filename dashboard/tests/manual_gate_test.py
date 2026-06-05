
import os
import asyncio
import json
import requests

def test_gate():
    os.environ["OSTWIN_MCP_ACTOR"] = "knowledge-curator"
    # We can't easily call the MCP server over stdio here without setting up the whole session.
    # But we can call the tool function directly if we import it.
    
    from dashboard.knowledge.mcp_server import knowledge_delete_namespace
    
    print("Testing knowledge_delete_namespace without confirm...")
    res = asyncio.run(knowledge_delete_namespace("some-ns", confirm=False))
    print(f"Result: {json.dumps(res, indent=2)}")
    
    if res.get("code") == "CONFIRMATION_REQUIRED":
        print("PASS: Confirmation gate triggered.")
    else:
        print("FAIL: Confirmation gate DID NOT trigger.")

if __name__ == "__main__":
    test_gate()
