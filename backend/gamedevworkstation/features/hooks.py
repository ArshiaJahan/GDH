"""Hooks engine: hook files (TOML), their trust and consent, built-in checks and the Unity gates.

Built on the hook bus (features/hookbus.py, app.hooks). Two kinds of hooks run here:

1. Always-on built-ins (Python, registered on the bus at startup; [hooks] enabled turns them off):
   - `tool_failure_breaker` (post_tool): the same tool failing with the same (normalized) error
     `breaker_note_at` (3) times in a row in a turn appends "change approach"; `breaker_stop_at`
     (5) ends the turn with a notice.
   - `scars.first_touch` (post_tool): POSTMORTEMS.md entries with an `- Applies to:` glob list;
     the first time in a session a tool touches a matching path, `[Project rule PM-007: …]` is
     appended to its result.
   - `context.pack` (session_start): in a Unity project or a folder with PROJECT.md, builds the
     project context pack once (PROJECT.md current milestone, TASTE.md, POSTMORTEMS.md index,
     active campaign) and freezes it in settings.context_pack; the loop appends its text to the
     system prompt. Rebuilt only on request (POST /api/hooks/context_pack), never mid-session.
   - `hooks.cards` (model_call, first call of a turn): raises the trust card for an untrusted
     hook file and the one-time "Turn on Unity gates?" offer.

2. Hook files, dispatched by one bus handler per event (`hooks.toml`):
   - the **preset** `skills/unity-router/hooks.toml` (built-in, so trusted, but off per project
     until enabled: the one-time offer card or POST /api/hooks/preset, which shows the consent
     card). Enabling stores hook_trust(project, "preset:unity-router", "preset", sha,
     {tools, commands, templates}): the exact MCP tools and command lines its gates run, so
     they then run without a card every turn (hook role ToolContext consent).
   - the project's `.gamedevworkstation/hooks.toml` and the hooks.toml of the session's *user* skills:
     ignored until trusted by hash (kind "hook_trust" card, full file shown). "Trust and allow
     its commands" consents to the commands and MCP tools it lists; "Trust, ask before
     commands" leaves them to the allowlist / a card. Any change to the file needs trust again
     (the agent may write the file; that only creates a new untrusted version).

   File format (version = 1; unknown keys are errors, invalid entries are skipped and listed):

       [[hook]]
       id = "cs-compile"                 # unique, [A-Za-z0-9_.:-]
       event = "pre_complete"            # session_start pre_tool post_tool pre_complete
                                         # pre_compact pre_merge post_merge turn_end
       tools = ["write_file"]            # pre/post_tool: fnmatch on the tool name
       paths = ["Library/**"]            # pre/post_tool: the tool's path argument (glob_match)
       changed = ["Assets/**/*.cs"]      # files changed this turn (at least one must match)
       roles = ["main", "subagent"]      # who triggered it (default both)
       phases = ["verify"]               # only in a campaign phase of these types
       action = "block" | "note" | "command" | "mcp" | "builtin"
       reason = "…"                      # block: why and how to fix
       note = "…"                        # note: appended to the tool / merge result
       run = "python3 {project}/x.py {changed}"   # command; {project} {changed} {skill:<name>}
       ok_exit = [0]                     # command: passing exit codes
       timeout_s = 60                    # command: 1-1800
       tool = "unity__read_console"      # mcp: server__tool (or mcp__server__tool)
       args = {}                         # mcp: tool arguments
       name = "unity.compile"            # builtin: see BUILTINS / add_builtin
       options = {}                      # builtin options
       on_fail = "block" | "note"        # a failing command / mcp / builtin: block (default for
                                         # pre_tool, pre_merge, pre_complete) or just report
       max_retries = 2                   # pre_complete: fix attempts before it's handed to you
       fail = "open" | "closed"          # a crashing hook: closed denies (default for pre_tool
                                         # and pre_merge), open allows and reports hooks.error
       level = "L1"                      # quality-ladder level stored with the gate result
       gate = "my.gate"                  # gate id (default: builtin name, else id)

   In a campaign or chain session, the gates its template lists in `blocking_gates` (e.g.
   unity.antipatterns for perf-pass and release) block like `on_fail = "block"` (and built-in
   `options.blocking = true`) even where the hook file makes them advisory.

   Plan only mode runs only block and note actions (and in-process built-ins); commands, MCP
   calls and the Unity gates don't run. Gate output a model sees is wrapped as untrusted.

Built-in actions (toml `action = "builtin"`): unity.compile, unity.tests, unity.antipatterns,
backlog.lint. Other features add theirs with HooksEngine.add_builtin().

Agent tool: `run_gate(name)` (main only; offered when the project has gates). REST:
GET /api/hooks, POST /api/hooks/preset, /hooks/trust, /hooks/run, /hooks/context_pack,
GET /api/hooks/unity. Events: hooks.trust_needed (+ the card), gate.result (via record_gate).
"""
from __future__ import annotations

import asyncio
import dataclasses
import fnmatch
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import time
import tomllib
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ..agent.tools import ToolContext, ToolOutput, obj, wrap_untrusted
from ..core.types import Message, TextBlock
from ..legacy import migrate_project_dir
from ..skills import builtin_skills_dir, user_skills_dir
from .hookbus import EVENTS, HookEvent, HookResult, TurnState, glob_match, hook_context
from .unity_bridge import (BridgeResult, _cmd_result, get_bridge, is_unity_project, load_script, skill_script,
                           unwrap_untrusted, UNITY_SERVER)

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

    from ..app import AppState

log = logging.getLogger(__name__)

HOOK_EVENTS = tuple(e for e in EVENTS if e != "model_call")  # model_call is internal
ACTIONS = ("block", "note", "command", "mcp", "builtin")
BLOCKING_EVENTS = ("pre_tool", "pre_merge", "pre_complete")
TOOL_EVENTS = ("pre_tool", "post_tool")
ROLES = ("main", "subagent")
PROJECT_FILE = ".gamedevworkstation/hooks.toml"
PRESET = "unity-router"          # the built-in Unity gate set: skills/unity-router/hooks.toml
USER_SKILL_PROJECT = "*"         # hook_trust.project for user skills' hook files (trusted everywhere)
MAX_FILE = 64_000
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
PLACEHOLDER_RE = re.compile(r"(?<!\$)\{([a-z][a-z0-9_-]*(?::[a-z0-9-]+)?)\}")
ENTRY_KEYS = {"id", "event", "tools", "paths", "changed", "roles", "phases", "action", "reason", "note", "run",
              "ok_exit", "timeout_s", "tool", "args", "name", "options", "on_fail", "max_retries", "fail", "level",
              "gate", "description"}
CONTEXT_PACK_MAX = 3000
BREAKER_NOTE_AT = 3
BREAKER_STOP_AT = 5


# ===================================================================== model


@dataclass
class HookEntry:
    id: str
    event: str
    action: str
    tools: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=lambda: list(ROLES))
    phases: list[str] = field(default_factory=list)
    reason: str = ""
    note: str = ""
    run: str = ""
    ok_exit: list[int] = field(default_factory=lambda: [0])
    timeout_s: int = 60
    tool: str = ""
    args: dict = field(default_factory=dict)
    name: str = ""
    options: dict = field(default_factory=dict)
    on_fail: str = "note"
    max_retries: int | None = None
    fail: str = "open"
    level: str | None = None
    gate: str | None = None
    description: str = ""

    def gate_id(self) -> str:
        return self.gate or (self.name if self.action == "builtin" else self.id)

    def mcp_subject(self) -> str:
        """`server__tool` for an mcp action."""
        t = self.tool[5:] if self.tool.startswith("mcp__") else self.tool
        return t

    def summary(self) -> dict:
        d = {"id": self.id, "event": self.event, "action": self.action, "gate": self.gate_id()}
        for k in ("tools", "paths", "changed", "phases"):
            if v := getattr(self, k):
                d[k] = v
        for k in ("reason", "note", "run", "tool", "name", "level", "description"):
            if v := getattr(self, k):
                d[k] = v
        if self.options:
            d["options"] = self.options
        return d


@dataclass
class Builtin:
    """A built-in action hook files can name (`action = "builtin"`, `name = …`).

    fn(engine, entry, ev, ac) -> HookResult | list | None (async or sync).
    needs(engine, project, entry) -> {"mcp": set("server__tool"), "run_command": set(command lines),
    "scripts": [descriptions]}: what it runs, shown on consent cards and consented by enabling.
    plan_ok: runs in Plan only mode (in-process checks only)."""

    name: str
    events: tuple[str, ...]
    fn: Callable[..., Any]
    needs: Callable[["HooksEngine", Path, HookEntry], dict] | None = None
    plan_ok: bool = False
    describe: str = ""


@dataclass
class ActionContext:
    session: dict
    project: Path
    consent: dict[str, set[str]]
    changed: list[str]
    force: bool = False
    source: "HookSource | None" = None
    prior: list[HookResult] = field(default_factory=list)  # results of earlier entries in this dispatch


