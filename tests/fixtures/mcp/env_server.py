"""Stdio MCP server for tests: reports the environment it was started with."""
import os

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("envy")


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def getenv(name: str) -> str:
    """Value of an environment variable of the server process."""
    return os.environ.get(name, "<unset>")


if __name__ == "__main__":
    server.run()
