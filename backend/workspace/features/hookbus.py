"""Hook bus: lifecycle events the agent loop fires, and the in-process hooks that answer them.

This module is the stable contract other features build on (hooks engine, quality ladder,
campaigns, fleet). It holds no policy of its own: with no hook registered every `fire()` returns
[] without awaiting anything, so the loop behaves exactly as it did before hooks existed.

Events (`EVENTS`), where they fire, and what the caller does with the results:

| event          | fired from                                                 | results used                      |
|----------------|------------------------------------------------------------|-----------------------------------|
| session_start  | agent/loop.py, before the first model call of a turn, when | none (observers); the session is  |
|                | the session has no assistant reply yet (may fire again if  | re-read afterwards, so a hook may |
|                | that turn stored no reply; handlers must be idempotent)    | freeze settings.context_pack      |
| model_call     | agent/loop.py, before every model call (internal)          | none                              |
| pre_tool       | AgentRunner._run_tool / SubagentManager._tool, before the  | first `block` denies the call     |
|                | tool runs (only for tools the caller may use at all)       | (stop_on_block)                   |
| post_tool      | same places, after the tool ran (output finalized)         | `note` / `reason` text appended   |
|                |                                                            | to the tool result text           |
| pre_complete   | agent/loop.py, when the model ends its turn without tool   | `block` = failing gate: retried   |
|                | calls (not on max_tokens / context_window stops, never in  | by the model, then exhausted.     |
|                | Plan only mode)                                            | Every result is a gate_runs row   |
| pre_compact    | agent/context.compact_messages (auto-compact and the       | none                              |
|                | Compact button), before summarizing                        |                                   |
| pre_merge      | the merge_worktree tool, after approval, before the merge  | first `block` holds the merge     |
| post_merge     | the merge_worktree tool, after a successful merge          | notes/reasons appended to output  |
| turn_end       | AgentRunner._run `finally` (every harness), after          | none                              |
|                | agent.idle; extra = {ok, error_kind, error}                |                                   |

Notes on semantics:
- Handlers run in (order, registration) order. A handler returns None (nothing to say), a
  HookResult, or a list of them; it may be sync or async.
- `fail="closed"`: a handler that raises (or returns something else) yields a `block` result, so
  a crashing guard denies. `fail="open"` (default): it yields an `allow` result with
  status="error" and the failure is published as a `hooks.error` event (loudly, never silently).
- `[hooks] enabled = false` in config turns every hook off (fire() returns []).
- `turn_end` handlers run inside the finishing runner task: `app.runner.is_running(sid)` is still
  True there. To start another turn, schedule it (e.g. a task that awaits
  `app.runner.running.get(sid)` first, then calls `app.runner.start(sid)`).
- To end the current turn from post_tool (e.g. a tool-failure breaker), call
  `ev.turn.request_stop(text)`: the loop stores the tool results, adds the notice and returns.

Events published here (on app.bus): `gate.result` (record_gate), `hooks.error` (a failing hook).
The loop publishes `gate.exhausted`.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, Union

from ..agent.tools import ToolContext, ToolOutput
from ..core.types import new_id

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)

EVENTS = ("session_start", "model_call", "pre_tool", "post_tool", "pre_complete", "pre_compact",
          "pre_merge", "post_merge", "turn_end")
DEFAULT_GATE_MAX_RETRIES = 2

# Tool argument keys that name the path a tool works on (hooks.toml `paths` matching uses these).
PATH_ARG_KEYS = ("path", "uri", "file", "script_path", "target")

# changed_files(): folders never scanned. Top level only (Unity's caches and per-user state; a
# folder of the same name deeper down, e.g. Assets/Game/Logs, is real content) ...
SKIP_TOP_DIRS = frozenset({"Library", "Temp", "Logs", "obj", "UserSettings"})
# ... and at any depth.
SKIP_ANY_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv"})
SKIP_REL_DIRS = frozenset({".workspace/tmp"})
MAX_SCAN_ENTRIES = 200_000  # a walk stops here (logged), so a huge folder can't stall a turn


# ------------------------------------------------------------------------- data


@dataclass
class TurnState:
    """One main-agent turn (from the user's message until the loop returns), shared by every hook
    that fires during it, including those fired for the session's subagents meanwhile.

    - started_at: the turn start (app.turn_started[sid]); changed files are those newer than this.
    - retries: pre_complete fix requests sent to the model so far, per gate id.
    - calls: model calls made so far in this turn.
    - data: scratch space for hooks, keyed by the hook's own name (e.g. a BACKLOG.md snapshot
      taken at turn start, tool-failure counts).
    - stop: set by request_stop(); the loop ends the turn after the current tool round."""

    session_id: str
    started_at: float
    folder: Path | None = None
    retries: dict[str, int] = field(default_factory=dict)
    calls: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    stop: dict[str, str] | None = None

    def changed_files(self, globs: list[str] | None = None) -> list[str]:
        """Files in the session folder modified since the turn started (relative POSIX paths,
        sorted), optionally filtered by `globs` (see glob_match). A filesystem walk: call it via
        asyncio.to_thread from async code when the folder may be large."""
        return changed_files(self.folder, self.started_at, globs) if self.folder else []

    def request_stop(self, text: str, kind: str = "hook_stop") -> None:
        """End the turn after the current tool round, with `text` as a notice (meta.notice=kind)
        under the chat. The model doesn't see the notice."""
        self.stop = {"kind": kind, "text": text}


