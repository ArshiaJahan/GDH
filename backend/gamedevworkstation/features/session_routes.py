"""Side-panel APIs: environment options, context breakdown and Compact; the new-session greeting."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from functools import cache
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI, HTTPException

from ..agent import context as cx
from ..core.types import ToolResultBlock
from ..skills import skills_prompt, turn_skill_segments
from ..store import SESSION_MODES

if TYPE_CHECKING:
    from ..app import AppState

# Kept for importers; the logic lives in agent/context.py.
CHARS_PER_TOKEN = cx.CHARS_PER_TOKEN
KEEP_RECENT_TURNS = cx.KEEP_RECENT_TURNS
COMPACT_PROMPT = cx.COMPACT_PROMPT
_est = cx.est
_msg_parts = cx.msg_parts


def context_breakdown(app: "AppState", sid: str) -> dict:
    s = app.store.get(sid)
    if not s:
        raise HTTPException(404)
    runner = app.runner
    segs = runner.system_segments(s)
    settings = s["settings"]
    progressive = settings.get("skill_mode") == "progressive"
    skill_segments = turn_skill_segments(settings, app.hooks.turn(sid)) if progressive else []
    skills_txt = ("\n".join(skill_segments) if progressive
                  else skills_prompt(settings.get("skills", [])))
    system_tokens = _est("\n".join(segs)) - _est(skills_txt)
    tools_tokens = _est(json.dumps([t.model_dump() for t in runner.tool_specs(s)]))
    msgs = runner.model_history(sid)
    msg_tokens = att_tokens = 0
    for m in msgs:
        a, b = _msg_parts(m)
        msg_tokens += a
        att_tokens += b
    skill_parts = None
    if progressive:
        pinned_tokens = sum(_est(seg) for seg in skill_segments if seg.startswith("Enabled skills:\n\n"))
        # Every full skill text still present counts, including skills evicted from the LRU:
        # unloading only stops retention at the next compaction; it doesn't rewrite history.
        calls = {c.id for m in msgs for c in m.tool_calls()
                 if c.name == "read_skill" and not c.input.get("path")}
        loaded_tokens = 0
        for m in msgs:
            if m.meta.get("skill_load"):
                loaded_tokens += _msg_parts(m)[0]
            else:
                loaded_tokens += sum(sum(cx.block_tokens(b)) for b in m.content
                                     if isinstance(b, ToolResultBlock) and not b.is_error and b.tool_use_id in calls)
        skill_parts = {"pinned": pinned_tokens, "index": _est(skills_txt) - pinned_tokens, "loaded": loaded_tokens}
        msg_tokens -= loaded_tokens
    parts = {"system": system_tokens, "tools": tools_tokens, "skills": _est(skills_txt),
             "messages": msg_tokens, "attachments": att_tokens}
    if skill_parts is not None:
        parts["skills"] = sum(skill_parts.values())
    est_total = sum(parts.values())
    # Calibrate against the last real request when we have one.
    last = app.db.one("SELECT input_tokens + cache_read_tokens + cache_write_tokens AS t, model FROM usage_records "
                      "WHERE session_id=? AND role='main' AND ok=1 AND billing != 'subscription' ORDER BY ts DESC LIMIT 1", [sid])
    calibrated = False
    if last and last["t"] and est_total and last["model"] == s["model"]:
        f = last["t"] / est_total
        if 0.4 < f < 2.5:
            parts = {k: int(v * f) for k, v in parts.items()}
            if skill_parts is not None:
                skill_parts = {k: int(v * f) for k, v in skill_parts.items()}
                parts["skills"] = sum(skill_parts.values())
            calibrated = True
    window = app.config.model(s["model"]).context_window
    total = sum(parts.values())
    fraction = total / window if window else 0
    return {"model": s["model"], "window": window, "total": total, "fraction": fraction,
            "parts": parts, "calibrated": calibrated,
            **({"skill_parts": skill_parts} if skill_parts is not None else {}),
            "compactable_messages": max(0, len(msgs) - 2 * KEEP_RECENT_TURNS),
            "can_compact": cx.manual_cut(msgs) is not None, "auto_compact_at": cx.AUTO_COMPACT_AT,
            "level": "danger" if fraction >= cx.DANGER_AT else "warn" if fraction >= cx.WARN_AT else "ok"}


async def compact(app: "AppState", sid: str) -> dict:
    """Summarize older turns with claude.fast at low effort; originals stay in history."""
    s = app.store.get(sid)
    if not s:
        raise HTTPException(404)
    if app.runner.is_running(sid):
        raise HTTPException(409, "Wait for the agent to finish (or stop it) before compacting.")
    msgs = app.runner.model_history(sid)
    cut = cx.manual_cut(msgs)
    if cut is None:
        return {"compacted": 0, "message": "Nothing to compact yet."}
    from ..providers.base import ProviderError

    try:
        return await cx.compact_messages(app, sid, msgs, cut)
    except ProviderError as e:
        raise HTTPException(502, f"Compact failed: {e}") from e


@cache
def account_full_name() -> str:
    """The Mac account's full name (`id -F`), else the passwd entry's gecos name; "" when unknown.
    Only the local account: never the Claude login or any email address."""
    if sys.platform == "darwin":
        try:
            r = subprocess.run(["/usr/bin/id", "-F"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        import pwd

        return pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
    except (ImportError, KeyError, OSError):
        return ""


def greeting_name(full: str) -> str | None:
    """"Arshia Jahan" → "Arshia J." (first name and last initial), "Arshia" → "Arshia"; None when
    there's no usable name, or it looks like an email address or a handle rather than a name."""
    full = " ".join((full or "").split())
    if not full or "@" in full or "/" in full:
        return None
    words = [w for w in full.split(" ") if re.search(r"[^\W\d_]", w)]
    if not words:
        return None
    first = words[0][:40]
    if len(words) == 1:
        return first
    initial = next((c for c in words[-1] if c.isalpha()), "")
    return f"{first} {initial.upper()}." if initial else first


def register(app: FastAPI, api: APIRouter, S: "AppState") -> None:
    @api.get("/greeting")
    async def greeting() -> dict:
        """The new-session screen's "What should we work on, <name>?": the Mac account's first name
        and last initial (null: "What should we work on?")."""
        return {"name": greeting_name(await asyncio.to_thread(account_full_name))}

    @api.get("/sessions/{sid}/context")
    async def ctx(sid: str) -> dict:
        return context_breakdown(S, sid)

    @api.post("/sessions/{sid}/compact")
    async def do_compact(sid: str) -> dict:
        return await compact(S, sid)

    @api.get("/environment")
    async def environment() -> dict:
        try:
            import claude_agent_sdk  # noqa: F401

            sdk = True
        except ImportError:
            sdk = False
        cc = S.extensions.get("claude_code")
        cc_status = await cc.probe.status() if cc is not None else None  # type: ignore[attr-defined]  # cached 60 s
        return {
            "harnesses": {"builtin": True, "agent_sdk": sdk, "codex_cli": bool(shutil.which("codex")),
                          "claude_code": bool(cc_status and cc_status["installed"])},
            "claude_code": cc_status,
            "accounts": {p: S.config.profiles(p) for p in ("anthropic", "openai", "elevenlabs")},
            "models": [{"id": k, "display_name": v.display_name, "provider": v.provider, "tier": S.config.tier_of(k),
                        "efforts": ["none", *v.efforts]}
                       for k, v in S.config.models.items()],
            "tiers": S.config.tiers,
            "tier_models": S.config.tier_models(),
            "modes": list(SESSION_MODES),  # Plan / Ask / Accept edits; no bypass mode
        }