@dataclass
class HookSource:
    kind: str                  # preset | project | user_skill
    name: str                  # preset / skill name, or the project file's rel path
    path: Path
    key_project: str           # hook_trust.project
    key_path: str              # hook_trust.path
    text: str
    sha: str
    entries: list[HookEntry]
    errors: list[str]
    state: str = "untrusted"   # preset: enabled | off | needs_consent; files: trusted | untrusted | changed | declined
    mode: str = ""             # files: trust_all | trust_ask
    consent: dict = field(default_factory=lambda: {"tools": [], "commands": [], "templates": []})

    @property
    def active(self) -> bool:
        return self.state in ("enabled", "trusted")

    def consent_sets(self) -> dict[str, set[str]]:
        return {"mcp": set(self.consent.get("tools") or []), "run_command": set(self.consent.get("commands") or []),
                "unity_cli": set(self.consent.get("unity_ops") or [])}

    def to_dict(self, needs: dict | None = None) -> dict:
        d = {"kind": self.kind, "name": self.name, "path": str(self.path), "sha": self.sha, "state": self.state,
             "active": self.active, "errors": self.errors, "hooks": [e.summary() for e in self.entries]}
        if self.mode:
            d["mode"] = self.mode
        if needs is not None:
            d["needs"] = needs
        return d


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# =============================================================== validation


def _str_list(v: Any, key: str, errs: list[str]) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        errs.append(f"{key} must be a list of strings")
        return []
    return [x.strip() for x in v]


def parse_hooks_toml(text: str, builtins: dict[str, Builtin]) -> tuple[list[HookEntry], list[str]]:
    """Parse and validate a hooks.toml. Returns (valid entries, problems). An invalid entry is
    left out (with its problems listed); a file that isn't TOML has no entries."""
    if len(text) > MAX_FILE:
        return [], [f"file is larger than {MAX_FILE // 1000} KB"]
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return [], [f"not valid TOML: {e}"]
    errors: list[str] = []
    if extra := sorted(set(data) - {"version", "hook"}):
        errors.append(f"unknown top-level key(s): {', '.join(extra)}")
    if data.get("version", 1) != 1:
        return [], errors + ["version must be 1"]
    hooks = data.get("hook", [])
    if not isinstance(hooks, list):
        return [], errors + ["[[hook]] must be an array of tables"]
    out: list[HookEntry] = []
    seen: set[str] = set()
    for i, h in enumerate(hooks, 1):
        where = f"hook #{i}" + (f" ({h.get('id')})" if isinstance(h, dict) and isinstance(h.get("id"), str) else "")
        e, errs = _parse_entry(h, builtins)
        if e and e.id in seen:
            errs.append(f"duplicate id {e.id!r}")
        if errs:
            errors += [f"{where}: {x}" for x in errs]
            continue
        assert e is not None
        seen.add(e.id)
        out.append(e)
    return out, errors


def _parse_entry(h: Any, builtins: dict[str, Builtin]) -> tuple[HookEntry | None, list[str]]:
    errs: list[str] = []
    if not isinstance(h, dict):
        return None, ["must be a table"]
    if extra := sorted(set(h) - ENTRY_KEYS):
        errs.append(f"unknown key(s): {', '.join(extra)}")
    hid, event, action = h.get("id"), h.get("event"), h.get("action")
    core: list[str] = []
    if not isinstance(hid, str) or not ID_RE.fullmatch(hid):
        core.append("id: 1-64 letters, digits, _ . : - (required)")
    if event not in HOOK_EVENTS:
        core.append(f"event must be one of {', '.join(HOOK_EVENTS)}")
    if action not in ACTIONS:
        core.append(f"action must be one of {', '.join(ACTIONS)}")
    if core:
        return None, errs + core
    e = HookEntry(id=hid, event=event, action=action)
    e.tools = _str_list(h.get("tools"), "tools", errs)
    e.paths = _str_list(h.get("paths"), "paths", errs)
    e.changed = _str_list(h.get("changed"), "changed", errs)
    e.phases = [p.lower() for p in _str_list(h.get("phases"), "phases", errs)]
    if "roles" in h:
        e.roles = _str_list(h.get("roles"), "roles", errs)
        if not e.roles or set(e.roles) - set(ROLES):
            errs.append("roles: main and/or subagent")
    if (e.tools or e.paths) and event not in TOOL_EVENTS:
        errs.append("tools / paths only apply to pre_tool and post_tool")
    for k in ("reason", "note", "run", "tool", "name", "description", "level", "gate"):
        v = h.get(k)
        if v is not None and not isinstance(v, str):
            errs.append(f"{k} must be a string")
        elif v is not None:
            setattr(e, k, v)
    if e.gate is not None and not ID_RE.fullmatch(e.gate):
        errs.append("gate: 1-64 letters, digits, _ . : -")
    for k in ("args", "options"):
        v = h.get(k, {})
        if not isinstance(v, dict):
            errs.append(f"{k} must be a table")
        else:
            setattr(e, k, v)
    if "ok_exit" in h:
        v = h["ok_exit"]
        if not isinstance(v, list) or not v or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
            errs.append("ok_exit must be a list of integers")
        else:
            e.ok_exit = v
    if "timeout_s" in h:
        v = h["timeout_s"]
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 1800:
            errs.append("timeout_s: 1-1800")
        else:
            e.timeout_s = v
    if "max_retries" in h:
        v = h["max_retries"]
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 5:
            errs.append("max_retries: 0-5")
        else:
            e.max_retries = v
    e.on_fail = h.get("on_fail", "block" if event in BLOCKING_EVENTS else "note")
    if e.on_fail not in ("block", "note"):
        errs.append("on_fail must be block or note")
    elif e.on_fail == "block" and event not in BLOCKING_EVENTS:
        errs.append(f"on_fail = block only works for {', '.join(BLOCKING_EVENTS)}")
    e.fail = h.get("fail", "closed" if event in ("pre_tool", "pre_merge") else "open")
    if e.fail not in ("open", "closed"):
        errs.append("fail must be open or closed")
    # action-specific
    if action == "block":
        if event not in BLOCKING_EVENTS:
            errs.append(f"action block only works for {', '.join(BLOCKING_EVENTS)}")
        if not e.reason.strip():
            errs.append("block needs a reason (what to do instead)")
    elif action == "note":
        if event not in ("post_tool", "post_merge"):
            errs.append("action note only works for post_tool and post_merge")
        if not e.note.strip():
            errs.append("note needs note text")
    elif action == "command":
        if not e.run.strip():
            errs.append("command needs run")
        for p in PLACEHOLDER_RE.findall(e.run):
            if p not in ("project", "changed") and not p.startswith("skill:"):
                errs.append(f"unknown placeholder {{{p}}} (use {{project}}, {{changed}}, {{skill:<name>}})")
    elif action == "mcp":
        if not re.fullmatch(r"(?:mcp__)?[A-Za-z0-9_-]+__[A-Za-z0-9_-]+", e.tool):
            errs.append("mcp needs tool = \"<server>__<tool>\"")
    elif action == "builtin":
        b = builtins.get(e.name)
        if not b:
            errs.append(f"unknown builtin {e.name!r} (known: {', '.join(sorted(builtins))})")
        elif event not in b.events:
            errs.append(f"builtin {e.name} runs on {', '.join(b.events)}, not {event}")
    return (None if errs else e), errs


# =============================================================== small helpers


def project_of(session: dict | None) -> Path | None:
    f = (session or {}).get("folder")
    if not f:
        return None
    try:
        p = Path(f).expanduser().resolve()
    except OSError:
        return None
    return p if p.is_dir() else None


def rel_path(p: str, *roots: Path | None) -> str:
    """A tool's path argument as a project-relative POSIX path (URIs like
    mcpforunity://path/Assets/x.cs and file:///abs are understood)."""
    s = re.sub(r"^[A-Za-z][\w+.-]*://(?:path/)?", "", str(p).strip())
    if s.startswith("//"):
        s = s[1:]
    path = Path(s).expanduser()
    if path.is_absolute():
        for r in roots:
            if not r:
                continue
            for a, b in ((path, r), (path.resolve(), r.resolve())):
                try:
                    return a.relative_to(b).as_posix()
                except ValueError:
                    continue
        return path.as_posix()
    return os.path.normpath(s).replace("\\", "/").lstrip("/") if s not in ("", ".") else ""


def skill_dir(name: str) -> Path | None:
    for root in (builtin_skills_dir(), user_skills_dir()):
        d = root / name
        if (d / "SKILL.md").is_file():
            return d
    return None


def render_command(template: str, project: Path, changed: list[str]) -> str:
    """Fill {project} {changed} {skill:<name>} (each shell-quoted). Raises ValueError for an
    unknown skill."""
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key == "project":
            return shlex.quote(str(project))
        if key == "changed":
            return " ".join(shlex.quote(c) for c in changed)
        if key.startswith("skill:"):
            d = skill_dir(key[6:])
            if not d:
                raise ValueError(f"no skill named {key[6:]}")
            return shlex.quote(str(d))
        return m.group(0)

    return PLACEHOLDER_RE.sub(sub, template)


def _fence(text: str, lang: str = "") -> str:
    ticks = max([3, *(len(m) + 1 for m in re.findall(r"`{3,}", text))])
    return f"{'`' * ticks}{lang}\n{text}\n{'`' * ticks}"


