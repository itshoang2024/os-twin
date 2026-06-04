"""Minimal MCP server to test if Codex can see tools."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Test Server")


@mcp.tool(structured_output=False)
def hello(name: str) -> str:
    """Say hello to someone.

    Args:
        name: The name to greet.
    """
    return f"Hello, {name}!"


@mcp.tool(structured_output=False)
def add(a: int, b: int) -> str:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.
    """
    return str(a + b)


if __name__ == "__main__":
    mcp.run(transport="stdio")
