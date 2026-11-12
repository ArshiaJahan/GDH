"""Alternative harnesses for the main agent of a session.

- builtin: GameDevWorkstation's own loop (agent/loop.py) — supports subagents, delegation, ElevenLabs, MCP.
- agent_sdk: the Claude Agent SDK (Claude Code's loop and tools) in the session folder.
- codex_cli: `codex exec` in the session folder, resumed across turns.
- claude_code: the user's own `claude` CLI, logged in with their subscription, one long-lived
  stream-json process per session (features/claude_code.py).

Both keep the transcript in GameDevWorkstation's own format (tool calls paired with results), so a
session can switch harness while idle.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, FastAPI

from ..agent.tools import GIT_WRITE_REFUSED, in_git_metadata
from ..config import get_key, sessions_dir
from ..core.types import (Message, TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock, Usage,
                          new_id)
from ..providers.base import compute_cost

if TYPE_CHECKING:
    from ..app import AppState

READ_ONLY_SDK_TOOLS = {"Read", "Glob", "Grep", "LS", "WebSearch", "TodoWrite", "NotebookRead", "Task", "Agent"}
# WebFetch is read-only too, but gate() first checks its URL: http(s) to a public host only, never this
# Mac or its network (the same rule as web_fetch; the CLI connects itself, so this is a pre-check).
WEB_FETCH_SDK_TOOLS = {"WebFetch"}
EDIT_SDK_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# Tools with no side effects of their own that the PreToolUse hook leaves to the CLI's rules and
# can_use_tool (plan-mode exits, questions, reading or stopping a background shell, loading a skill).
DEFERRED_SDK_TOOLS = {"BashOutput", "KillShell", "KillBash", "TaskOutput", "TaskStop", "ExitPlanMode",
                      "EnterPlanMode", "AskUserQuestion", "ToolSearch", "Skill"}
# The hook waits for the user's answer on an approval card; past this it fails, which blocks the call.
HOOK_TIMEOUT_S = 24 * 3600
PROJECT_INSTRUCTIONS = ("CLAUDE.md", ".claude/CLAUDE.md")
PROJECT_INSTRUCTIONS_MAX_CHARS = 40_000
SDK_MODE = {"ask": "default", "accept_edits": "acceptEdits", "plan": "plan"}
# Recap of earlier turns for a provider thread that starts without them (bounded).
RECAP_MESSAGES = 12
RECAP_MESSAGE_CHARS = 400
RECAP_SUMMARY_CHARS = 2000
RECAP_MAX_CHARS = 6000


def _cwd(session: dict) -> Path:
    if session.get("folder"):
        return Path(session["folder"])
    d = sessions_dir() / session["id"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _project_instructions(cwd: Path) -> str | None:
    """The folder's CLAUDE.md files as a system prompt (the Agent SDK harness loads no settings files,
    so the CLI doesn't read them itself). Bounded; None when there are none."""
    parts = []
    root = cwd.resolve()
    for rel in PROJECT_INSTRUCTIONS:
        f = cwd / rel
        try:
            if f.is_file() and root in f.resolve().parents:  # not a symlink out of the folder
                parts.append(f"Contents of {f} (project instructions):\n\n{f.read_text(errors='replace')}")
        except OSError:
            continue
    return "\n\n".join(parts)[:PROJECT_INSTRUCTIONS_MAX_CHARS] or None


async def _web_fetch_refusal(url: str) -> str | None:
    """None when the SDK's WebFetch may fetch `url`, else why not: only http(s) URLs whose host
    resolves to public addresses only (no localhost, private, link-local, CGNAT/Tailscale ranges)."""
    import httpx

    from ..safe_fetch import DEFAULT_PORT, UnsafeURL, resolve_public

    try:
        u = httpx.URL(url.strip())
    except (httpx.InvalidURL, TypeError):
        return "Not a valid URL."
    if u.scheme not in ("http", "https") or not u.host:
        return "WebFetch: only http or https URLs."
    try:
        await resolve_public(u.host, u.port or DEFAULT_PORT[u.scheme])
    except UnsafeURL as e:
        return f"WebFetch refused: {e} Only public web pages can be fetched."
    except Exception as e:  # noqa: BLE001 — can't check it, so it isn't fetched
        return f"WebFetch refused: couldn't check {u.host} ({type(e).__name__})."
    return None