@dataclass
class HookEvent:
    """What a hook gets.

    - name: one of EVENTS.
    - ctx: the ToolContext of whoever triggered the event: role "main" (main loop, merges,
      compaction, turn end), "subagent" (a subagent's tool call) or "hook" (an action a hook runs
      under hook_context()). ctx.session is the session dict (settings, folder, mode).
    - tool / args: pre_tool and post_tool (args as the model sent them).
    - output: post_tool, the finalized ToolOutput (already capped and untrusted-wrapped).
    - turn: the session's current TurnState (None when no main turn is running, e.g. a background
      subagent finishing after its parent's turn ended).
    - unit: the subagent id for subagent tool calls and pre/post_merge.
    - extra: event-specific fields:
        model_call:   {"call": n}  (1-based, within the turn)
        pre_compact:  {"auto": bool, "cut": int, "messages": int}
        pre_merge:    {"branch": str, "worktree": str, "name": str}
        post_merge:   {"branch": str, "worktree": str, "name": str, "stat": str, "changes": bool}
        turn_end:     {"ok": bool, "error_kind": None | "cancelled" | "budget" | "context_full"
                        | "no_key" | "error", "error": str}"""

    name: str
    ctx: ToolContext
    tool: str | None = None
    args: dict | None = None
    output: ToolOutput | None = None
    turn: TurnState | None = None
    unit: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def session_id(self) -> str:
        return self.ctx.session_id

    def path_args(self) -> list[str]:
        """The path-like arguments of a tool call (keys in PATH_ARG_KEYS), for path matching."""
        return [str(v) for k in PATH_ARG_KEYS if isinstance(v := (self.args or {}).get(k), str) and v]


@dataclass
class HookResult:
    """What a hook answers.

    - action: "allow" (nothing to do), "block" (pre_tool / pre_merge: deny; pre_complete: the
      gate failed), or "note" (post_tool / post_merge: `note` is appended to the result).
    - reason: for block, why and how to fix it (the model reads it).
    - note: text appended to the tool result (post_tool, post_merge).
    - gate: gate id (e.g. "unity.compile") shown in the UI and stored in gate_runs. Defaults to
      the hook's registered name where one is needed.
    - evidence: observed facts the hook found (stored in gate_runs.detail).
    - status: pass | fail | skipped | error. pre_complete records every result: a block is
      "fail" unless status says otherwise, anything else "pass" unless status says otherwise.
    - max_retries: per-gate override of [hooks] gate_max_retries (pre_complete).
    - untrusted: raw outside output a block quotes (Unity console errors, command output); the
      loop wraps it with wrap_untrusted before the model sees it.
    - level / subjects: quality-ladder level ("L1".."L4") and story/AC ids, stored in gate_runs.
    - hook: filled in by HookBus.fire with the registered handler name."""

    action: Literal["allow", "block", "note"] = "allow"
    reason: str = ""
    note: str = ""
    gate: str | None = None
    evidence: list[dict] = field(default_factory=list)
    status: Literal["pass", "fail", "skipped", "error"] | None = None
    max_retries: int | None = None
    untrusted: str = ""
    level: str | None = None
    subjects: list[str] = field(default_factory=list)
    hook: str = ""

    @property
    def id(self) -> str:
        """The gate id, else the hook name."""
        return self.gate or self.hook

    def block_text(self) -> str:
        """How a pre_tool / pre_merge block reads to the model."""
        return f"Blocked by {self.id or 'a hook'}: {self.reason or 'no reason given'}"


