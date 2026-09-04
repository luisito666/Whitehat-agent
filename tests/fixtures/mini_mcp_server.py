"""Mini servidor MCP stdio para tests: una unica tool echo.

Uso (spawn stdio):
    python tests/fixtures/mini_mcp_server.py
"""
from mcp.server.fastmcp import FastMCP

m = FastMCP("mini-test")


@m.tool()
def echo(text: str) -> str:
    """Devuelve el texto tal cual."""
    return text


if __name__ == "__main__":
    m.run(transport="stdio")
