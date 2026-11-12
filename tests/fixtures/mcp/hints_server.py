"""Stdio MCP server for tests: tools with different MCP annotations."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("hints")


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def look(text: str) -> str:
    """Read-only."""
    return f"look:{text}"


@server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))
def note(text: str) -> str:
    """Additive and local (an edit)."""
    return f"note:{text}"


@server.tool(annotations=ToolAnnotations(destructive_hint=True))
def wipe(text: str) -> str:
    """Destructive."""
    return f"wipe:{text}"


@server.tool()
def plain(text: str) -> str:
    """Not annotated."""
    return f"plain:{text}"


if __name__ == "__main__":
    server.run()
