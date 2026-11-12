"""GameDevWorkstation's own tools as an MCP server, for Claude Code sessions (harness claude_code).

`POST /mcp/gdw` on the backend's existing FastAPI app (127.0.0.1 only), outside /api so the app's
own token is never handed to the CLI. Each claude process gets its own random bearer token, which
names the one session it may act for; `--mcp-config` carries it in a 0600 file in that session's
data dir. Requests must come from a loopback address with a loopback Host header (no DNS
rebinding) and no foreign Origin (no browser page can call it).

Transport: the request/response subset of MCP Streamable HTTP. Every POSTed JSON-RPC request gets
an `application/json` reply; notifications get 202; GET (the optional server-to-client SSE stream)
and DELETE get 405. claude 2.1.308 works with exactly this [live]: it sends the bearer header from
--mcp-config, probes `server/discover` (answered "Method not found", it then falls back), sends
`initialize` (protocol 2025-11-25), `notifications/initialized`, one GET (405 is fine) and
`tools/list`; `tools/call` params carry `_meta` ({"claudecode/toolUseId", "progressToken"}). The MCP SDK's StreamableHTTPSessionManager needs its own task-group lifespan and
doesn't hand the request's bearer identity to tool handlers in stateless mode, so this small route
is used instead; tests drive it with the MCP SDK's own client.

Tools offered (prefixed `mcp__gdw__` inside Claude Code): every `app.tools` tool the session's main
agent would get (Tool.when per session), minus the ones that overlap Claude Code's built-ins (file
tools, shell, web) or need the built-in loop or an API key (subagents, waves, campaigns, critique,
web_search), plus the session's enabled MCP servers from Skills & MCP (e.g. MCP for Unity), plus
`approve` (Claude Code's --permission-prompt-tool; the PreToolUse hook refuses it as a model call).
Calls run exactly like the built-in loop's: a ToolContext for the session's main agent, pre_tool and
post_tool hooks, the tool's own approval cards, Plan only mode refusals and output limits.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import secrets
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .. import __version__
from ..agent.tools import ToolContext, ToolOutput
from .hookbus import run_post_tool, run_pre_tool

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)

PATH = "/mcp/gdw"
SERVER = "gdw"  # → mcp__gdw__<tool> in Claude Code
APPROVE_TOOL = "approve"
PROMPT_TOOL = f"mcp__{SERVER}__{APPROVE_TOOL}"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 4 * 1024 * 1024
# Not offered: Claude Code has its own (file tools, shell, web fetch), they bill an API key
# (web_search, critique), or they belong to the built-in loop (subagents, waves, campaigns, chains).
EXCLUDED_TOOLS = frozenset({
    "read_file", "list_dir", "search", "write_file", "edit_file", "delete_file", "run_command",
    "web_fetch", "web_search", "critique",
    "spawn_subagent", "get_subagent_result", "message_subagent", "stop_subagent", "request_effort_approval",
    "merge_worktree", "discard_worktree", "record_unit_outcome", "get_delegation_stats",
    "run_wave", "wave_status", "merge_wave", "close_wave",
    "campaign_status", "campaign_log", "campaign_pause", "campaign_submit_plan", "campaign_phase_done",
    "chain_step_done",
})
APPROVE_SCHEMA = {"type": "object", "properties": {
    "tool_name": {"type": "string"}, "input": {"type": "object"}, "tool_use_id": {"type": "string"}},
    "additionalProperties": True}
APPROVE_DESCRIPTION = ("Internal: answers Claude Code's permission prompts with GameDevWorkstation's approval "
                       "cards. Never call it yourself.")
Approver = Callable[[str, dict], Awaitable[dict]]


def _loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _host_only(host_header: str) -> str:
    h = host_header.strip().lower()
    if h.startswith("["):  # [::1]:8765
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def _err(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


class GdwMcp:
    def __init__(self, app: "AppState"):
        self.app = app
        self._tokens: dict[str, str] = {}  # token -> session id
        self.approver: Approver | None = None  # set by features/claude_code.py

    # ------------------------------------------------------------- tokens

    def issue(self, sid: str) -> str:
        """A fresh token for a session's new claude process (the old one stops working)."""
        self.revoke(sid)
        tok = secrets.token_urlsafe(32)
        self._tokens[tok] = sid
        return tok

    def revoke(self, sid: str, token: str | None = None) -> None:
        for t in [t for t, s in self._tokens.items() if s == sid and (token is None or t == token)]:
            del self._tokens[t]

    def session_for(self, supplied: str) -> str | None:
        found = None
        for tok, sid in list(self._tokens.items()):  # compare every one: no early exit on a match
            if hmac.compare_digest(tok.encode(), supplied.encode()):
                found = sid
        return found

    def url(self) -> str:
        port = getattr(self.app, "listen_port", None)
        if not port:
            raise RuntimeError("GameDevWorkstation's own port isn't known, so Claude Code can't reach its tools.")
        return f"http://127.0.0.1:{int(port)}{PATH}"

    def config_json(self, token: str) -> dict:
        """The --mcp-config document for one claude process (`type` is required for URL servers [docs])."""
        return {"mcpServers": {SERVER: {"type": "http", "url": self.url(),
                                        "headers": {"Authorization": f"Bearer {token}"}}}}

    # -------------------------------------------------------------- tools

    def tools_for(self, session: dict) -> list[dict]:
        """[{name, description, inputSchema, source: "tool" | "mcp" | "approve"}] for this session now."""
        out: list[dict] = []
        excluded = EXCLUDED_TOOLS | set((self.app.config.claude_code or {}).get("exclude_tools") or [])
        for spec in self.app.tools.specs(role="main", session=session):
            if spec.name in excluded or spec.name == APPROVE_TOOL:
                continue
            out.append({"name": spec.name, "description": spec.description, "inputSchema": spec.input_schema,
                        "source": "tool", **({"annotations": {"readOnlyHint": True}} if spec.read_only else {})})
        if self.app.mcp:
            for spec in self.app.mcp.tool_specs(session):
                out.append({"name": spec.name, "description": spec.description, "inputSchema": spec.input_schema,
                            "source": "mcp"})
        out.append({"name": APPROVE_TOOL, "description": APPROVE_DESCRIPTION, "inputSchema": APPROVE_SCHEMA,
                    "source": "approve"})
        return out

    def tool_names(self, session: dict) -> list[str]:
        return [t["name"] for t in self.tools_for(session)]

    async def call(self, sid: str, name: str, args: dict) -> dict:
        """One tools/call as an MCP CallToolResult."""
        app = self.app
        session = app.store.get(sid)
        if not session:
            return _text_result("This session no longer exists.", True)
        offered = {t["name"]: t for t in self.tools_for(session)}
        if name not in offered:
            return _text_result(f"Tool {name!r} is not available in this session.", True)
        if offered[name]["source"] == "approve":
            if self.approver is None:
                return _text_result(json.dumps({"behavior": "deny", "message": "No approval handler."}), False)
            decision = await self.approver(sid, args)
            return _text_result(json.dumps(decision), False)
        model = app.config.resolve(session["model"])
        ctx = ToolContext(app=app, session=session, run_id=f"main:{sid}", role="main", provider="anthropic", model=model)
        if (blocked := await run_pre_tool(app, ctx, name, args)) is not None:
            out = ToolOutput(blocked.block_text(), is_error=True)
        else:
            if offered[name]["source"] == "mcp" and app.mcp:
                out = await app.mcp.call(ctx, name, args)
            else:
                out = await app.tools.run(ctx, name, args)
            out = await run_post_tool(app, ctx, name, args, out)
        content: list[dict] = [{"type": "text", "text": out.text or "(no output)"}]
        for img in out.images:
            try:
                content.append({"type": "image", "data": img.load_b64(), "mimeType": img.media_type})
            except (OSError, ValueError):
                continue
        return {"content": content, "isError": bool(out.is_error)}

    # ---------------------------------------------------------------- http

    def _refusal(self, request: Request) -> Response | None:
        if not _loopback(request.client.host if request.client else None):
            return JSONResponse({"error": "loopback only"}, status_code=403)
        if not _loopback(_host_only(request.headers.get("host", ""))):
            return JSONResponse({"error": "bad host"}, status_code=403)  # DNS rebinding
        origin = request.headers.get("origin")
        if origin and origin != "null":
            try:
                from urllib.parse import urlsplit

                if not _loopback(urlsplit(origin).hostname):
                    return JSONResponse({"error": "bad origin"}, status_code=403)
            except ValueError:
                return JSONResponse({"error": "bad origin"}, status_code=403)
        return None

    async def handle(self, request: Request) -> Response:
        if (r := self._refusal(request)) is not None:
            return r
        supplied = request.headers.get("authorization", "")
        sid = self.session_for(supplied[7:].strip()) if supplied[:7].lower() == "bearer " else None
        if not sid:
            return JSONResponse({"error": "unauthorized"}, status_code=401,
                                headers={"WWW-Authenticate": 'Bearer realm="gdw"'})
        if request.method != "POST":
            return Response(status_code=405, headers={"Allow": "POST"})
        body = await request.body()
        if len(body) > MAX_BODY:
            return JSONResponse(_err(None, -32600, "Request too large"), status_code=413)
        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse(_err(None, -32700, "Parse error"), status_code=400)
        batch = isinstance(msg, list)
        replies = [r for m in (msg if batch else [msg]) if (r := await self._one(sid, m)) is not None]
        if not replies:
            return Response(status_code=202)
        return JSONResponse(replies if batch else replies[0])

    async def _one(self, sid: str, m: Any) -> dict | None:
        if not isinstance(m, dict) or m.get("jsonrpc") != "2.0" or not isinstance(m.get("method"), str):
            if isinstance(m, dict) and "method" not in m and ("result" in m or "error" in m):
                return None  # a response to something we never asked
            return _err(m.get("id") if isinstance(m, dict) else None, -32600, "Invalid request")
        rid, method, params = m.get("id"), m["method"], m.get("params") or {}
        if rid is None:  # a notification (notifications/initialized, cancelled, ...)
            return None
        try:
            if method == "initialize":
                want = str(params.get("protocolVersion") or "")
                return {"jsonrpc": "2.0", "id": rid, "result": {
                    "protocolVersion": want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "gamedevworkstation", "version": __version__},
                    "instructions": "GameDevWorkstation's own tools for this session (task board, Unity, items, "
                                    "skills). Their approval cards appear in GameDevWorkstation."}}
            if method == "ping":
                return {"jsonrpc": "2.0", "id": rid, "result": {}}
            if method == "tools/list":
                s = self.app.store.get(sid)
                tools = [{k: v for k, v in t.items() if k != "source"} for t in (self.tools_for(s) if s else [])]
                return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}}
            if method == "tools/call":
                name = str(params.get("name") or "")
                args = params.get("arguments") or {}
                if not isinstance(args, dict):
                    return _err(rid, -32602, "arguments must be an object")
                return {"jsonrpc": "2.0", "id": rid, "result": await self.call(sid, name, args)}
            if method in ("resources/list", "resources/templates/list", "prompts/list"):
                key = {"resources/list": "resources", "resources/templates/list": "resourceTemplates",
                       "prompts/list": "prompts"}[method]
                return {"jsonrpc": "2.0", "id": rid, "result": {key: []}}
            return _err(rid, -32601, f"Method not found: {method}")
        except Exception as e:  # noqa: BLE001 — a failing tool is an error result, never a dropped connection
            log.warning("gdw mcp %s failed", method, exc_info=True)
            return _err(rid, -32603, f"{type(e).__name__}: {e}")


def _text_result(text: str, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def mount(app_: FastAPI, server: GdwMcp) -> None:
    app_.add_api_route(PATH, server.handle, methods=["GET", "POST", "DELETE"], include_in_schema=False)
