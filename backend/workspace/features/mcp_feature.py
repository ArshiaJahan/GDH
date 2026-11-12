"""MCP servers (stdio or HTTP) as tools for the main agent and subagents, plus the
Skills & MCP page API.

Tools are exposed as `mcp__<server>__<tool>` ToolSpecs; each provider adapter translates
them like any other tool, so Claude and Codex subagents both can use them.
Servers marked `shared` come from another machine: a session only sees them when its
Shared tools box is ticked, and every call asks for approval unless allowlisted
(`shared_tool:<server>__<tool>`).

Secrets: env vars and headers whose names look secret (KEY, TOKEN, SECRET, PASSWORD, PAT, AUTH,
Authorization, …) are kept in the Keychain (service `Workspace`, account `mcp:<server>:<NAME>`, or
`mcp:<server>:header:<Name>` for headers). SQLite only holds a reference, the API only shows
`••••last4`, and the value is read back when the server is started. With WORKSPACE_NO_KEYCHAIN=1
(development) they stay in SQLite, with a warning in the log.

Built-in servers (`[mcp.presets.*]` in config, e.g. MCP for Unity) are added once at startup, off
by default for sessions. kv `mcp_presets_seeded` lists the ones added (they show a Built-in badge
and can be reset to their definition); `mcp_presets_deleted` the ones the user removed, which are
never added back. Skills listed in `[skills.mcp_on_invoke]` turn their servers on for a session when
they're invoked or ticked in its Connectors card (enable_for_skills).
"""
from __future__ import annotations

import asyncio
import base64
import contextvars
import json
import logging
import os
import re
import shutil
from typing import TYPE_CHECKING, Any, Iterable

from fastapi import APIRouter, Body, FastAPI, HTTPException

from ..agent.tools import ToolContext, ToolOutput, finalize_output, obj
from ..children import CHILDREN
from ..config import delete_secret, get_secret, keychain_enabled, set_secret
from ..core.types import ImageBlock, ToolSpec
from ..skills import get_skill, list_skills, read_skill_file, save_skill

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 30
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTH|CREDENTIAL|COOKIE|(?:^|[_-])PAT(?:[_-]|$)", re.I)
MASK = "••••"


# --------------------------------------------------------------------- secrets


def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME.search(name))


def _account(server: str, kind: str, name: str) -> str:
    return f"mcp:{server}:{name}" if kind == "env" else f"mcp:{server}:header:{name}"


def _is_ref(v: Any) -> bool:
    return isinstance(v, dict) and isinstance(v.get("keychain"), str)


def _hint(value: str) -> str:
    return value[-4:] if len(value) >= 8 else ""


def masked(m: dict) -> dict[str, str]:
    """What the API shows: secrets as ••••last4, everything else as is."""
    out = {}
    for k, v in (m or {}).items():
        if _is_ref(v):
            out[k] = MASK + str(v.get("hint") or "")
        elif is_secret_name(k) and v:
            out[k] = MASK + _hint(str(v))
        else:
            out[k] = v
    return out


def check_secrets(incoming: dict, existing: dict | None = None) -> None:
    """Raises ValueError if a masked value or stored reference is sent back for a name that has no
    stored secret (or a different one). Writes nothing."""
    existing = existing or {}
    for k, val in (incoming or {}).items():
        name = str(k).strip()
        if not name:
            continue
        kept = _is_ref(val) or (isinstance(val, str) and val.startswith(MASK))
        if kept and existing.get(name) is None or _is_ref(val) and val != existing.get(name):
            raise ValueError(f"Enter the value of {name} again")


def unused_secrets(existing: dict | None, saved: dict) -> list[str]:
    """Keychain accounts `existing` refers to that `saved` no longer does."""
    used = {v["keychain"] for v in saved.values() if _is_ref(v)}
    return [v["keychain"] for v in (existing or {}).values() if _is_ref(v) and v["keychain"] not in used]