def _prompt_text(msg: Message) -> str:
    parts = []
    for b in msg.content:
        if isinstance(b, TextBlock):
            parts.append(b.text)
        elif getattr(b, "path", None):
            parts.append(f"[Attached {b.type}: {b.path}]")
    return "\n\n".join(parts)


def make_gate(app: "AppState", session: Callable[[], dict], cwd: Path,
              touched: list[Path]) -> Callable[[str, dict], Awaitable[str | None]]:
    """GameDevWorkstation's decision for one Claude Code tool call (Agent SDK and claude_code harnesses):
    the returned gate(name, input) is None to allow, else the reason it's refused.
    Folder scope, data policy, Plan mode, git metadata, the before-write snapshot and the approval
    cards all live here. `session()` gives the session as it is now (its mode can change mid-turn);
    files about to be written are appended to `touched` (for changes.notify after the turn)."""
    sid = session()["id"]
    roots = [cwd.resolve(), app.worktrees_root(sid).resolve()]

    def full_path(path_str: str) -> Path:
        p = Path(path_str).expanduser()
        return (p if p.is_absolute() else cwd / p).resolve()

    def inside(path_str: str | None) -> bool:
        if not path_str:
            return True  # tools default to the working folder
        full = full_path(path_str)
        return any(full == r or r in full.parents for r in roots)

    async def gate(name: str, inp: dict) -> str | None:
        s = session()
        target = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
        if name in READ_ONLY_SDK_TOOLS | EDIT_SDK_TOOLS and not inside(target):
            return f"{target} is outside the session folder."
        if name in READ_ONLY_SDK_TOOLS:
            if target and not app.policy.allows_path(full_path(target), "anthropic"):
                return "That file is marked sensitive."
            return None
        if name in WEB_FETCH_SDK_TOOLS:
            return await _web_fetch_refusal(str(inp.get("url") or ""))
        if name in EDIT_SDK_TOOLS:
            if s["mode"] == "plan":
                return "Plan only mode: no edits."
            full = full_path(target) if target else None
            if full and (in_git_metadata(full) or in_git_metadata(target)):
                return GIT_WRITE_REFUSED.format(path=target)
            if not (s["mode"] == "accept_edits" or app.approvals.allowlisted("edit", str(full or ""))):
                res = await app.approvals.ask(sid, "edit", {
                    "subject": target or name, "path": target, "action": name.lower(),
                    "old": str(inp.get("old_string", ""))[:500],
                    "new": str(inp.get("new_string", inp.get("content", "")))[:500]})
                if res["status"] != "approved":
                    return "The user declined."
            if full:
                app.changes.snapshot(sid, full)  # for the Changes card's diff and revert
                touched.append(full)
            return None
        if name == "Bash":
            cmd = inp.get("command", "")
            if s["mode"] == "plan":
                return "Plan only mode: no commands."
            if app.approvals.allowlisted("run_command", cmd):
                return None
            res = await app.approvals.ask(sid, "command", {"subject": cmd, "command": cmd, "cwd": str(cwd)})
        else:
            res = await app.approvals.ask(sid, "command", {"subject": name, "command": f"{name} {json.dumps(inp)[:300]}",
                                                           "cwd": str(cwd)})
        return None if res["status"] == "approved" else "The user declined."

    return gate


