"""Minimal stdio MCP server for tests."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("demo")


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def add(a: int, b: int) -> str:
    """Add two integers."""
    return str(a + b)


@server.tool()
def shout(text: str) -> str:
    """Upper-case some text."""
    return text.upper()


if __name__ == "__main__":
    server.run()