HookFn = Callable[[HookEvent], Union[None, HookResult, list, Awaitable[Any]]]


@dataclass
class _Handler:
    event: str
    name: str
    fn: HookFn
    order: int
    fail: str
    when: Callable[[HookEvent], bool] | None
    seq: int


# ------------------------------------------------------------------------- bus


class HookBus:
    """app.hooks. In-process registry of hook handlers per event, plus the per-turn state."""

    def __init__(self, app: "AppState"):
        self.app = app
        self._handlers: dict[str, list[_Handler]] = {}
        self._seq = 0
        self.turns: dict[str, TurnState] = {}  # session id → its running main turn

    # ------------------------------------------------------------- registry

    def register(self, event: str, name: str, fn: HookFn, *, order: int = 100,
                 fail: Literal["open", "closed"] = "open",
                 when: Callable[[HookEvent], bool] | None = None) -> None:
        """Add `fn` for `event` under `name` (unique per event: registering the same name again
        replaces it, so reloading a hook set is idempotent). Lower `order` runs first; equal
        orders run in registration order. `when(ev)` → False skips the handler cheaply (a
        raising `when` counts as a handler failure)."""
        if event not in EVENTS:
            raise ValueError(f"Unknown hook event {event!r}; one of: {', '.join(EVENTS)}")
        if fail not in ("open", "closed"):
            raise ValueError("fail must be 'open' or 'closed'")
        self.unregister(event, name)
        self._seq += 1
        self._handlers.setdefault(event, []).append(_Handler(event, name, fn, int(order), fail, when, self._seq))
        self._handlers[event].sort(key=lambda h: (h.order, h.seq))

    def unregister(self, event: str | None, name: str) -> int:
        """Remove handler `name` from `event` (every event when None). Returns how many went."""
        n = 0
        for ev in [event] if event else list(self._handlers):
            hs = self._handlers.get(ev) or []
            keep = [h for h in hs if h.name != name]
            n += len(hs) - len(keep)
            if keep:
                self._handlers[ev] = keep
            else:
                self._handlers.pop(ev, None)
        return n

    def handlers(self, event: str) -> list[str]:
        """Names of the handlers for `event`, in the order they run."""
        return [h.name for h in self._handlers.get(event, [])]

    def enabled(self) -> bool:
        """The [hooks] enabled master switch (default on)."""
        return bool(((getattr(self.app.config, "hooks", None) or {}).get("enabled", True)))

    def has(self, event: str) -> bool:
        """True when firing `event` could do anything. Callers check it before doing extra work
        (reading the session, building payloads), which keeps the zero-hook path identical."""
        return bool(self._handlers.get(event)) and self.enabled()

    def max_retries(self, result: HookResult | None = None) -> int:
        """pre_complete fix attempts per gate per turn: the result's own max_retries, else
        [hooks] gate_max_retries (default 2)."""
        if result is not None and result.max_retries is not None:
            return max(int(result.max_retries), 0)
        v = (getattr(self.app.config, "hooks", None) or {}).get("gate_max_retries", DEFAULT_GATE_MAX_RETRIES)
        try:
            return max(int(v), 0)
        except (TypeError, ValueError):
            return DEFAULT_GATE_MAX_RETRIES

    # ----------------------------------------------------------------- fire

    async def fire(self, ev: HookEvent, *, stop_on_block: bool = False) -> list[HookResult]:
        """Run the handlers for ev.name and collect their results (None answers are dropped).
        stop_on_block: stop at the first block (pre_tool, pre_merge: later guards needn't run).
        With nothing registered (or hooks disabled) this returns [] without awaiting anything."""
        hs = self._handlers.get(ev.name)
        if not hs or not self.enabled():
            return []
        out: list[HookResult] = []
        for h in list(hs):
            try:
                if h.when is not None and not h.when(ev):
                    continue
                r = h.fn(ev)
                if inspect.isawaitable(r):
                    r = await r
                got = [] if r is None else list(r) if isinstance(r, (list, tuple)) else [r]
                if not all(isinstance(x, HookResult) for x in got):
                    raise TypeError(f"returned {type(r).__name__}, not HookResult")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — a hook must never take the loop down
                got = [self._failed(ev, h, e)]
            for x in got:
                if not x.hook:
                    x.hook = h.name
                out.append(x)
                if stop_on_block and x.action == "block":
                    return out
        return out

    def _failed(self, ev: HookEvent, h: _Handler, e: Exception) -> HookResult:
        err = f"{type(e).__name__}: {e}"[:500]
        log.warning("hook %s (%s) failed: %s", h.name, ev.name, err, exc_info=True)
        try:
            self.app.bus.publish("hooks.error", {"event": ev.name, "hook": h.name, "error": err, "fail": h.fail,
                                                 "tool": ev.tool}, ev.ctx.session_id)
        except Exception:  # noqa: BLE001
            pass
        if h.fail == "closed":
            return HookResult(action="block", status="error", hook=h.name,
                              reason=f"the check {h.name} failed ({err}), so this was blocked to be safe.")
        return HookResult(action="allow", status="error", hook=h.name, reason=err)

    # ---------------------------------------------------------------- turns

    def begin_turn(self, session_id: str, started_at: float | None = None, folder: Path | None = None) -> TurnState:
        """A fresh TurnState for the session's new main turn (the loop calls this)."""
        t = TurnState(session_id=session_id, started_at=started_at or time.time(), folder=folder)
        self.turns[session_id] = t
        return t

    def turn(self, session_id: str) -> TurnState | None:
        """The session's running main turn, if any."""
        return self.turns.get(session_id)

    def end_turn(self, session_id: str, turn: TurnState | None = None) -> None:
        if turn is None or self.turns.get(session_id) is turn:
            self.turns.pop(session_id, None)

    # ---------------------------------------------------------------- gates

    def record_gate(self, session_id: str | None, result: HookResult, *, attempt: int = 0,
                    campaign_id: str | None = None, started_at: float | None = None) -> str:
        """Store one gate evaluation in gate_runs and publish `gate.result`
        {id, gate, status, attempt, level, subjects, summary, hook}. Returns the row id.
        status: result.status, else "fail" for a block and "pass" otherwise."""
        status = result.status or ("fail" if result.action == "block" else "pass")
        rid = new_id("gate_")
        summary = (result.reason or result.note or "")[:1000]
        now = time.time()
        self.app.db.insert("gate_runs", {
            "id": rid, "session_id": session_id, "campaign_id": campaign_id, "gate": result.id or "hook",
            "level": result.level, "status": status, "attempt": int(attempt),
            "subjects": json.dumps(list(result.subjects)), "summary": summary,
            "detail": json.dumps({"hook": result.hook, "action": result.action, "evidence": result.evidence,
                                  "note": result.note[:2000]}, default=str),
            "started_at": started_at or now, "ended_at": now})
        self.app.bus.publish("gate.result", {"id": rid, "gate": result.id or "hook", "status": status,
                                             "attempt": int(attempt), "level": result.level,
                                             "subjects": list(result.subjects), "summary": summary,
                                             "hook": result.hook}, session_id)
        return rid

    # ------------------------------------------------------------ utilities

    def changed_files(self, folder: Path, since: float, globs: list[str] | None = None) -> list[str]:
        """See the module function changed_files()."""
        return changed_files(folder, since, globs)