def store_secrets(server: str, kind: str, incoming: dict, existing: dict | None = None,
                  prune: bool = True) -> dict:
    """The env/headers map to save: secret-named values go to the Keychain (a reference is kept).
    A value sent back masked (`••••…`) keeps the stored secret. With prune, Keychain entries no longer
    used are deleted (pass prune=False and call unused_secrets after the row is saved instead).
    Raises ValueError if the Keychain refuses a value."""
    existing = existing or {}
    items = [(str(k).strip(), v) for k, v in (incoming or {}).items() if str(k).strip()]
    check_secrets(incoming, existing)  # check everything before writing anything
    out: dict[str, Any] = {}
    for name, val in items:
        old = existing.get(name)
        if _is_ref(val) or (isinstance(val, str) and val.startswith(MASK)):
            out[name] = old  # unchanged secret (or a stored reference passed through by the migration)
            continue
        val = "" if val is None else str(val)
        if is_secret_name(name) and val:
            if keychain_enabled():
                acct = _account(server, kind, name)
                try:
                    set_secret(acct, val)
                except Exception as e:  # noqa: BLE001 — never include the value
                    raise ValueError(f"Couldn't save {name} in the Keychain: {type(e).__name__}") from None
                out[name] = {"keychain": acct, "hint": _hint(val)}
                continue
            log.warning("WORKSPACE_NO_KEYCHAIN=1: MCP server %s %s %s is stored in plain SQLite", server, kind, name)
        out[name] = val
    if prune:
        for acct in unused_secrets(existing, out):
            delete_secret(acct)
    return out


def resolve_secrets(m: dict) -> dict[str, str]:
    """Real values for starting a server. Raises RuntimeError (without the value) if one is gone."""
    out = {}
    for k, v in (m or {}).items():
        if _is_ref(v):
            try:
                val = get_secret(v["keychain"])
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"Couldn't read {k} from the Keychain: {type(e).__name__}") from None
            if val is None:
                raise RuntimeError(f"{k} is missing from the Keychain. Edit the server on the Skills & MCP page "
                                   "and enter it again.")
            out[k] = val
        else:
            out[k] = "" if v is None else str(v)
    return out


def forget_secrets(row: dict) -> None:
    for k in ("env", "headers"):
        for v in (row.get(k) or {}).values():
            if _is_ref(v):
                delete_secret(v["keychain"])


# ------------------------------------------------------------ stdio commands

# Where a command usually lives when it isn't on PATH (GUI apps on macOS don't get the shell's PATH;
# at startup services.fix_path merges the login shell's PATH into this process's, then these are tried).
COMMAND_FALLBACKS = {"uvx": ("/opt/homebrew/bin/uvx", "/usr/local/bin/uvx", "~/.local/bin/uvx", "~/.cargo/bin/uvx")}
MISSING_HINTS = {"uvx": "Install uv (brew install uv), then use Test connection."}


def resolve_command(cmd: str | None) -> str | None:
    """The executable a stdio server's command runs, or None if it can't be found."""
    if not cmd:
        return None
    if "/" in cmd:
        p = os.path.expanduser(cmd)
        return p if os.path.isfile(p) and os.access(p, os.X_OK) else None
    if found := shutil.which(cmd):
        return found
    for p in COMMAND_FALLBACKS.get(cmd, ()):
        p = os.path.expanduser(p)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def missing_command_hint(cmd: str | None) -> str | None:
    """For the Skills & MCP page: why a stdio server can't start, or None if its command is there.
    Relative paths (resolved against the working folder at start) aren't judged."""
    if not cmd or (("/" in cmd) and not cmd.startswith(("/", "~"))) or resolve_command(cmd):
        return None
    base = os.path.basename(cmd)
    return f"{base} wasn't found on this Mac. " + MISSING_HINTS.get(base, "Install it or edit the server's command.")


# ------------------------------------------------------------------- presets


def _preset_row(p: dict) -> dict:
    """The mcp_servers fields a preset defines ([mcp.presets.*]). Raises ValueError if it's unusable."""
    name, transport = str(p.get("name") or ""), str(p.get("transport") or "stdio")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", name):
        raise ValueError("name: letters, digits, - and _ (max 40)")
    if transport not in ("stdio", "http") or (transport == "stdio" and not p.get("command")) \
            or (transport == "http" and not str(p.get("url") or "").startswith(("http://", "https://"))):
        raise ValueError("a stdio preset needs a command, an http one an http(s) url")
    return {"name": name, "transport": transport, "command": p.get("command") if transport == "stdio" else None,
            "args": [str(a) for a in p.get("args") or []], "env": {str(k): str(v) for k, v in (p.get("env") or {}).items()},
            "url": p.get("url") if transport == "http" else None,
            "headers": {str(k): str(v) for k, v in (p.get("headers") or {}).items()}}