class Harnesses:
    def __init__(self, app: "AppState"):
        self.app = app

    async def run(self, session: dict) -> None:
        h = session["harness"]
        if h == "agent_sdk":
            await self._agent_sdk(session)
        elif h == "codex_cli":
            await self._codex_cli(session)
        elif h == "claude_code" and (cc := self.app.extensions.get("claude_code")) is not None:
            await cc.run_turn(session)  # type: ignore[attr-defined]  # features/claude_code.py
        else:
            raise ValueError(f"unknown harness {h}")

    def _last_user(self, sid: str) -> Message:
        msgs = self.app.store.messages(sid, include_compacted=False)
        for m in reversed(msgs):
            if m.role == "user" and not m.meta.get("tool_results"):
                return m
        raise RuntimeError("No user message to answer")

    def _recap(self, sid: str, before: Message) -> str:
        """A bounded text recap of the visible history before `before` (the message being answered),
        for a provider thread that hasn't seen it: a copy or fork, a harness switch, a failed resume."""
        lines: list[str] = []
        for m in self.app.store.messages(sid, include_compacted=False):
            if m.id == before.id:
                break
            if m.meta.get("tool_results") or m.meta.get("error") or m.meta.get("notice"):
                continue  # app notes ("reply hit the output limit") are for the user, never the model
            if txt := m.text().strip():
                if m.meta.get("summary"):
                    lines.append(f"summary of earlier turns: {txt[:RECAP_SUMMARY_CHARS]}")
                else:
                    lines.append(f"{m.role}: {txt[:RECAP_MESSAGE_CHARS]}")
        return "\n".join(lines[-RECAP_MESSAGES:])[-RECAP_MAX_CHARS:]

    def _prompt(self, sid: str, recap: bool) -> str:
        """The text sent for this turn: the last user message, after a recap when `recap` and
        there is earlier history."""
        last = self._last_user(sid)
        prompt = _prompt_text(last)
        if recap and (r := self._recap(sid, last)):
            return f"Earlier in this conversation:\n{r}\n\nNow: {prompt}"
        return prompt

    # ------------------------------------------------------------ claude agent sdk

    async def _agent_sdk(self, s: dict) -> None:
        try:
            from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, HookMatcher, PermissionResultAllow,
                                          PermissionResultDeny, ResultMessage, UserMessage, query)
            from claude_agent_sdk import TextBlock as SText, ThinkingBlock as SThink, ToolResultBlock as SResult, \
                ToolUseBlock as SUse
        except ImportError as e:
            raise RuntimeError("The Claude Agent SDK isn't installed (uv sync --extra agent-sdk).") from e
        app, sid = self.app, s["id"]
        s = {**s, "model": app.config.resolve(s["model"])}  # a tier key never reaches the SDK or pricing
        app.usage.check(sid)
        effort, token = await app.runner._effective_effort(s)
        if effort == "cancel":
            app.store.add_message(sid, Message.assistant("Cancelled: effort above high wasn't approved."))
            return
        mcfg = app.config.model(s["model"])
        resume = s["settings"].get("agent_sdk_session")
        prompt = self._prompt(sid, recap=not resume)  # a new SDK session hasn't seen the earlier turns
        cwd = _cwd(s)
        touched: list[Path] = []
        gate = make_gate(app, lambda: s, cwd, touched)

        async def pre_tool_use(data: Any, _tool_use_id: str | None, _ctx: Any) -> dict:
            name = data.get("tool_name", "")
            if name in DEFERRED_SDK_TOOLS:
                return {}  # no say: the CLI's own rules, then can_use_tool (which asks), decide
            why = await gate(name, data.get("tool_input") or {})
            out: dict[str, Any] = {"hookEventName": "PreToolUse", "permissionDecision": "deny" if why else "allow"}
            if why:
                out["permissionDecisionReason"] = why
            return {"hookSpecificOutput": out}

        async def can_use_tool(name: str, inp: dict, _ctx: Any):
            # Second line: reached only for calls the hook left undecided (or if a hook didn't run).
            why = await gate(name, inp)
            if why:
                return PermissionResultDeny(behavior="deny", message=why)
            return PermissionResultAllow(behavior="allow")

        async def prompt_stream() -> AsyncIterator[dict]:
            yield {"type": "user", "message": {"role": "user", "content": prompt}}

        env = {}
        profile = app.config.profile_for(s, "anthropic")
        if key := get_key("anthropic", profile):
            env["ANTHROPIC_API_KEY"] = key
        # Session allowance (incl. "Resume anyway") and daily allowance; None only when no limit is set.
        left = app.usage.headroom(sid)
        # No settings files at all (setting_sources=[]): a project's .claude/settings.json can carry
        # permission allow rules, hooks, env and statusLine commands, and the agent can write that file.
        # Project MCP configs (.mcp.json) are ignored too (strict_mcp_config). CLAUDE.md still reaches
        # the model, read here and passed as the system prompt (text only, nothing runs from it).
        opts = ClaudeAgentOptions(
            model=s["model"], cwd=str(cwd), permission_mode=SDK_MODE.get(s["mode"], "default"),
            can_use_tool=can_use_tool, resume=resume, env=env,
            effort=None if effort == "none" else effort, max_budget_usd=None if left is None else max(left, 0.01),
            setting_sources=[], strict_mcp_config=True, system_prompt=_project_instructions(cwd),
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use], timeout=HOOK_TIMEOUT_S,
                                              on_failure="block")]})
        pending_results: list[ToolResultBlock] = []
        t0 = time.monotonic()
        async for m in query(prompt=prompt_stream(), options=opts):
            if isinstance(m, AssistantMessage):
                if pending_results:
                    app.store.add_message(sid, Message(role="user", content=pending_results, meta={"tool_results": True}))
                    pending_results = []
                blocks: list[Any] = []
                for b in m.content:
                    if isinstance(b, SText):
                        blocks.append(TextBlock(text=b.text))
                    elif isinstance(b, SThink):
                        blocks.append(ThinkingBlock(thinking=b.thinking, signature=getattr(b, "signature", None),
                                                    provider="anthropic"))
                    elif isinstance(b, SUse):
                        blocks.append(ToolUseBlock(id=b.id, name=b.name, input=b.input))
                        app.bus.publish("tool.started", {"tool_use_id": b.id, "name": b.name, "input": b.input}, sid)
                if blocks:
                    app.store.add_message(sid, Message(role="assistant", content=blocks,
                                                       meta={"model": m.model, "effort": effort, "harness": "agent_sdk"}))
            elif isinstance(m, UserMessage) and isinstance(m.content, list):
                for b in m.content:
                    if isinstance(b, SResult):
                        text = b.content if isinstance(b.content, str) else json.dumps(b.content)[:20000]
                        pending_results.append(ToolResultBlock.text(b.tool_use_id, text or "(no output)",
                                                                    is_error=bool(b.is_error)))
                        app.bus.publish("tool.finished", {"tool_use_id": b.tool_use_id, "is_error": bool(b.is_error),
                                                          "output": (text or "")[:4000]}, sid)
            elif isinstance(m, ResultMessage):
                if pending_results:
                    app.store.add_message(sid, Message(role="user", content=pending_results, meta={"tool_results": True}))
                    pending_results = []
                u = m.usage or {}
                usage = Usage(input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0),
                              cache_read_tokens=u.get("cache_read_input_tokens", 0),
                              cache_write_tokens=u.get("cache_creation_input_tokens", 0))
                usage.cost_usd = m.total_cost_usd if m.total_cost_usd is not None else compute_cost(mcfg, usage)
                app.usage.record(provider="anthropic", model=s["model"], usage=usage, session_id=sid, profile=profile,
                                 role="main", run_id=f"main:{sid}", effort=effort,
                                 latency_ms=m.duration_ms or int((time.monotonic() - t0) * 1000),
                                 ok=not m.is_error)
                app.store.update(sid, settings={"agent_sdk_session": m.session_id})
                for f in dict.fromkeys(touched):
                    app.changes.notify(sid, f, "anthropic", s["model"])
                if m.is_error and m.result:
                    app.store.add_message(sid, Message(role="assistant", content=[TextBlock(text=str(m.result))],
                                                       meta={"error": True, "error_kind": "harness"}))

    # ------------------------------------------------------------------- codex cli

    async def _codex_cli(self, s: dict) -> None:
        app, sid = self.app, s["id"]
        if not shutil.which("codex"):
            raise RuntimeError("The Codex CLI isn't installed (npm i -g @openai/codex).")
        app.usage.check(sid)
        cwd = _cwd(s)
        m = app.config.resolve(s["model"])
        model = m if app.config.model(m).provider == "openai" else app.config.resolve("codex.cli")
        effort, _token = await app.runner._effective_effort(s)  # above high asks, like every other path
        if effort == "cancel":
            app.store.add_message(sid, Message.assistant("Cancelled: effort above high wasn't approved."))
            return
        if effort == "none":
            effort = "low"
        # Codex runs shell commands of its own choosing (sandboxed, but still commands), and shell commands
        # always ask unless allowlisted: once per turn in Ask and Accept edits. Plan runs read-only.
        if s["mode"] != "plan" and not app.approvals.allowlisted("codex_cli", str(cwd)):
            res = await app.approvals.ask(sid, "command", {
                "subject": "Codex CLI turn", "command": f"codex exec (sandbox: workspace-write) in {cwd}", "cwd": str(cwd)})
            if res["status"] != "approved":
                app.store.add_message(sid, Message.assistant("The Codex CLI turn was declined."))
                return
        sandbox = "read-only" if s["mode"] == "plan" else "workspace-write"
        thread = s["settings"].get("codex_thread")
        base = ["--json", "--skip-git-repo-check", "-m", model, "-c", f'model_reasoning_effort="{effort}"',
                "--sandbox", sandbox, "-C", str(cwd)]
        args = ["codex", "exec", *base, "resume", thread, "-"] if thread else ["codex", "exec", *base, "-"]
        # A new thread (copy, fork, harness switch) hasn't seen the earlier turns: recap them.
        code, thread_id, err = await self._codex_turn(s, args, self._prompt(sid, recap=not thread), model, effort)
        if code != 0 and thread:
            # Resume failed (old thread, CLI change): start fresh with a short recap.
            code, thread_id, err = await self._codex_turn(s, ["codex", "exec", *base, "-"],
                                                          self._prompt(sid, recap=True), model, effort)
        if thread_id:
            app.store.update(sid, settings={"codex_thread": thread_id})
        if code != 0:
            app.store.add_message(sid, Message(role="assistant", content=[TextBlock(text=f"Codex CLI exited {code}: {err[-800:]}")],
                                               meta={"error": True, "error_kind": "harness"}))

    async def _codex_turn(self, s: dict, args: list[str], prompt: str, model: str, effort: str) -> tuple[int, str | None, str]:
        app, sid = self.app, s["id"]
        env = dict(os.environ)
        profile = app.config.profile_for(s, "openai")
        if key := get_key("openai", profile):
            env["CODEX_API_KEY"] = key
        tier = "codex.cli" if model == app.config.resolve("codex.cli") else None
        jid = app.jobs.start(sid, "codex_cli", f"Codex CLI turn · {app.config.label(model, tier)}",
                             {"model": model, "tier": tier})
        proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, env=env, start_new_session=True,
                                                    limit=2**24)
        app.jobs.procs[jid] = proc
        assert proc.stdin and proc.stdout and proc.stderr
        proc.stdin.write(prompt.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        thread_id = None
        mcfg = app.config.model(model)
        t0 = time.monotonic()
        try:
            async for line in proc.stdout:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t, item = ev.get("type"), ev.get("item") or {}
                if t == "thread.started":
                    thread_id = ev.get("thread_id")
                elif t == "item.completed" and item.get("type") == "agent_message":
                    app.store.add_message(sid, Message(role="assistant", content=[TextBlock(text=item.get("text", ""))],
                                                       meta={"model": model, "effort": effort, "harness": "codex_cli"}))
                elif t == "item.completed" and item.get("type") in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
                    tid = new_id("toolu_")
                    name = {"command_execution": "shell", "file_change": "edit_files"}.get(item["type"], item["type"])
                    inp = {"command": item.get("command")} if item["type"] == "command_execution" else {
                        k: v for k, v in item.items() if k not in ("id", "type", "status")}
                    out = item.get("aggregated_output") or item.get("status") or "done"
                    app.store.add_message(sid, Message(role="assistant", content=[ToolUseBlock(id=tid, name=name, input=inp)],
                                                       meta={"model": model, "harness": "codex_cli"}))
                    app.store.add_message(sid, Message(role="user", meta={"tool_results": True}, content=[
                        ToolResultBlock.text(tid, str(out)[:8000], is_error=item.get("exit_code") not in (None, 0))]))
                    app.jobs.log(jid, f"{name}: {json.dumps(inp)[:200]}\n")
                    if item["type"] == "file_change":
                        for ch in item.get("changes") or []:
                            fp = Path(ch.get("path", ""))
                            fp = fp if fp.is_absolute() else _cwd(s) / fp
                            app.changes.notify(sid, fp, "openai", model)  # indexes artifacts for Outputs
                        app.bus.publish("file.changed", {"path": str(_cwd(s))}, sid)
                elif t == "turn.completed":
                    u = ev.get("usage") or {}
                    cached = u.get("cached_input_tokens", 0)
                    usage = Usage(input_tokens=max(u.get("input_tokens", 0) - cached, 0), cache_read_tokens=cached,
                                  output_tokens=u.get("output_tokens", 0), reasoning_tokens=u.get("reasoning_output_tokens", 0))
                    usage.cost_usd = compute_cost(mcfg, usage)
                    app.usage.record(provider="openai", model=model, usage=usage, session_id=sid, role="main", profile=profile,
                                     run_id=f"main:{sid}", effort=effort, latency_ms=int((time.monotonic() - t0) * 1000))
            await proc.wait()
            err = (await proc.stderr.read()).decode(errors="replace")
        finally:
            app.jobs.procs.pop(jid, None)
            if proc.returncode is None:  # cancelled, budget hit or a store error: don't leave codex running
                from ..services import _kill_tree

                _kill_tree(proc)
        app.jobs.finish(jid, "done" if proc.returncode == 0 else "failed", exit_code=proc.returncode)
        return proc.returncode or 0, thread_id, err


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    S.extensions["harnesses"] = Harnesses(S)