def _section(md: str, heading: re.Pattern) -> str:
    """The body of the first `## ` section whose heading matches, up to the next # / ## heading."""
    lines = md.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r"^#{1,3}\s", ln) and heading.search(ln):
            level = len(ln) - len(ln.lstrip("#"))
            body = []
            for x in lines[i + 1:]:
                m = re.match(r"^(#{1,6})\s", x)
                if m and len(m.group(1)) <= level:
                    break
                body.append(x)
            return "\n".join(body).strip()
    return ""


def _list_items(body: str, n: int) -> list[str]:
    items = [re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", ln).strip() for ln in body.splitlines()
             if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+\S", ln)]
    return items[:n]


def _cut(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _read(p: Path, limit: int = 400_000) -> str | None:
    try:
        if not p.is_file():
            return None
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return None


# ------------------------------------------------------------ postmortems

PM_HEAD = re.compile(r"^#{2,4}\s+(PM-\d+)\b\s*[:\-–—]?\s*(.*?)\s*$", re.M)


def parse_postmortems(text: str) -> list[dict]:
    """POSTMORTEMS.md entries: [{id, num, title, rule, globs}] (### PM-007 Title (date) blocks
    with `- Rule:` and `- Applies to: glob, glob` lines)."""
    heads = list(PM_HEAD.finditer(text))
    out = []
    for i, m in enumerate(heads):
        block = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        rule = re.search(r"^\s*[-*]\s*Rule:\s*(.+)$", block, re.M)
        applies = re.search(r"^\s*[-*]\s*Applies to:\s*(.+)$", block, re.M)
        globs = []
        if applies:
            globs = [g.strip().strip("`").strip() for g in re.split(r"[,;]", applies.group(1))]
            globs = [g for g in globs if g and g.lower() not in ("none", "-", "n/a", "all")]
        title = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", m.group(2)).strip()
        out.append({"id": m.group(1), "num": int(m.group(1)[3:]), "title": title,
                    "rule": rule.group(1).strip() if rule else "", "globs": globs})
    return out


# ================================================================= engine


class HooksEngine:
    """app.extensions["hooks_engine"]."""

    def __init__(self, app: "AppState"):
        self.app = app
        self.builtins: dict[str, Builtin] = {}
        self._cards: dict[tuple, str] = {}                      # (project, path, kind) → open approval id
        self._tasks: set[asyncio.Task] = set()
        self._scars_seen: OrderedDict[str, set[str]] = OrderedDict()  # session → PM ids already noted
        self._pm_cache: dict[str, tuple[float, list[dict]]] = {}
        self._file_cache: dict[str, tuple[tuple, tuple]] = {}   # path → ((mtime, size), (text, sha, entries, errors))
        _register_builtins(self)

    # ---------------------------------------------------------- builtins

    def add_builtin(self, name: str, fn: Callable[..., Any], events: tuple[str, ...] | list[str], *,
                    needs: Callable[["HooksEngine", Path, HookEntry], dict] | None = None,
                    plan_ok: bool = False, describe: str = "") -> None:
        """Make `name` available to hook files as `action = "builtin"` (same name replaces)."""
        self.builtins[name] = Builtin(name, tuple(events), fn, needs, plan_ok, describe)
        self._file_cache.clear()

    # ----------------------------------------------------------- config

    def _cfg(self) -> dict:
        return getattr(self.app.config, "hooks", None) or {}

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return int(self._cfg().get(key, default))
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------ files

    def _load(self, path: Path) -> tuple[str, str, list[HookEntry], list[str]] | None:
        try:
            st = path.stat()
        except OSError:
            return None
        sig = (st.st_mtime_ns, st.st_size)
        hit = self._file_cache.get(str(path))
        if hit and hit[0] == sig:
            return hit[1]  # type: ignore[return-value]
        if st.st_size > MAX_FILE:
            res: tuple = ("", "", [], [f"file is larger than {MAX_FILE // 1000} KB"])
        else:
            text = _read(path) or ""
            entries, errors = parse_hooks_toml(text, self.builtins)
            res = (text, sha256(text), entries, errors)
        self._file_cache[str(path)] = (sig, res)
        return res  # type: ignore[return-value]

    def _trust_rows(self, *projects: str) -> dict[tuple[str, str, str], dict]:
        q = ",".join("?" * len(projects))
        rows = self.app.db.all(f"SELECT * FROM hook_trust WHERE project IN ({q})", list(projects))
        out = {}
        for r in rows:
            try:
                r["detail"] = json.loads(r["detail"] or "{}")
            except ValueError:
                r["detail"] = {}
            out[(r["project"], r["path"], r["kind"])] = r
        return out

    @staticmethod
    def preset_path(name: str = PRESET) -> Path:
        return builtin_skills_dir() / name / "hooks.toml"

    def sources(self, session: dict | None = None, *, project: Path | None = None) -> list[HookSource]:
        """Every hook file that applies to the session's project, with its trust state."""
        project = project or project_of(session)
        if not project:
            return []
        pkey = str(project)
        rows = self._trust_rows(pkey, USER_SKILL_PROJECT)
        out: list[HookSource] = []
        # the built-in preset(s): skills shipped with the app that have a hooks.toml
        presets = {}
        root = builtin_skills_dir()
        for f in sorted(root.glob("*/hooks.toml")) if root.is_dir() else []:
            got = self._load(f)
            if not got:
                continue
            text, sha, entries, errors = got
            name = f.parent.name
            presets[name] = sha
            src = HookSource("preset", name, f, pkey, f"preset:{name}", text, sha, entries, errors, state="off")
            row = rows.get((pkey, src.key_path, "preset"))
            if row:
                src.consent = row["detail"]
                need = self.needs(project, entries)
                have = {k: set(row["detail"].get(k) or []) for k in ("tools", "commands", "templates")}
                ok = row["sha256"] == sha or all(set(need[k]) <= have[k] for k in have)
                src.state = "enabled" if ok else "needs_consent"
            out.append(src)
        # the project's own file
        migrate_project_dir(project)  # first use after the rename (legacy.py)
        pf = project / PROJECT_FILE
        if got := self._load(pf):
            out.append(self._file_source("project", PROJECT_FILE, pf, pkey, PROJECT_FILE, got, rows))
        # hook files of the session's user skills
        for name in sorted(_session_skills(session)):
            f = user_skills_dir() / name / "hooks.toml"
            if not f.is_file() or not (got := self._load(f)):
                continue
            if presets.get(name) == got[1]:
                continue  # an unchanged copy of the built-in preset (Customize copies the folder)
            out.append(self._file_source("user_skill", name, f, USER_SKILL_PROJECT, str(f), got, rows))
        return out

    def _file_source(self, kind: str, name: str, path: Path, kproj: str, kpath: str, got: tuple,
                     rows: dict) -> HookSource:
        text, sha, entries, errors = got
        src = HookSource(kind, name, path, kproj, kpath, text, sha, entries, errors)
        row = rows.get((kproj, kpath, "file"))
        if row and row["sha256"] == sha:
            src.state, src.mode = "trusted", str(row["detail"].get("mode") or "trust_all")
            src.consent = row["detail"]
        elif (d := rows.get((kproj, kpath, "declined"))) and d["sha256"] == sha:
            src.state = "declined"
        elif row:
            src.state = "changed"
        return src

    def active(self, session: dict | None) -> list[tuple[HookEntry, HookSource]]:
        return [(e, s) for s in self.sources(session) if s.active for e in s.entries]

    def needs(self, project: Path, entries: list[HookEntry]) -> dict[str, list[str]]:
        """What these entries run: MCP tools (server__tool), command lines (built-ins), command
        templates (command entries) and informational scripts."""
        tools: set[str] = set()
        cmds: set[str] = set()
        templates: set[str] = set()
        unity_ops: set[str] = set()
        scripts: list[str] = []
        for e in entries:
            if e.action == "command":
                templates.add(e.run)
            elif e.action == "mcp":
                tools.add(e.mcp_subject())
            elif e.action == "builtin" and (b := self.builtins.get(e.name)) and b.needs:
                n = b.needs(self, project, e) or {}
                tools |= set(n.get("mcp") or ())
                cmds |= set(n.get("run_command") or ())
                unity_ops |= set(n.get("unity_cli") or ())
                scripts += [s for s in n.get("scripts") or () if s not in scripts]
        out = {"tools": sorted(tools), "commands": sorted(cmds), "templates": sorted(templates), "scripts": scripts}
        if unity_ops:  # route-independent Unity op keys (the official Unity CLI backend)
            out["unity_ops"] = sorted(unity_ops)
        return out

    # ------------------------------------------------------------ trust

    def trust(self, src: HookSource, project: Path, mode: str = "trust_all", sha: str | None = None) -> None:
        """Trust this exact version (sha) of a hook file. trust_all also consents to the commands
        and MCP tools it lists."""
        detail: dict[str, Any] = {"mode": mode}
        if mode == "trust_all":
            detail.update(self.needs(project, src.entries))
        self.app.db.insert("hook_trust", {"project": src.key_project, "path": src.key_path, "kind": "file",
                                          "sha256": sha or src.sha, "detail": detail, "approved_at": time.time()},
                           replace=True)
        self.app.db.execute("DELETE FROM hook_trust WHERE project=? AND path=? AND kind='declined'",
                            [src.key_project, src.key_path])

    def decline(self, src: HookSource, sha: str | None = None) -> None:
        self.app.db.insert("hook_trust", {"project": src.key_project, "path": src.key_path, "kind": "declined",
                                          "sha256": sha or src.sha, "detail": {}, "approved_at": time.time()},
                           replace=True)

    def untrust(self, key_project: str, key_path: str) -> int:
        cur = self.app.db.execute("DELETE FROM hook_trust WHERE project=? AND path=? AND kind IN ('file','declined')",
                                  [key_project, key_path])
        return cur.rowcount

    def enable_preset(self, project: Path, name: str = PRESET) -> dict:
        src = next((s for s in self.sources(project=project) if s.kind == "preset" and s.name == name), None)
        if not src:
            raise KeyError(name)
        detail = self.needs(project, src.entries)
        self.app.db.insert("hook_trust", {"project": str(project), "path": f"preset:{name}", "kind": "preset",
                                          "sha256": src.sha, "detail": detail, "approved_at": time.time()},
                           replace=True)
        self.app.bus.publish("hooks.updated", {"project": str(project), "preset": name, "enabled": True})
        return detail

    def disable_preset(self, project: Path, name: str = PRESET) -> None:
        self.app.db.execute("DELETE FROM hook_trust WHERE project=? AND path=? AND kind='preset'",
                            [str(project), f"preset:{name}"])
        self.app.bus.publish("hooks.updated", {"project": str(project), "preset": name, "enabled": False})

    def gates_enabled(self, session: dict) -> bool:
        """Whether the session's project has any active pre_complete gate (offers run_gate)."""
        try:
            return any(e.event == "pre_complete" for e, _ in self.active(session))
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------ cards

    def _card_open(self, key: tuple) -> bool:
        aid = self._cards.get(key)
        if not aid:
            return False
        row = self.app.db.one("SELECT status FROM approvals WHERE id=?", [aid])
        if row and row["status"] == "pending":
            return True
        self._cards.pop(key, None)
        return False

    def _ask(self, sid: str | None, key: tuple, kind: str, payload: dict,
             on_answer: Callable[[dict], None]) -> str | None:
        """Raise a card without waiting for it (the turn goes on; the hook file stays ignored until
        it's answered). None when the same card is already open."""
        if self._card_open(key):
            return None
        aid = self.app.approvals.request(sid, kind, payload)
        self._cards[key] = aid

        async def wait() -> None:
            try:
                res = await self.app.approvals.wait(aid)
            finally:
                self._cards.pop(key, None)
            row = self.app.db.one("SELECT status FROM approvals WHERE id=?", [aid])
            if row and row["status"] == "expired":
                return  # the run was stopped: ask again next time, don't count it as an answer
            try:
                on_answer(res)
            except Exception:  # noqa: BLE001
                log.warning("hook card answer failed", exc_info=True)

        t = asyncio.create_task(wait())
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return aid

    def request_trust(self, sid: str | None, src: HookSource, project: Path) -> str | None:
        """The hook_trust card for one file version (full file plus what it would run)."""
        needs = self.needs(project, src.entries)
        where = f"{project.name}/{PROJECT_FILE}" if src.kind == "project" else f"skill {src.name}: hooks.toml"
        md = [f"**{where}** asks GameDevWorkstation to run hooks in this project. It's ignored until you trust it, and "
              "any later change to it asks again."]
        md += _needs_md(needs)
        blocks = [e.id for e in src.entries if e.action in ("block", "note")]
        if blocks:
            md.append("**Blocks and notes:** " + ", ".join(f"`{b}`" for b in blocks))
        if src.errors:
            md.append("**Problems (these entries are skipped):**\n" + "\n".join(f"- {x}" for x in src.errors[:10]))
        md.append(_fence(src.text, "toml"))
        payload = {"subject": f"Trust hooks in {where}?", "markdown": "\n\n".join(md),
                   "path": str(src.path), "sha256": src.sha, "project": str(project),
                   "buttons": [{"id": "trust_all", "label": "Trust and allow its commands", "decision": "approve",
                                "style": "primary"},
                               {"id": "trust_ask", "label": "Trust, ask before commands", "decision": "approve"},
                               {"id": "ignore", "label": "Ignore this version", "decision": "deny", "style": "ghost"}]}
        sha = src.sha

        def answer(res: dict) -> None:
            if res.get("status") == "approved":
                self.trust(src, project, "trust_ask" if res.get("choice") == "trust_ask" else "trust_all", sha)
                self.app.bus.publish("hooks.updated", {"project": str(project), "path": str(src.path), "trusted": True}, sid)
            elif res.get("choice") == "ignore":
                self.decline(src, sha)

        aid = self._ask(sid, (src.key_project, src.key_path, "file"), "hook_trust", payload, answer)
        if aid:
            self.app.bus.publish("hooks.trust_needed", {"project": str(project), "path": str(src.path),
                                                        "kind": src.kind, "approval_id": aid}, sid)
        return aid

    def request_preset(self, sid: str | None, project: Path, name: str = PRESET, *, offer: bool = False) -> str | None:
        """The consent card for the built-in Unity gates (`offer`: the one-time first-use offer)."""
        src = next((s for s in self.sources(project=project) if s.kind == "preset" and s.name == name), None)
        if not src:
            raise KeyError(name)
        needs = self.needs(project, src.entries)
        gates = [e for e in src.entries]
        md = [("This looks like a Unity project. " if offer else "")
              + "GameDevWorkstation can check the agent's work at fixed points, so a turn can't end red:"]
        md.append("\n".join(f"- `{e.gate_id() if e.action == 'builtin' else e.id}` ({_event_label(e.event)}): "
                            f"{e.description or e.reason or e.note or e.name}" for e in gates))
        md += _needs_md(needs, consent=True)
        md.append("You can turn this off any time (Quality card → Unity gates).")
        payload = {"subject": f"Turn on Unity gates for {project.name}?", "markdown": "\n\n".join(md),
                   "project": str(project), "preset": name,
                   "buttons": [{"id": "enable", "label": "Turn on Unity gates", "decision": "approve",
                                "style": "primary"},
                               {"id": "not_now", "label": "Not now", "decision": "deny", "style": "ghost"}]}

        def answer(res: dict) -> None:
            if res.get("status") == "approved":
                self.enable_preset(project, name)

        return self._ask(sid, (str(project), f"preset:{name}", "preset"), "hook_preset", payload, answer)

    async def check_cards(self, ev: HookEvent) -> None:
        """model_call (first call of a turn, main agent): ask about untrusted hook files and offer
        the Unity gates once per Unity project."""
        if ev.extra.get("call") != 1 or ev.ctx.role != "main":
            return None
        session = ev.ctx.session
        project = project_of(session)
        if not project:
            return None
        srcs = await asyncio.to_thread(self.sources, session)
        for s in srcs:
            if s.kind in ("project", "user_skill") and s.state in ("untrusted", "changed"):
                self.request_trust(ev.session_id, s, project)
        preset = next((s for s in srcs if s.kind == "preset" and s.name == PRESET), None)
        if preset and preset.state == "off" and is_unity_project(project) and self._uses_unity_skill(session):
            key = (str(project), f"preset:{PRESET}", "offer")
            if not self.app.db.one("SELECT 1 FROM hook_trust WHERE project=? AND path=? AND kind='offer'",
                                   [key[0], key[1]]):
                self.app.db.insert("hook_trust", {"project": key[0], "path": key[1], "kind": "offer", "sha256": "",
                                                  "detail": {"session_id": ev.session_id}, "approved_at": time.time()},
                                   replace=True)  # one-time, whatever the answer
                self.request_preset(ev.session_id, project, PRESET, offer=True)
        return None

    def _uses_unity_skill(self, session: dict) -> bool:
        return any(UNITY_SERVER in self.app.config.skill_mcp_servers(n) for n in _session_skills(session))

    # --------------------------------------------------------- dispatch

    async def dispatch(self, ev: HookEvent) -> list[HookResult] | None:
        """The bus handler for every hook-file event."""
        session = ev.ctx.session
        project = project_of(session)
        if not project:
            return None
        entries = [(e, s) for e, s in await asyncio.to_thread(self.active, session) if e.event == ev.name]
        if not entries:
            return None
        cache: dict[str, Any] = {}
        out: list[HookResult] = []
        for e, s in entries:
            try:
                changed = await self._match(e, ev, project, cache)
                if changed is None:
                    continue
                res = await self.run_entry(e, s, ev, project, changed, prior=out)
            except asyncio.CancelledError:
                raise
            except Exception as ex:  # noqa: BLE001 — a hook never takes the loop down
                res = [self._crashed(e, ev, ex)]
            for r in res:
                r.hook = r.hook or e.id
                out.append(r)
            if ev.name in ("pre_tool", "pre_merge") and any(r.action == "block" for r in res):
                break
        return out

    def _crashed(self, e: HookEntry, ev: HookEvent, ex: Exception) -> HookResult:
        err = f"{type(ex).__name__}: {ex}"[:500]
        log.warning("hook %s (%s) failed: %s", e.id, ev.name, err, exc_info=True)
        try:
            self.app.bus.publish("hooks.error", {"event": ev.name, "hook": e.id, "error": err, "fail": e.fail,
                                                 "tool": ev.tool}, ev.session_id)
        except Exception:  # noqa: BLE001
            pass
        gate = e.gate_id() if ev.name in ("pre_complete", "post_merge") else None
        if e.fail == "closed":
            return HookResult(action="block", status="error", hook=e.id, gate=gate,
                              reason=f"the check {e.id} failed ({err}), so this was blocked to be safe.")
        return HookResult(action="allow", status="error", hook=e.id, gate=gate, reason=err)

    async def _match(self, e: HookEntry, ev: HookEvent, project: Path, cache: dict, *,
                     force: bool = False) -> list[str] | None:
        """None when the entry doesn't apply; else the files its {changed} stands for."""
        if ev.ctx.role in ROLES and ev.ctx.role not in e.roles:
            return None
        rels: list[str] = []
        if ev.name in TOOL_EVENTS:
            if e.tools and not (ev.tool and any(fnmatch.fnmatchcase(ev.tool, t) for t in e.tools)):
                return None
            rels = [r for p in ev.path_args() if (r := rel_path(p, ev.ctx.folder, project))]
            if e.paths and not any(glob_match(r, g) for r in rels for g in e.paths):
                return None
        if e.phases and not force and self.phase_type(ev.ctx.session) not in e.phases:
            return None
        if e.changed or (ev.name not in TOOL_EVENTS and e.action == "command" and "{changed}" in e.run):
            if "changed" not in cache:
                t = ev.turn
                cache["changed"] = await asyncio.to_thread(t.changed_files) if t and t.folder else []
            hits = [c for c in cache["changed"] if not e.changed or any(glob_match(c, g) for g in e.changed)]
            if e.changed and not hits and not force:
                return None
            return hits[:500]
        return rels

    def phase_type(self, session: dict) -> str | None:
        """The type (research | plan | build | wire | verify | prune) of the session's current
        campaign phase, if it's in a campaign."""
        cid = ((session or {}).get("settings") or {}).get("campaign_id")
        if not cid:
            return None
        try:
            row = self.app.db.one("SELECT phase, phases FROM campaigns WHERE id=?", [cid])
            phases = json.loads(row["phases"] or "[]") if row else []
            p = phases[int(row["phase"])] if row and 0 <= int(row["phase"]) < len(phases) else None
            return str((p or {}).get("type") or "").lower() or None
        except Exception:  # noqa: BLE001
            return None

    def blocking_gates(self, session: dict | None) -> set[str]:
        """Gate ids the session's campaign or chain makes blocking (its template's blocking_gates),
        while it isn't done or abandoned."""
        cid = ((session or {}).get("settings") or {}).get("campaign_id")
        if not cid:
            return set()
        try:
            row = self.app.db.one("SELECT status, breaker FROM campaigns WHERE id=?", [cid])
            if not row or row["status"] in ("done", "abandoned"):
                return set()
            gates = (json.loads(row["breaker"] or "{}") or {}).get("blocking_gates") or []
            return {str(g) for g in gates if isinstance(g, str)}
        except Exception:  # noqa: BLE001 — the campaigns table belongs to another feature
            return set()

    async def run_entry(self, e: HookEntry, src: HookSource | None, ev: HookEvent, project: Path,
                        changed: list[str], *, force: bool = False,
                        prior: list[HookResult] | None = None) -> list[HookResult]:
        """Run one entry's action. Plan only mode runs only block / note (and plan_ok built-ins)."""
        session = ev.ctx.session
        if e.event in BLOCKING_EVENTS and (bg := self.blocking_gates(session)) and (e.gate_id() in bg or e.id in bg):
            e = dataclasses.replace(e, on_fail="block", options={**(e.options or {}), "blocking": True})
        plan = session.get("mode") == "plan"
        consent = src.consent_sets() if src else {"mcp": set(), "run_command": set()}
        ac = ActionContext(session, project, consent, changed, force, src, list(prior or []))
        if e.action == "block":
            return [HookResult(action="block", reason=e.reason, gate=e.gate_id(), status="fail", level=e.level,
                               max_retries=e.max_retries, hook=e.id)]
        if e.action == "note":
            return [HookResult(action="note", note=e.note, hook=e.id)]
        if e.action == "builtin":
            b = self.builtins[e.name]
            if plan and not b.plan_ok:
                return []
            r = b.fn(self, e, ev, ac)
            if asyncio.iscoroutine(r):
                r = await r
            res = [] if r is None else list(r) if isinstance(r, (list, tuple)) else [r]
        elif plan:
            return []
        elif e.action == "command":
            res = await self._run_command(e, ev, ac)
        else:
            res = await self._run_mcp(e, ev, ac)
        for r in res:
            r.hook = r.hook or e.id
            if r.max_retries is None and e.max_retries is not None:
                r.max_retries = e.max_retries
            if r.level is None and e.level:
                r.level = e.level
        self._after(e, ev, res)
        return res

    def _after(self, e: HookEntry, ev: HookEvent, res: list[HookResult]) -> None:
        """Fail open, loudly: a notice under the chat for a gate that couldn't run (once per turn
        and gate). Gate results of post_merge are recorded here (the loop records pre_complete)."""
        sid = ev.session_id
        for r in res:
            if r.status in ("skipped", "error") and r.gate and ev.name in ("pre_complete", "post_merge") \
                    and self._cfg().get("fail_open_notice", True):
                seen = ev.turn.data.setdefault("hooks.notices", set()) if ev.turn else set()
                if r.id not in seen:
                    seen.add(r.id)
                    self.notice(sid, "gate_skipped", f"Gate {r.id} {'skipped' if r.status == 'skipped' else 'errored'}: "
                                                     f"{_cut(r.reason, 400)}")
            if ev.name == "post_merge" and r.gate:
                try:
                    self.app.hooks.record_gate(sid, r, campaign_id=(ev.ctx.session.get("settings") or {}).get("campaign_id"))
                except Exception:  # noqa: BLE001
                    log.warning("recording gate %s failed", r.id, exc_info=True)

    def notice(self, sid: str, kind: str, text: str) -> None:
        """A note for the user under the chat; never sent to the model."""
        self.app.store.add_message(sid, Message(role="assistant", content=[TextBlock(text=text)], meta={"notice": kind}))

    # ------------------------------------------------- command / mcp

    def outcome(self, e: HookEntry, ev: HookEvent, ok: bool, summary: str, raw: str, *,
                status: str | None = None, evidence: list | None = None, source: str = "") -> HookResult | None:
        """Turn a check's outcome into the result its event needs. raw = outside text (wrapped as
        untrusted wherever a model reads it)."""
        gid = e.gate_id()
        src = source or f"hook:{e.id}"
        if status in ("skipped", "error"):
            return HookResult(gate=gid, status=status, reason=summary, evidence=evidence or [], hook=e.id)
        if ok:
            if ev.name in ("pre_complete", "post_merge"):
                return HookResult(gate=gid, status="pass", reason=summary, evidence=evidence or [], hook=e.id)
            return None
        if ev.name == "pre_complete" and e.on_fail == "block":
            return HookResult(action="block", gate=gid, status="fail", reason=summary, untrusted=_cut(raw, 6000),
                              evidence=evidence or [], hook=e.id)
        if ev.name in ("pre_tool", "pre_merge") and e.on_fail == "block":
            text = summary + (("\n\n" + wrap_untrusted(_cut(raw, 4000), src)) if raw.strip() else "")
            return HookResult(action="block", gate=gid, status="fail", reason=text, evidence=evidence or [], hook=e.id)
        note = f"[{gid}] {summary}" + (("\n" + wrap_untrusted(_cut(raw, 4000), src)) if raw.strip() else "")
        if ev.name == "pre_complete":
            return HookResult(gate=gid, status="fail", reason=summary, note=note, evidence=evidence or [], hook=e.id)
        return HookResult(action="note", gate=gid if ev.name == "post_merge" else None, status="fail",
                          note=note, reason=summary, evidence=evidence or [], hook=e.id)

    async def _run_command(self, e: HookEntry, ev: HookEvent, ac: ActionContext) -> list[HookResult]:
        cmd = render_command(e.run, ac.project, ac.changed)
        consent = {k: set(v) for k, v in ac.consent.items()}
        if ac.source and e.run in set(ac.source.consent.get("templates") or []):
            consent.setdefault("run_command", set()).add(cmd)  # the trusted file listed this template
        ctx = hook_context(self.app, ac.session, consent=consent)
        out = await self.app.tools.run(ctx, "run_command", {"command": cmd, "timeout_s": e.timeout_s})
        code, body, res = _cmd_result(out.text)
        ev_ = [{"command": cmd, "exit_code": code, "result": res}]
        if code is None:
            r = self.outcome(e, ev, False, f"{e.id} didn't run: {_cut(out.text, 300)}", "", status="skipped", evidence=ev_)
        elif code in e.ok_exit:
            r = self.outcome(e, ev, True, f"{e.id} passed" + (f" ({res})" if res else ""), body, evidence=ev_)
        else:
            why = f"{e.id} failed (exit {code})" + (f": {res}" if res else "") + (f". {e.reason}" if e.reason else "")
            r = self.outcome(e, ev, False, why, body, evidence=ev_, source=f"command:{e.id}")
        return [r] if r else []

    async def _run_mcp(self, e: HookEntry, ev: HookEvent, ac: ActionContext) -> list[HookResult]:
        from .mcp_feature import tool_name

        mgr = self.app.mcp
        subject = e.mcp_subject()
        server, tool = subject.split("__", 1)
        name = tool_name(server, tool)
        if mgr is None:
            r = self.outcome(e, ev, False, "MCP isn't available", "", status="skipped")
            return [r] if r else []
        if not mgr.owns(name):
            try:
                await asyncio.wait_for(mgr.connect(server), 30)
            except Exception as ex:  # noqa: BLE001
                r = self.outcome(e, ev, False, f"MCP server {server} isn't reachable ({_cut(str(ex), 200)})", "",
                                 status="skipped")
                return [r] if r else []
        consent = {k: set(v) for k, v in ac.consent.items()}
        ctx = hook_context(self.app, ac.session, consent=consent)
        out = await mgr.call(ctx, name, dict(e.args))
        raw = unwrap_untrusted(out.text)
        r = self.outcome(e, ev, not out.is_error, f"{e.id}: {server}.{tool} " + ("failed" if out.is_error else "ok"),
                         raw, source=f"mcp:{server}.{tool}")
        return [r] if r else []

    # ----------------------------------------------------------- gates

    def gate_entries(self, session: dict) -> list[tuple[HookEntry, HookSource | None]]:
        return [(e, s) for e, s in self.active(session) if e.event == "pre_complete"]

    def gate_names(self, session: dict) -> list[str]:
        return list(dict.fromkeys(e.gate_id() for e, _ in self.gate_entries(session)))

    async def run_gate(self, session: dict, name: str, *, record: bool = True) -> HookResult:
        """Run one gate now (run_gate tool, POST /api/hooks/run), ignoring its `changed` and
        `phases` conditions, and record the result in gate_runs (attempt 0). Raises KeyError for
        an unknown gate; ValueError without a project folder."""
        project = project_of(session)
        if not project:
            raise ValueError("This session has no folder.")
        cands = [(e, s) for e, s in self.gate_entries(session) if name in (e.gate_id(), e.id)]
        if not cands and (b := self.builtins.get(name)) and "pre_complete" in b.events:
            preset = next((s for s in self.sources(session) if s.kind == "preset" and s.active), None)
            cands = [(HookEntry(id=name, event="pre_complete", action="builtin", name=name, on_fail="block"), preset)]
        if not cands:
            raise KeyError(name)
        e, src = cands[0]
        sid = session["id"]
        t0 = time.time()
        turn = self.app.hooks.turn(sid) or TurnState(sid, self.app.turn_started.get(sid) or t0, folder=project)
        ctx = ToolContext(app=self.app, session=session, run_id=f"gate:{sid}", role="main")
        ev = HookEvent("pre_complete", ctx, turn=turn)
        changed = await self._match(e, ev, project, {}, force=True) or []
        try:
            res = await self.run_entry(e, src, ev, project, changed, force=True)
        except asyncio.CancelledError:
            raise
        except Exception as ex:  # noqa: BLE001
            res = [self._crashed(e, ev, ex)]
        r = res[0] if res else HookResult(gate=e.gate_id(), status="skipped", reason="nothing to check", hook=e.id)
        r.hook = r.hook or e.id
        if record:
            self.app.hooks.record_gate(sid, r, attempt=0, started_at=t0,
                                       campaign_id=(session.get("settings") or {}).get("campaign_id"))
        return r

    # ------------------------------------------------ always-on built-ins

    def breaker(self, ev: HookEvent) -> HookResult | None:
        """tool_failure_breaker (post_tool, main agent)."""
        t, out = ev.turn, ev.output
        if t is None or out is None or ev.ctx.role != "main" or not ev.tool:
            return None
        counts: dict[tuple[str, str], int] = t.data.setdefault("tool_failure_breaker", {})
        if not out.is_error:
            for k in [k for k in counts if k[0] == ev.tool]:
                counts.pop(k)
            return None
        key = (ev.tool, error_signature(out.text))
        n = counts[key] = counts.get(key, 0) + 1
        note_at = max(self._cfg_int("breaker_note_at", BREAKER_NOTE_AT), 2)
        stop_at = max(self._cfg_int("breaker_stop_at", BREAKER_STOP_AT), note_at + 1)
        if n >= stop_at:
            t.request_stop(f"Stopped: {ev.tool} failed {n} times in a row with the same error "
                           f"({_cut(key[1], 160)}). Look at the approach before continuing.", kind="tool_failure_breaker")
            return HookResult(action="note", hook="tool_failure_breaker",
                              note=f"[GameDevWorkstation: {ev.tool} failed {n} times in a row with the same error; the turn "
                                   "stops here.]")
        if n >= note_at:
            return HookResult(action="note", hook="tool_failure_breaker",
                              note=f"[GameDevWorkstation: {ev.tool} has failed {n} times in a row with the same error. Don't "
                                   "retry the same call: change approach (other arguments, another tool, or ask the "
                                   "user).]")
        return None

    def _postmortems(self, project: Path) -> list[dict]:
        p = project / "POSTMORTEMS.md"
        try:
            mtime = p.stat().st_mtime
        except OSError:
            return []
        hit = self._pm_cache.get(str(p))
        if hit and hit[0] == mtime:
            return hit[1]
        rules = parse_postmortems(_read(p) or "")
        self._pm_cache[str(p)] = (mtime, rules)
        return rules

    def scars(self, ev: HookEvent) -> HookResult | None:
        """scars.first_touch (post_tool)."""
        paths = ev.path_args()
        if not paths:
            return None
        project = project_of(ev.ctx.session)
        if not project:
            return None
        rules = [r for r in self._postmortems(project) if r["globs"] and r["rule"]]
        if not rules:
            return None
        rels = [r for p in paths if (r := rel_path(p, ev.ctx.folder, project))]
        seen = self._scars_seen.setdefault(ev.session_id, set())
        self._scars_seen.move_to_end(ev.session_id)
        while len(self._scars_seen) > 500:
            self._scars_seen.popitem(last=False)
        notes = []
        for r in rules:
            if r["id"] in seen:
                continue
            if any(glob_match(p, g) for p in rels for g in r["globs"]):
                seen.add(r["id"])
                notes.append(f"[Project rule {r['id']} (POSTMORTEMS.md): {r['rule']}]")
        return HookResult(action="note", note="\n".join(notes), hook="scars.first_touch") if notes else None

    def context_pack(self, ev: HookEvent) -> None:
        """context.pack (session_start): build and freeze the pack once per session."""
        s = self.app.store.get(ev.session_id) or ev.ctx.session
        if isinstance((s.get("settings") or {}).get("context_pack"), dict):
            return None  # frozen
        pack = build_context_pack(self.app, s)
        if pack:
            self.app.store.update(ev.session_id, settings={"context_pack": pack})
        return None

    def refresh_context_pack(self, sid: str) -> dict | None:
        """Rebuild the pack (Refresh project context). It changes the system prompt from the next
        model call on, so the prompt cache starts over once."""
        s = self.app.store.get(sid)
        if not s:
            raise KeyError(sid)
        pack = build_context_pack(self.app, s)
        self.app.store.update(sid, settings={"context_pack": pack or {}})
        return pack

    async def aclose(self) -> None:
        for t in list(self._tasks):
            t.cancel()


def _session_skills(session: dict | None) -> set[str]:
    st = (session or {}).get("settings") or {}
    out: set[str] = set()
    for k in ("skills", "loaded_skills", "pinned_skills"):
        v = st.get(k) or []
        out |= {str(x) for x in v} if isinstance(v, list) else set()
    return out


def _event_label(event: str) -> str:
    return {"pre_complete": "before the agent finishes a turn", "pre_tool": "before a tool runs",
            "post_tool": "after a tool ran", "post_merge": "after a worktree merge", "pre_merge": "before a merge",
            "session_start": "at session start", "turn_end": "at turn end", "pre_compact": "before compaction"}.get(event, event)


def _needs_md(needs: dict, *, consent: bool = False) -> list[str]:
    md = []
    head = "It will run, without asking each time" if consent else "If you allow its commands, it runs"
    if needs.get("tools"):
        md.append(f"**{head}, these MCP tools:** " + ", ".join(f"`{t.replace('__', '.', 1)}`" for t in needs["tools"]))
    cmds = needs.get("commands", []) + needs.get("templates", [])
    if cmds:
        md.append(f"**{'Commands' if consent else head + ' these commands'}:**\n" + _fence("\n".join(cmds), "sh"))
    if needs.get("unity_ops"):
        md.append(f"**{head}, these Unity CLI checks** (official `unity` CLI, when the Unity backend uses it): "
                  + ", ".join(f"`{o}`" for o in needs["unity_ops"]))
    if needs.get("scripts"):
        md.append("**Built-in scripts (read-only checks):** " + "; ".join(f"`{s}`" for s in needs["scripts"]))
    return md


_SIG_SUBS = [
    (re.compile(r"<untrusted-[0-9a-f]+[^>]*>|</untrusted-[0-9a-f]+>"), ""),
    (re.compile(r"(['\"`]).*?\1"), "…"),
    (re.compile(r"(?:[A-Za-z]:)?[\w.~-]*(?:/[\w.@~-]+)+"), "<path>"),
    (re.compile(r"\d+"), "#"),
    (re.compile(r"\s+"), " "),
]


def error_signature(text: str) -> str:
    """A tool error's first meaningful line, normalized (quotes, paths, numbers), so the same
    failure with other arguments counts as the same error."""
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s or s.startswith("<untrusted-") or re.fullmatch(r"exit code -?\d+", s):
            continue
        for rx, rep in _SIG_SUBS:
            s = rx.sub(rep, s)
        s = s.strip().lower()
        if s:
            return s[:160]
    return ""


# ============================================================ context pack


def build_context_pack(app: "AppState", session: dict) -> dict | None:
    """The project context pack (≤ CONTEXT_PACK_MAX chars): PROJECT.md current milestone, TASTE.md
    (three words, top 5 heuristics, anti-patterns), the 10 newest POSTMORTEMS rules, the active
    campaign. None when the folder is neither a Unity project nor has a PROJECT.md, or nothing
    was found. {text, sources, sha, built_at}."""
    project = project_of(session)
    if not project or not (is_unity_project(project) or (project / "PROJECT.md").is_file()):
        return None
    parts: list[str] = []
    sources: list[str] = []
    if md := _read(project / "PROJECT.md"):
        sec = _section(md, re.compile(r"current milestone", re.I))
        if sec:
            parts.append("## Current milestone (PROJECT.md)\n" + _cut(sec, 900))
            sources.append("PROJECT.md")
    if md := _read(project / "TASTE.md"):
        words = _section(md, re.compile(r"three words(?!.*test)", re.I))
        heur = _list_items(_section(md, re.compile(r"heuristic", re.I)), 5)
        anti = _list_items(_section(md, re.compile(r"anti-?patterns?", re.I)), 6)
        t = []
        if words:
            t.append(_cut(words, 300))
        if heur:
            t.append("Heuristics (higher wins): " + "; ".join(f"{i}. {h}" for i, h in enumerate(heur, 1)))
        if anti:
            t.append("Anti-patterns: " + "; ".join(anti))
        if t:
            parts.append("## Taste (TASTE.md)\n" + _cut("\n".join(t), 800))
            sources.append("TASTE.md")
    if md := _read(project / "POSTMORTEMS.md"):
        pms = sorted(parse_postmortems(md), key=lambda r: -r["num"])[:10]
        if pms:
            parts.append("## Project rules (POSTMORTEMS.md, newest first)\n" + "\n".join(
                "- " + _cut(f"{r['id']} {r['title']}" + (f": {r['rule']}" if r["rule"] else ""), 170) for r in pms))
            sources.append("POSTMORTEMS.md")
    if camp := _campaign_pointer(app, session, project):
        parts.append("## Active campaign\n" + _cut(camp, 400))
        sources.append("campaign")
    if not parts:
        return None
    head = ("Project context (frozen at session start; files may have changed since: read them before relying "
            "on details):")
    text = _cut(head + "\n\n" + "\n\n".join(parts), CONTEXT_PACK_MAX)
    return {"text": text, "sources": sources, "sha": sha256(text)[:16], "built_at": time.time()}


def _campaign_pointer(app: "AppState", session: dict, project: Path) -> str:
    cid = (session.get("settings") or {}).get("campaign_id")
    try:
        if cid:
            row = app.db.one("SELECT * FROM campaigns WHERE id=?", [cid])
        else:
            row = app.db.one("SELECT * FROM campaigns WHERE folder=? AND status IN ('active','running','paused') "
                             "ORDER BY updated_at DESC LIMIT 1", [str(project)])
    except Exception:  # noqa: BLE001 — the campaigns table belongs to another feature
        return ""
    if not row:
        return ""
    out = f"{row.get('title') or row.get('slug')} ({row.get('kind')}, {row.get('status')})"
    try:
        phases = json.loads(row.get("phases") or "[]")
        i = int(row.get("phase") or 0)
        if 0 <= i < len(phases):
            out += f", phase {i + 1}/{len(phases)}: {phases[i].get('name', '')}"
    except (ValueError, TypeError, AttributeError):
        pass
    if row.get("file"):
        f = Path(row["file"]) if Path(row["file"]).is_absolute() else project / row["file"]
        if (md := _read(f)) and (m := re.search(r"Next action:\s*(.+)", md)):
            out += f"\nNext action: {m.group(1).strip()}"
        out += f"\nCampaign file: {row['file']}"
    return out


# ============================================================ built-ins


def _bridge_needs(op: str) -> Callable[["HooksEngine", Path, HookEntry], dict]:
    def needs(eng: HooksEngine, project: Path, e: HookEntry) -> dict:
        o = e.options or {}
        spec = {"op": "compile"} if op == "compile" else {"op": "test", "platform": str(o.get("platform") or "editmode"),
                                                         "category": o.get("category"), "filter": o.get("filter")}
        c = get_bridge(eng.app).consent_for(project, [spec])
        return {"mcp": c["mcp"], "run_command": c["run_command"], "unity_cli": c.get("unity_cli", set())}
    return needs


def _bridge_result(eng: HooksEngine, e: HookEntry, ev: HookEvent, r: BridgeResult, level: str, fix: str) -> HookResult | None:
    ev_ = [{**r.evidence, "mode": r.mode, "summary": r.summary}]
    if r.status in ("skipped", "error"):
        return HookResult(gate=e.gate_id(), status=r.status, reason=r.summary, evidence=ev_, level=level, hook=e.id)
    ok = r.status == "pass"
    summary = r.summary if ok else f"{r.summary} after this turn's changes ({r.mode}). {fix}"
    res = eng.outcome(e, ev, ok, summary, r.report, evidence=ev_, source=f"unity:{e.gate_id()}")
    if res:
        res.level = level
    return res


async def _b_unity_compile(eng: HooksEngine, e: HookEntry, ev: HookEvent, ac: ActionContext) -> HookResult | None:
    r = await get_bridge(eng.app).compile(ac.session, consent=ac.consent)
    return _bridge_result(eng, e, ev, r, e.level or "L1",
                          "Fix the root causes in the order listed (compile-fix-loop), then finish.")


async def _b_unity_tests(eng: HooksEngine, e: HookEntry, ev: HookEvent, ac: ActionContext) -> HookResult | None:
    if any(r.gate == "unity.compile" and r.action == "block" for r in ac.prior):
        return None  # tests can't run while it doesn't compile; that gate already asked for a fix
    o = e.options or {}
    r = await get_bridge(eng.app).run_tests(ac.session, str(o.get("platform") or "editmode"),
                                            category=o.get("category"), test_filter=o.get("filter"),
                                            consent=ac.consent)
    return _bridge_result(eng, e, ev, r, e.level or "L2",
                          "Fix the code under test (not the test), then finish.")


def antipatterns_script() -> Path:
    return skill_script("perf-pass", "scripts/unity_antipatterns.py")


async def _b_unity_antipatterns(eng: HooksEngine, e: HookEntry, ev: HookEvent, ac: ActionContext) -> HookResult | None:
    """perf-pass's anti-pattern audit with a baseline ratchet: only new findings count. Advisory
    unless options.blocking = true. Without the script (an older Unity pack) it does nothing,
    unless it was asked for by name (run_gate), which reports it as skipped."""
    gid = e.gate_id()
    script = antipatterns_script()
    if any(r.gate == "unity.compile" and r.action == "block" for r in ac.prior):
        return None
    if not script.is_file():
        return HookResult(gate=gid, status="skipped", hook=e.id, reason="perf-pass/scripts/unity_antipatterns.py "
                          "isn't installed") if ac.force else None
    py = shutil.which("python3")
    if not py:
        return HookResult(gate=gid, status="skipped", hook=e.id, reason="python3 not found")
    o = e.options or {}
    baseline = str(o.get("baseline") or ".gamedevworkstation/antipatterns-baseline.json")
    argv = [py, str(script), "--project", str(ac.project)]
    files = [c for c in ac.changed if c.endswith(".cs")]
    if files:
        argv += ["--changed", *files]
    argv += ["--baseline", str(ac.project / baseline)]
    try:
        p = await asyncio.create_subprocess_exec(*argv, cwd=str(ac.project), stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL)
    except OSError as ex:
        return HookResult(gate=gid, status="skipped", hook=e.id, reason=f"couldn't start the audit ({ex})")
    try:
        raw, _ = await asyncio.wait_for(p.communicate(), max(int(eng._cfg_int("gate_timeout_s", 180)), 10))
    except asyncio.TimeoutError:
        try:
            p.kill()
        except ProcessLookupError:
            pass
        return HookResult(gate=gid, status="skipped", hook=e.id, reason="the anti-pattern audit timed out")
    out = raw.decode(errors="replace")
    res = re.findall(r"^RESULT: (OK|FAIL)\b ?(.*)$", out, re.M)
    if not res:
        return HookResult(gate=gid, status="error", hook=e.id, reason=f"no RESULT line (exit {p.returncode})")
    ok = res[-1][0] == "OK"
    summary = f"RESULT: {res[-1][0]} {res[-1][1]}".strip()
    if not ok:
        summary += (". New anti-patterns in changed files: fix them, or suppress one with "
                    "`// harness:allow RULE reason` when it's intended.")
    ent = dataclasses.replace(e, on_fail="block" if o.get("blocking") else "note")
    return eng.outcome(ent, ev, ok, summary, out[-6000:], evidence=[{"result": summary, "files": files[:50]}],
                       source="unity_antipatterns")


def _b_backlog_lint(eng: HooksEngine, e: HookEntry, ev: HookEvent, ac: ActionContext) -> HookResult | None:
    """gdd-to-backlog's backlog_lint.py, imported in-process, on the BACKLOG.md just written."""
    path = None
    for p in ev.path_args():
        r = rel_path(p, ev.ctx.folder, ac.project)
        if r.rsplit("/", 1)[-1] == "BACKLOG.md":
            path = (ev.ctx.folder or ac.project) / r
            break
    path = path or ac.project / "BACKLOG.md"
    text = _read(path)
    if text is None:
        return None
    mod = load_script(skill_script("gdd-to-backlog", "scripts/backlog_lint.py"))
    if mod is None:
        return HookResult(gate=e.gate_id(), status="skipped", hook=e.id, reason="backlog_lint.py not found") \
            if ev.name == "pre_complete" else None
    lint = mod.Linter(str(path))
    lint.parse(text)
    lint.check()
    errors = sorted(lint.errors)
    if not errors:
        return eng.outcome(e, ev, True, "BACKLOG.md lints clean", "")
    lines = "\n".join(f"ERROR BACKLOG.md:{ln}: {msg}" for ln, msg in errors[:5])
    more = f"\n… {len(errors) - 5} more" if len(errors) > 5 else ""
    summary = (f"BACKLOG.md has {len(errors)} lint error{'s' if len(errors) != 1 else ''} (gdd-to-backlog format); "
               "fix them")
    return eng.outcome(e, ev, False, summary, lines + more, source="backlog_lint")


def _register_builtins(eng: HooksEngine) -> None:
    eng.add_builtin("unity.compile", _b_unity_compile, ("pre_complete", "post_merge"), needs=_bridge_needs("compile"),
                    describe="Unity compile (per the Unity backend: MCP or the Unity CLI live Editor when it's "
                             "open, else a batch compile: Unity CLI or unity.sh)")
    eng.add_builtin("unity.tests", _b_unity_tests, ("pre_complete",), needs=_bridge_needs("tests"),
                    describe="Unity EditMode/PlayMode tests (MCP run_tests or Unity CLI run_tests when the Editor is "
                             "open, else `unity test` / unity.sh test)")
    eng.add_builtin("unity.antipatterns", _b_unity_antipatterns, ("pre_complete",),
                    needs=lambda eng_, project, e: {"scripts": ["python3 perf-pass/scripts/unity_antipatterns.py "
                                                                "--changed … --baseline .gamedevworkstation/antipatterns-baseline.json"]},
                    describe="perf-pass anti-pattern audit, new findings only")
    eng.add_builtin("backlog.lint", _b_backlog_lint, ("post_tool", "pre_complete"), plan_ok=True,
                    describe="gdd-to-backlog BACKLOG.md lint")


# ============================================================== wiring

ALWAYS_ON = [("post_tool", "tool_failure_breaker", 40), ("post_tool", "scars.first_touch", 60),
             ("session_start", "context.pack", 50), ("model_call", "hooks.cards", 50)]


def get_engine(app: "AppState") -> HooksEngine | None:
    return app.extensions.get("hooks_engine")  # type: ignore[return-value]


def install(S: "AppState") -> HooksEngine:
    """Create the engine, register its bus handlers and the run_gate tool (no routes; tests use
    this on a bare AppState). Idempotent."""
    if eng := get_engine(S):
        return eng
    eng = HooksEngine(S)
    S.extensions["hooks_engine"] = eng
    get_bridge(S)
    hb = S.hooks
    hb.register("post_tool", "tool_failure_breaker", eng.breaker, order=40)
    hb.register("post_tool", "scars.first_touch", eng.scars, order=60)
    hb.register("session_start", "context.pack", eng.context_pack, order=50)
    hb.register("model_call", "hooks.cards", eng.check_cards, order=50)
    for event in HOOK_EVENTS:
        hb.register(event, "hooks.toml", eng.dispatch, order=100)

    @S.tools.add("run_gate", "Run one of this project's gates now (e.g. unity.compile, unity.tests) instead of "
                 "waiting for the end of the turn, e.g. before declaring a phase done. Returns pass / fail / skipped "
                 "with the evidence. The gates also run by themselves when you finish.",
                 obj({"name": {"type": "string", "description": "Gate id, e.g. unity.compile"}}, ["name"]),
                 main_only=True, when=eng.gates_enabled)
    async def run_gate(ctx: ToolContext, a: dict) -> ToolOutput:
        name = str(a.get("name") or "").strip()
        try:
            r = await eng.run_gate(ctx.session, name)
        except KeyError:
            names = eng.gate_names(ctx.session)
            return ToolOutput(f"No gate {name!r} here. Gates: {', '.join(names) or 'none'}.", is_error=True)
        except ValueError as e:
            return ToolOutput(str(e), is_error=True)
        status = r.status or ("fail" if r.action == "block" else "pass")
        text = f"Gate {r.id}: {status}. {r.reason}".strip()
        if r.untrusted:
            text += "\n\n" + wrap_untrusted(r.untrusted, f"gate:{r.id}")
        elif r.note and status == "fail":
            text += "\n\n" + r.note
        return ToolOutput(text, is_error=status == "fail")

    return eng


def register(app_: "FastAPI", api: "APIRouter", S: "AppState") -> None:
    from fastapi import Body, HTTPException

    eng = install(S)

    def _session(sid: str | None) -> dict:
        s = S.store.get(sid) if sid else None
        if not s:
            raise HTTPException(404, "Session not found")
        return s

    def _project(body: dict) -> tuple[Path, dict | None]:
        s = S.store.get(body["session_id"]) if body.get("session_id") else None
        p = project_of(s) if s else None
        if not p and body.get("project"):
            try:
                p = Path(str(body["project"])).expanduser().resolve()
            except OSError:
                p = None
            if p and not p.is_dir():
                p = None
        if not p:
            raise HTTPException(400, "A session with a folder (session_id) or an existing project folder is needed")
        return p, s

    @api.get("/hooks")
    async def hooks_state(session_id: str | None = None, project: str | None = None) -> dict:
        p, s = _project({"session_id": session_id, "project": project})
        srcs = await asyncio.to_thread(eng.sources, s, project=p)
        return {"project": str(p), "enabled": S.hooks.enabled(), "unity_project": is_unity_project(p),
                "sources": [x.to_dict(eng.needs(p, x.entries)) for x in srcs],
                "gates": list(dict.fromkeys(e.gate_id() for x in srcs if x.active for e in x.entries
                                            if e.event == "pre_complete")),
                "builtins": [{"name": n, "event": ev_} for ev_, n, _ in ALWAYS_ON]
                + [{"name": b.name, "events": list(b.events), "describe": b.describe} for b in eng.builtins.values()]}

    @api.get("/hooks/unity")
    async def unity_state(session_id: str) -> dict:  # alias of GET /api/unity/state
        return await get_bridge(S).full_state(_session(session_id))

    @api.post("/hooks/preset")
    async def preset(body: dict = Body(...)) -> dict:
        p, s = _project(body)
        name = str(body.get("preset") or PRESET)
        if not body.get("enabled", True):
            eng.disable_preset(p, name)
            return {"status": "disabled"}
        try:
            aid = eng.request_preset(s["id"] if s else None, p, name)
        except KeyError:
            raise HTTPException(404, f"No hook preset {name}") from None
        return {"status": "pending", "approval_id": aid}

    @api.post("/hooks/trust")
    async def trust(body: dict = Body(...)) -> dict:
        p, s = _project(body)
        srcs = [x for x in eng.sources(s, project=p) if x.kind != "preset"]
        want = body.get("path")
        srcs = [x for x in srcs if not want or want in (x.key_path, str(x.path), x.name)]
        if not srcs:
            raise HTTPException(404, "No such hook file")
        if body.get("trusted") is False:
            return {"removed": sum(eng.untrust(x.key_project, x.key_path) for x in srcs)}
        ids = [aid for x in srcs if x.state != "trusted" and (aid := eng.request_trust(s["id"] if s else None, x, p))]
        return {"status": "pending" if ids else "unchanged", "approval_ids": ids}

    @api.post("/hooks/run")
    async def run(body: dict = Body(...)) -> dict:
        s = _session(body.get("session_id"))
        gate = str(body.get("gate") or "")

        async def go() -> HookResult:
            return await eng.run_gate(s, gate)

        if body.get("wait"):
            try:
                r = await go()
            except KeyError:
                raise HTTPException(404, f"No gate {gate}") from None
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            return {"gate": r.id, "status": r.status or ("fail" if r.action == "block" else "pass"),
                    "summary": r.reason, "evidence": r.evidence}
        if gate not in eng.gate_names(s) and gate not in eng.builtins:
            raise HTTPException(404, f"No gate {gate}")
        t = asyncio.create_task(go())  # the result arrives as a gate.result event
        eng._tasks.add(t)
        t.add_done_callback(eng._tasks.discard)
        return {"status": "started", "gate": gate}

    @api.post("/hooks/context_pack")
    async def context_pack(body: dict = Body(...)) -> dict:
        s = _session(body.get("session_id"))
        return {"context_pack": eng.refresh_context_pack(s["id"])}