def _same_as_preset(row: dict, p: dict) -> bool:
    """Is a stored server (as _rows returns it) still exactly its preset's definition?"""
    try:
        want = _preset_row(p)
    except ValueError:
        return False
    return all((row.get(k) or None) == (want[k] or None) for k in ("transport", "command", "args", "env", "url", "headers"))


# ------------------------------------------------------------- stdio children

# The connection whose task is starting a stdio server, so the spawn hook can note its pid.
_CONNECTING: contextvars.ContextVar["MCPConnection | None"] = contextvars.ContextVar("mcp_connecting", default=None)


def _install_spawn_hook() -> None:
    """Register every stdio server's process group with CHILDREN (it runs in its own session), so
    quitting ends it. The MCP SDK doesn't expose the process, so wrap its spawn function."""
    try:
        import mcp.client.stdio as stdio_mod
    except ImportError:
        return
    orig = getattr(stdio_mod, "_create_platform_compatible_process", None)
    if orig is None:
        log.warning("MCP SDK changed: stdio server processes aren't tracked for shutdown")
        return
    if getattr(orig, "_workspace_hook", False):
        return

    async def spawn(*a: Any, **k: Any) -> Any:
        proc = await orig(*a, **k)
        CHILDREN.track(proc.pid, "mcp")
        if (c := _CONNECTING.get()) is not None:
            c.pids.append(proc.pid)
        return proc

    spawn._workspace_hook = True  # type: ignore[attr-defined]
    stdio_mod._create_platform_compatible_process = spawn


def _attr(o: Any, *names: str) -> Any:
    """MCP SDK v2 uses snake_case; v1 used camelCase."""
    for n in names:
        try:
            v = getattr(o, n)
        except AttributeError:
            continue
        if v is not None:
            return v
    return None


def mcp_policy(mode: str, hints: dict[str, Any]) -> str:
    """allow | ask | deny for one MCP tool call, from the session mode and the tool's annotations.
    MCP's defaults apply to missing hints (readOnly false, destructive true, openWorld true), so an
    unannotated tool counts as one that changes things.
    - Plan: only readOnlyHint=true tools run; everything else is refused.
    - readOnlyHint=true: runs in every mode (like read_file and web_search).
    - Accept edits: also runs tools that say they are neither destructive nor open-world (additive,
      local changes, the MCP counterpart of an edit); the rest ask.
    - Ask: everything else asks.
    Asking can be skipped with an `mcp:<server>__<tool>` allowlist rule (not in Plan). Shared servers
    keep their own rules on top: Shared tools must be on and every job asks (shared_tool:...)."""
    if hints.get("readOnlyHint") is True:
        return "allow"
    if mode == "plan":
        return "deny"
    if mode == "accept_edits" and hints.get("destructiveHint") is False and hints.get("openWorldHint") is False:
        return "allow"
    return "ask"


def hint_notes(hints: dict[str, Any]) -> list[str]:
    """What the approval card says about the tool's own annotations."""
    if not hints:
        return ["not annotated: may change or delete things, or reach outside this Mac"]
    out = []
    if hints.get("destructiveHint") is not False:
        out.append("may delete or overwrite data" if hints.get("destructiveHint") else
                   "may delete or overwrite data (not stated otherwise)")
    if hints.get("openWorldHint") is not False:
        out.append("reaches outside this Mac (web, other services)" if hints.get("openWorldHint") else
                   "may reach outside this Mac (not stated otherwise)")
    return out


def tool_name(server: str, tool: str) -> str:
    clean = lambda s: re.sub(r"[^a-zA-Z0-9_-]", "_", s)  # noqa: E731
    return f"mcp__{clean(server)}__{clean(tool)}"[:64]