def hook_context(app: "AppState", session: dict, *, run_id: str | None = None,
                 consent: dict[str, set[str]] | None = None) -> ToolContext:
    """A ToolContext for actions a hook performs itself (role "hook"). Its file tools reach only
    the session folder. `consent` lists what the user already consented to for this hook set, by
    approval kind, as exact subjects: {"run_command": {"<exact command line>"}, "mcp":
    {"<server>__<tool>"}, "edit": {...}}. Those pass without a card; anything else asks as usual
    (or follows the allowlist). Plan only mode still refuses edits and commands first."""
    return ToolContext(app=app, session=session, run_id=run_id or f"hook:{session['id']}", role="hook",
                       consent={k: set(v) for k, v in (consent or {}).items()})


# ------------------------------------------------------- shared call sites


def result_notes(results: list[HookResult]) -> list[str]:
    """Text to append to a tool or merge result: each result's note, or a block's reason (after
    the fact a block can only be reported, not prevented)."""
    return [t for r in results if (t := (r.note or (r.reason if r.action == "block" else "")).strip())]


async def run_pre_tool(app: "AppState", ctx: ToolContext, name: str, args: dict, *,
                       unit: str | None = None) -> HookResult | None:
    """Fire pre_tool for one tool call (main loop and subagents). Returns the first block, or None
    to let the call run. A no-op returning None when no pre_tool hook is registered."""
    hooks: HookBus | None = getattr(app, "hooks", None)
    if hooks is None or not hooks.has("pre_tool"):
        return None
    res = await hooks.fire(HookEvent("pre_tool", ctx, tool=name, args=args, turn=hooks.turn(ctx.session_id),
                                     unit=unit), stop_on_block=True)
    return next((r for r in res if r.action == "block"), None)