class MCPConnection:
    """One live server connection, owned by its own task."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.session: Any = None
        self.tools: list[Any] = []
        self.error: str | None = None
        self.pids: list[int] = []  # stdio server process (for shutdown tracking)
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self._ready.wait(), CONNECT_TIMEOUT)
        if self.error:
            raise RuntimeError(self.error)

    async def _run(self) -> None:
        from mcp import ClientSession

        _CONNECTING.set(self)
        try:
            if self.cfg["transport"] == "stdio":
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client

                _install_spawn_hook()
                command = self.cfg["command"]
                exe = resolve_command(command)
                if exe is None and "/" not in command:  # a bare name that isn't installed: say so plainly
                    raise FileNotFoundError(missing_command_hint(command))
                params = StdioServerParameters(command=exe or command, args=self.cfg.get("args") or [],
                                               env={**os.environ, **resolve_secrets(self.cfg.get("env"))})
                transport = stdio_client(params)
            else:
                from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

                client = create_mcp_http_client(headers=resolve_secrets(self.cfg.get("headers")) or None)
                transport = streamable_http_client(self.cfg["url"], http_client=client)
            async with transport as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    self.tools = (await session.list_tools()).tools
                    self._ready.set()
                    await self._stop.wait()
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"[:500]
        finally:
            self.session = None
            self._ready.set()
            for pid in self.pids:
                CHILDREN.release(pid)

    async def close(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, 5)
            except (asyncio.TimeoutError, Exception):
                self._task.cancel()


class MCPManager:
    def __init__(self, app: "AppState"):
        self.app = app
        self.conns: dict[str, MCPConnection] = {}
        self._names: dict[str, tuple[str, str]] = {}  # exposed name → (server, tool)
        self._locks: dict[str, asyncio.Lock] = {}

    # ----------------------------------------------------------------- config

    def _rows(self) -> list[dict]:
        """Rows as stored: secrets are Keychain references (or plain values with WORKSPACE_NO_KEYCHAIN=1)."""
        rows = self.app.db.all("SELECT * FROM mcp_servers ORDER BY name")
        for r in rows:
            for k in ("args", "env", "headers"):
                r[k] = json.loads(r[k] or ("[]" if k == "args" else "{}"))
        return rows

    def _row(self, name: str) -> dict | None:
        return next((r for r in self._rows() if r["name"] == name), None)

    def servers(self) -> list[dict]:
        """For the API and agents: secret values masked as ••••last4. Built-in servers (presets) carry
        preset/description/modified; a stdio server whose command isn't installed carries a hint."""
        rows = self._rows()
        presets, seeded = self.app.config.mcp_presets(), set(self._kv("mcp_presets_seeded"))
        for r in rows:
            p = presets.get(r["name"]) if r["name"] in seeded else None
            r["preset"] = p is not None
            r["description"] = str((p or {}).get("description") or "")
            r["modified"] = p is not None and not _same_as_preset(r, p)
            r["hint"] = missing_command_hint(r["command"]) if r["transport"] == "stdio" else None
            r["env"], r["headers"] = masked(r["env"]), masked(r["headers"])
            r["enabled_default"] = bool(r["enabled_default"])
            r["shared"] = bool(r["shared"])
            c = self.conns.get(r["name"])
            r["connected"] = bool(c and c.session)
            r["error"] = c.error if c else None
            r["tools"] = [t.name for t in c.tools] if c and c.session else None
        return rows

    def server(self, name: str) -> dict | None:
        return next((s for s in self.servers() if s["name"] == name), None)

    def enabled_for(self, session: dict) -> list[dict]:
        overrides = (session.get("settings") or {}).get("connectors", {}) or {}
        shared_ok = bool((session.get("settings") or {}).get("shared_tools"))
        out = []
        for s in self.servers():
            on = overrides.get(s["name"], s["enabled_default"])
            if s["shared"] and not shared_ok:
                continue
            if on:
                out.append(s)
        return out

    async def add(self, body: dict) -> dict:
        """Validate and save a server config (replacing one with the same name). Raises ValueError."""
        name = (body.get("name") or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", name):
            raise ValueError("Name: letters, digits, - and _ (max 40)")
        transport = body.get("transport", "stdio")
        if transport not in ("stdio", "http"):
            raise ValueError("transport is stdio or http")
        if transport == "stdio" and not body.get("command"):
            raise ValueError("A stdio server needs a command")
        if transport == "http" and not str(body.get("url", "")).startswith(("http://", "https://")):
            raise ValueError("An HTTP server needs an http(s) URL")
        old = self._row(name) or {}
        # Validate both maps before touching the Keychain, and drop entries the old row used only once
        # the new row is saved: a rejected edit must leave the stored server working.
        check_secrets(body.get("env") or {}, old.get("env"))
        check_secrets(body.get("headers") or {}, old.get("headers"))
        env = store_secrets(name, "env", body.get("env") or {}, old.get("env"), prune=False)
        headers = store_secrets(name, "headers", body.get("headers") or {}, old.get("headers"), prune=False)
        self.app.db.insert("mcp_servers", {"name": name, "transport": transport, "command": body.get("command"),
                                           "args": body.get("args") or [], "env": env,
                                           "url": body.get("url"), "headers": headers,
                                           "enabled_default": int(body.get("enabled_default", True)),
                                           "shared": int(bool(body.get("shared")))}, replace=True)
        for acct in unused_secrets(old.get("env"), env) + unused_secrets(old.get("headers"), headers):
            delete_secret(acct)
        await self.disconnect(name)
        return self.server(name)  # type: ignore[return-value]

    async def remove(self, name: str) -> None:
        """Delete a server (and its Keychain entries). A built-in one is remembered as deleted, so
        startup doesn't add it back; Reset to default (reset_preset) restores it."""
        await self.disconnect(name)
        row = self._row(name)
        self.app.db.execute("DELETE FROM mcp_servers WHERE name=?", [name])
        if row:
            forget_secrets(row)
        seeded = self._kv("mcp_presets_seeded")
        if name in seeded or name in self.app.config.mcp_presets():  # also a server of yours with a preset's name
            self.app.db.kv_set("mcp_presets_seeded", [n for n in seeded if n != name])
            self.app.db.kv_set("mcp_presets_deleted", list(dict.fromkeys([*self._kv("mcp_presets_deleted"), name])))

    # ---------------------------------------------------------------- presets

    def _kv(self, key: str) -> list[str]:
        v = self.app.db.kv_get(key, [])
        return [str(x) for x in v] if isinstance(v, list) else []

    def seed_presets(self) -> list[str]:
        """Startup: add each built-in server that was never added and has no server of its name yet.
        Never touches an existing server, never re-adds one the user deleted, and adds them off by
        default for sessions (skills in [skills.mcp_on_invoke] turn them on). A preset whose command
        isn't installed is still added; the Skills & MCP page shows how to fix it."""
        seeded, deleted = self._kv("mcp_presets_seeded"), set(self._kv("mcp_presets_deleted"))
        existing = {r["name"] for r in self._rows()}
        added = []
        for name, p in self.app.config.mcp_presets().items():
            if name in existing or name in deleted or name in seeded:
                continue
            try:
                row = _preset_row(p)
            except ValueError as e:
                log.warning("MCP preset %s skipped: %s", name, e)
                continue
            self.app.db.insert("mcp_servers", {**row, "enabled_default": 0, "shared": 0})
            added.append(name)
            if row["transport"] == "stdio" and (hint := missing_command_hint(row["command"])):
                log.info("added built-in MCP server %s; %s", name, hint)
            else:
                log.info("added built-in MCP server %s", name)
        if added:
            self.app.db.kv_set("mcp_presets_seeded", [*seeded, *added])
        return added

    async def reset_preset(self, name: str) -> dict:
        """Put a built-in server back to its definition (also restores one that was deleted). Keeps its
        On by default choice. Raises KeyError (no such preset) or ValueError (a server of yours has
        that name)."""
        p = self.app.config.mcp_presets().get(name)
        if not p:
            raise KeyError(name)
        seeded, deleted = self._kv("mcp_presets_seeded"), self._kv("mcp_presets_deleted")
        old = self._row(name)
        if old and name not in seeded:
            raise ValueError(f"{name} is your own server, not the built-in one")
        row = _preset_row(p)
        self.app.db.insert("mcp_servers", {**row, "enabled_default": int(bool(old and old["enabled_default"])),
                                           "shared": 0}, replace=True)
        if old:
            forget_secrets(old)
        self.app.db.kv_set("mcp_presets_seeded", list(dict.fromkeys([*seeded, name])))
        self.app.db.kv_set("mcp_presets_deleted", [n for n in deleted if n != name])
        await self.disconnect(name)
        return self.server(name)  # type: ignore[return-value]

    # --------------------------------------------------- skills turn servers on

    def enable_for_skills(self, sid: str, skills: Iterable[str]) -> list[str]:
        """Turn on, for this session, the MCP servers these skills use ([skills.mcp_on_invoke]), when
        they exist and aren't on yet. Servers from another machine are never turned on this way (they
        need the session's Shared tools and ask before every call), and shared_tools is never changed.
        Publishes `mcp.auto_enabled` (shown once as a toast). Returns the servers turned on."""
        skills = list(skills)
        s = self.app.store.get(sid)
        if not s or not skills:
            return []
        conn = dict((s.get("settings") or {}).get("connectors") or {})
        rows = {r["name"]: r for r in self._rows()}
        names: list[str] = []
        for sk in skills:
            for n in self.app.config.skill_mcp_servers(sk):
                r = rows.get(n)
                if not r or r["shared"] or n in names or conn.get(n, bool(r["enabled_default"])):
                    continue
                names.append(n)
        if not names:
            return []
        self.app.store.update(sid, settings={"connectors": {**conn, **dict.fromkeys(names, True)}})
        msg = f"Enabled MCP server{'s' if len(names) > 1 else ''} {', '.join(names)} for this session"
        self.app.bus.publish("mcp.auto_enabled", {"servers": names, "skills": skills, "message": msg}, sid)
        return names

    async def test(self, name: str) -> dict:
        """(Re)connect a server and list its tools."""
        await self.disconnect(name)
        try:
            c = await self.connect(name)
        except Exception as e:  # noqa: BLE001
            c = self.conns.get(name)
            return {"ok": False, "error": (c.error if c else None) or str(e)}
        return {"ok": True, "tools": [{"name": t.name, "description": t.description} for t in c.tools]}

    # ------------------------------------------------------------ connections

    async def connect(self, name: str) -> MCPConnection:
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            c = self.conns.get(name)
            if c and c.session:
                return c
            cfg = self._row(name)
            if not cfg:
                raise KeyError(name)
            c = MCPConnection(cfg)  # secrets are resolved when it starts
            self.conns[name] = c
            await c.start()
            for t in c.tools:
                self._names[tool_name(name, t.name)] = (name, t.name)
            return c

    async def disconnect(self, name: str) -> None:
        c = self.conns.pop(name, None)
        if c:
            await c.close()

    async def warm(self, session: dict) -> None:
        """Connect the session's enabled servers (in parallel) so their tools can be offered."""
        await asyncio.gather(*(self._safe_connect(s["name"]) for s in self.enabled_for(session)))

    async def _safe_connect(self, name: str) -> None:
        try:
            await self.connect(name)
        except Exception:  # noqa: BLE001 — shown on the Skills & MCP page
            pass

    # --------------------------------------------------------------- as tools

    def tool_specs(self, session: dict) -> list[ToolSpec]:
        specs = []
        for s in self.enabled_for(session):
            c = self.conns.get(s["name"])
            if not c or not c.session:
                continue
            for t in c.tools:
                specs.append(ToolSpec(name=tool_name(s["name"], t.name),
                                      description=f"[MCP {s['name']}{' · other machine' if s['shared'] else ''}] "
                                                  f"{t.description or ''}"[:1024],
                                      input_schema=_attr(t, "input_schema", "inputSchema")
                                      or {"type": "object", "properties": {}}))
        return specs

    def owns(self, name: str) -> bool:
        return name in self._names

    def hints(self, server: str, tool: str) -> dict[str, bool | None]:
        """The tool's MCP annotations (readOnlyHint, destructiveHint, openWorldHint); None = not given."""
        c = self.conns.get(server)
        t = next((t for t in (c.tools if c else []) if t.name == tool), None)
        a = _attr(t, "annotations") if t is not None else None
        if a is None:
            return {}
        out: dict[str, bool | None] = {}
        for key, snake in (("readOnlyHint", "read_only_hint"), ("destructiveHint", "destructive_hint"),
                           ("openWorldHint", "open_world_hint")):
            v = _attr(a, snake, key)
            out[key] = v if isinstance(v, bool) else None
        return out

    async def call(self, ctx: ToolContext, name: str, args: dict) -> ToolOutput:
        server, tool = self._names[name]
        cfg = self.server(server) or {}
        if not any(s["name"] == server for s in self.enabled_for(ctx.session)):
            # Connected for another session, but turned off (or removed) for this one.
            if cfg.get("shared") and not (ctx.session.get("settings") or {}).get("shared_tools"):
                return ToolOutput("Shared tools are off for this session.", is_error=True)
            return ToolOutput(f"MCP server {server} is turned off for this session.", is_error=True)
        hints = self.hints(server, tool)
        decision = mcp_policy(ctx.mode, hints)
        if decision == "deny":
            return ToolOutput(f"Plan only mode: {server}.{tool} isn't marked read-only (readOnlyHint), so it isn't "
                              "run. Describe the call instead.", is_error=True)
        if not cfg.get("shared") and decision == "ask" and not (ctx.consented("mcp", f"{server}__{tool}")
                                                                or self.app.approvals.allowlisted("mcp", f"{server}__{tool}")):
            # Allowlist rule: `mcp:<server>__<tool>` (glob), e.g. `mcp:github__get_*`. ctx.consented: a
            # hook context's consented tools (hookbus.hook_context; always empty for agents).
            res = await self.app.approvals.ask(ctx.session_id, "mcp_tool", {
                "subject": f"{server}.{tool}", "tool": tool, "server": server, "summary": json.dumps(args)[:300],
                "hints": hint_notes(hints), "role": ctx.role, "run_id": ctx.run_id})
            if res["status"] != "approved":
                return ToolOutput(f"User declined {server}.{tool}.", is_error=True)
        if cfg.get("shared"):
            if not (ctx.session.get("settings") or {}).get("shared_tools"):
                return ToolOutput("Shared tools are off for this session.", is_error=True)
            # Allowlist rule: `shared_tool:<server>__<tool>` (glob), e.g. `shared_tool:laptop__*`.
            if not self.app.approvals.allowlisted("shared_tool", f"{server}__{tool}"):
                res = await self.app.approvals.ask(ctx.session_id, "shared_tool", {
                    "subject": f"{server}.{tool}", "tool": tool, "machine": server,
                    "summary": json.dumps(args)[:300], "role": ctx.role})
                if res["status"] != "approved":
                    return ToolOutput("User declined the job on shared tools.", is_error=True)
        try:
            c = await self.connect(server)
            r = await asyncio.wait_for(c.session.call_tool(tool, args), 300)
        except Exception as e:  # noqa: BLE001
            await self.disconnect(server)
            return finalize_output(ctx, name, ToolOutput(f"MCP {server} error: {e}", is_error=True,
                                                         untrusted=f"mcp:{server}.{tool}"))
        texts, images = [], []
        for block in r.content or []:
            t = getattr(block, "type", "")
            if t == "text":
                texts.append(block.text)
            elif t == "image":
                images.append(ImageBlock(media_type=_attr(block, "mime_type", "mimeType") or "image/png", data=block.data))
            elif t == "resource":
                res_ = block.resource
                texts.append(getattr(res_, "text", None) or f"[resource {getattr(res_, 'uri', '')}]")
            else:
                texts.append(f"[{t} content]")
        structured = _attr(r, "structured_content", "structuredContent")
        if structured and not texts:
            texts.append(json.dumps(structured))
        # Capped (text and images, overflow saved for read_output) and marked as outside content.
        return finalize_output(ctx, name, ToolOutput("\n".join(texts) or "(no output)", images=images,
                                                     is_error=bool(_attr(r, "is_error", "isError")),
                                                     untrusted=f"mcp:{server}.{tool}"))

    def migrate_secrets(self) -> int:
        """Startup: move secret-looking env/header values still stored in SQLite into the Keychain."""
        if not keychain_enabled():
            return 0
        moved = 0
        for r in self._rows():
            fields = {}
            for kind in ("env", "headers"):
                cur = r[kind] or {}
                if any(is_secret_name(k) and isinstance(v, str) and v and not v.startswith(MASK)
                       for k, v in cur.items()):
                    try:
                        fields[kind] = store_secrets(r["name"], kind, cur, cur)
                    except ValueError as e:
                        log.warning("MCP server %s: secrets left in SQLite: %s", r["name"], e)
            if fields:
                self.app.db.update("mcp_servers", "name", r["name"], fields)
                moved += 1
        if moved:
            log.info("moved secrets of %d MCP server(s) into the Keychain", moved)
        return moved

    async def astart(self) -> None:
        try:
            self.migrate_secrets()
        except Exception:  # noqa: BLE001 — never block startup
            log.exception("MCP secret migration failed")
        try:
            self.seed_presets()
        except Exception:  # noqa: BLE001 — never block startup
            log.exception("adding built-in MCP servers failed")

    async def aclose(self) -> None:
        # In parallel: each server may take a few seconds to close, and quitting has a deadline.
        await asyncio.gather(*(self.disconnect(n) for n in list(self.conns)), return_exceptions=True)


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    mgr = MCPManager(S)
    S.mcp = mgr
    S.extensions["mcp"] = mgr

    # Connect a session's servers before each agent turn, so their tools are offered.
    async def pre_turn(sid: str) -> None:
        s = S.store.get(sid)
        if s:
            await mgr.warm(s)

    S.extensions["pre_turn"] = pre_turn

    # ------------------------------------------------------------------ skills

    @S.tools.add("read_skill", "Read a skill's SKILL.md (and the list of its other files), or one of those files "
                 "(references/, templates/, scripts/) by its path relative to the skill's folder.",
                 obj({"name": {"type": "string"}, "path": {"type": "string"}}, ["name"]), read_only=True)
    async def read_skill(ctx: ToolContext, a: dict) -> ToolOutput:
        try:
            text = read_skill_file(a["name"], a.get("path") or "")
        except (KeyError, FileNotFoundError) as e:
            return ToolOutput(str(e.args[0] if e.args else e), is_error=True)
        if ctx.role == "main" and not a.get("path"):
            from ..skills import skill_lru

            session = S.store.get(ctx.session_id)
            if session and session["settings"].get("skill_mode") == "progressive":
                updated = S.store.update(ctx.session_id, settings={"loaded_skills": skill_lru(
                    session["settings"], a["name"], int(S.config.skills.get("max_loaded", 3)))})
                if updated:
                    ctx.session = updated
        return ToolOutput(text)

    @api.get("/skills")
    async def skills() -> dict:
        return {"skills": list_skills(), "global": S.db.kv_get("skills_global", ["delegation"])}

    @api.get("/skills/{name}")
    async def skill(name: str) -> dict:
        s = get_skill(name)
        if not s:
            raise HTTPException(404)
        return s

    @api.put("/skills/{name}")
    async def put_skill(name: str, body: dict = Body(...)) -> dict:
        try:
            return save_skill(name, body["content"])
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @api.post("/skills/global")
    async def set_global(body: dict = Body(...)) -> dict:
        S.db.kv_set("skills_global", list(dict.fromkeys(body.get("names", []))))
        return {"global": S.db.kv_get("skills_global")}

    # --------------------------------------------------------------------- mcp

    @api.get("/mcp/servers")
    async def servers() -> list[dict]:
        return mgr.servers()

    @api.post("/mcp/servers")
    async def add_server(body: dict = Body(...)) -> dict:
        try:
            return await mgr.add(body)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @api.patch("/mcp/servers/{name}")
    async def patch_server(name: str, body: dict = Body(...)) -> dict:
        if not mgr.server(name):
            raise HTTPException(404)
        fields = {k: int(bool(v)) for k, v in body.items() if k in ("enabled_default", "shared")}
        S.db.update("mcp_servers", "name", name, fields)
        return mgr.server(name)  # type: ignore[return-value]

    @api.delete("/mcp/servers/{name}")
    async def del_server(name: str) -> dict:
        await mgr.remove(name)
        return {"ok": True}

    @api.post("/mcp/servers/{name}/reset")
    async def reset_server(name: str) -> dict:
        """Reset a built-in server to its definition in config (or bring back a deleted one)."""
        try:
            return await mgr.reset_preset(name)
        except KeyError:
            raise HTTPException(404, f"{name} isn't a built-in server") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @api.post("/mcp/servers/{name}/test")
    async def test(name: str) -> dict:
        return await mgr.test(name)

    @api.post("/sessions/{sid}/shared-tools")
    async def shared_tools(sid: str, body: dict = Body(...)) -> dict:
        """Changing this restarts the session's tool processes, so it's only allowed while idle."""
        if S.runner.is_running(sid):
            raise HTTPException(409, "Wait until the session is idle to change shared tools.")
        s = S.store.update(sid, settings={"shared_tools": bool(body.get("enabled"))})
        for srv in mgr.servers():
            if srv["shared"]:  # only the shared servers restart; other sessions keep their connections
                await mgr.disconnect(srv["name"])
        S.bus.publish("session.restarted", {"id": sid, "reason": "shared_tools"}, sid)
        return s