async def run_post_tool(app: "AppState", ctx: ToolContext, name: str, args: dict, out: ToolOutput, *,
                        unit: str | None = None) -> ToolOutput:
    """Fire post_tool after a tool ran; notes are appended to the (already finalized) output text,
    outside any untrusted block. Returns `out` itself when there's nothing to add."""
    hooks: HookBus | None = getattr(app, "hooks", None)
    if hooks is None or not hooks.has("post_tool"):
        return out
    res = await hooks.fire(HookEvent("post_tool", ctx, tool=name, args=args, output=out,
                                     turn=hooks.turn(ctx.session_id), unit=unit))
    if not (notes := result_notes(res)):
        return out
    return dataclasses.replace(out, text=(out.text or "(no output)") + "\n\n" + "\n".join(notes))


# ------------------------------------------------------------- changed files


@lru_cache(maxsize=512)
def _glob_re(pattern: str) -> re.Pattern[str]:
    out, i, n = [], 0, len(pattern)
    while i < n:
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == n:
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out) + r"\Z")


def glob_match(path: str, pattern: str) -> bool:
    """Match a relative POSIX path against a gitignore-like glob (case-sensitive).
    - No "/" in the pattern: matches the file name at any depth ("*.cs", "BACKLOG.md").
    - With "/": matches the whole path from the folder root; "*" stays within one folder, "**"
      spans folders ("Assets/**/*.cs" matches Assets/a.cs and Assets/x/y/a.cs;
      "Assets/**/UI/**" matches everything under any UI folder in Assets)."""
    path = path.replace("\\", "/").lstrip("/")
    pattern = pattern.replace("\\", "/").lstrip("/")
    if "/" not in pattern:
        return bool(_glob_re(pattern).match(path.rsplit("/", 1)[-1]))
    return bool(_glob_re(pattern).match(path))


def changed_files(folder: Path | str | None, since: float, globs: list[str] | None = None) -> list[str]:
    """Files under `folder` whose mtime is at or after `since` (epoch seconds), as sorted relative
    POSIX paths, keeping only those matching any of `globs` (all when None or empty).

    A plain mtime walk: Unity, MCP tools and commands write files the app never sees, so tool
    interception can't be relied on. Skipped: Library/ Temp/ Logs/ obj/ UserSettings/ at the top
    level, .git/ node_modules/ __pycache__/ .venv/ anywhere, .workspace/tmp/; symlinks aren't
    followed. Stops after MAX_SCAN_ENTRIES entries. Synchronous: use asyncio.to_thread in async code."""
    if not folder:
        return []
    root = Path(folder)
    if not root.is_dir():
        return []
    found: list[str] = []
    seen = 0
    stack: list[tuple[str, str]] = [(str(root), "")]
    while stack:
        path, rel = stack.pop()
        try:
            it = os.scandir(path)
        except OSError:
            continue
        with it:
            for e in it:
                seen += 1
                if seen > MAX_SCAN_ENTRIES:
                    log.warning("changed_files: stopped after %d entries in %s", MAX_SCAN_ENTRIES, root)
                    stack.clear()
                    break
                r = f"{rel}/{e.name}" if rel else e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        if e.name in SKIP_ANY_DIRS or (not rel and e.name in SKIP_TOP_DIRS) or r in SKIP_REL_DIRS:
                            continue
                        stack.append((e.path, r))
                    elif e.is_file(follow_symlinks=False) and e.stat(follow_symlinks=False).st_mtime >= since:
                        if not globs or any(glob_match(r, g) for g in globs):
                            found.append(r)
                except OSError:
                    continue
    return sorted(found)
