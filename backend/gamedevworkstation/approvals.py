"""Approval cards: the agent asks, the UI answers.

Kinds: effort (above-high), command, edit, delete, elevenlabs (large generation),
shared_tool, mcp_tool (a local MCP tool that isn't read-only), mcp_install (the Skills & MCP
assistant adding a server; it has no session), unity (a Unity op through the harness: payload op,
key, route, argv and the generic card's subject / markdown / buttons; see unity_bridge.ensure_allowed).
An effort approval yields a token minted by core.effort.APPROVALS.

Any other kind (hook_trust, gate escalations, campaign plan approval, ...) is shown by the UI's
generic card, from these payload fields:
- subject: the card's title line; markdown: its body (rendered as safe Markdown);
- buttons (optional): [{id, label, decision: "approve" | "deny", style?: "primary" | "ghost"}];
  without them the card shows Approve / Decline;
- note (optional): {label, placeholder} adds a text box whose text comes back as the answer's note.
The waiter gets {"status", "choice": button id, "note": text}; choice/note are also stored in the
payload as "answer".
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
from typing import Any

from .config import Config
from .core.effort import APPROVALS
from .core.types import new_id
from .db import DB, now
from .events import EventBus

COMMAND_KINDS = {"run_command", "command"}
# Shell syntax that chains, substitutes, redirects or backgrounds commands (zsh glob qualifiers such as
# *(e:…:) need parentheses too). A command line with any of these is more than one simple command.
SHELL_SYNTAX = frozenset(";&|`$()<>\n\r")


def has_shell_syntax(command: str) -> bool:
    return any(ch in SHELL_SYNTAX for ch in command)


class Approvals:
    def __init__(self, db: DB, bus: EventBus, config: Config):
        self.db, self.bus, self.config = db, bus, config
        self._waiters: dict[str, asyncio.Future] = {}

    def allowlisted(self, kind: str, subject: str) -> bool:
        """True if a `kind:pattern` rule (fnmatch) covers subject. For shell commands (run_command,
        command) a pattern only covers one simple command: a command line with shell operators or
        expansions (; & | ` $ ( ) < > or a line break) always gets the approval card, so
        `run_command:git status*` can't wave through `git status; curl … | sh`. Only the bare
        `run_command:*` rule (every command, explicitly) covers those. A rule with an empty pattern
        (`run_command:` or a bare `edit`) covers nothing: only a literal `kind:*` means everything."""
        compound = kind in COMMAND_KINDS and has_shell_syntax(subject)
        for pat in self.config.modes.get("allowlist", []) or []:
            k, _, p = str(pat).partition(":")
            p = p.strip()
            if not p or k.strip() != kind or (compound and p != "*"):
                continue
            if fnmatch.fnmatch(subject, p):
                return True
        return False

    def request(self, session_id: str | None, kind: str, payload: dict[str, Any]) -> str:
        aid = new_id("apr_")
        self.db.insert("approvals", {"id": aid, "session_id": session_id, "kind": kind,
                                     "payload": json.dumps(payload, default=str), "created_at": now()})
        self._waiters[aid] = asyncio.get_running_loop().create_future()
        self.bus.publish("approval.requested", {"id": aid, "kind": kind, "payload": payload, "status": "pending"},
                         session_id)
        return aid

    async def wait(self, aid: str, timeout: float | None = None) -> dict:
        fut = self._waiters.get(aid)
        if fut is None:
            row = self.db.one("SELECT * FROM approvals WHERE id=?", [aid])
            return {"status": (row or {}).get("status", "denied")}
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout)
        finally:
            if fut.done():
                self._waiters.pop(aid, None)

    SCHEDULED_TIMEOUT_S = 30 * 60

    async def ask(self, session_id: str | None, kind: str, payload: dict[str, Any]) -> dict:
        aid = self.request(session_id, kind, payload)
        timeout = None
        if session_id:
            row = self.db.one("SELECT settings FROM sessions WHERE id=?", [session_id])
            if row and json.loads(row["settings"] or "{}").get("scheduled_task"):
                timeout = self.SCHEDULED_TIMEOUT_S  # nobody may be there to answer a scheduled run
        try:
            return await self.wait(aid, timeout)
        except asyncio.TimeoutError:
            self.resolve(aid, "deny")
            return {"status": "denied", "timed_out": True}

    def expire_session(self, session_id: str) -> int:
        """A stopped run can't act on its open cards any more. Returns how many were open."""
        rows = self.db.all("SELECT id FROM approvals WHERE session_id=? AND status='pending'", [session_id])
        for r in rows:
            self.expire(r["id"])
        return len(rows)

    def expire(self, aid: str) -> None:
        """Close one open card (e.g. its run was cancelled); a waiter sees it as denied."""
        row = self.db.one("SELECT session_id, status FROM approvals WHERE id=?", [aid])
        if not row or row["status"] != "pending":
            return
        self.db.update("approvals", "id", aid, {"status": "expired", "resolved_at": now()})
        fut = self._waiters.pop(aid, None)
        if fut and not fut.done():
            fut.set_result({"status": "denied"})
        self.bus.publish("approval.resolved", {"id": aid, "status": "expired"}, row["session_id"])

    def resolve(self, aid: str, decision: str, *, choice: str | None = None, note: str | None = None) -> dict:
        """decision: approve | downgrade (effort: run at high instead) | deny. choice / note: the
        generic card's button id (must be one of payload.buttons when the card has buttons) and
        its text box; both are passed to the waiter and kept in the payload as "answer"."""
        row = self.db.one("SELECT * FROM approvals WHERE id=?", [aid])
        if not row:
            raise KeyError(aid)
        if row["status"] != "pending":
            return {"status": row["status"]}
        payload = json.loads(row["payload"])
        status = {"approve": "approved", "downgrade": "downgraded", "deny": "denied"}[decision]
        result: dict[str, Any] = {"status": status}
        if choice is not None or note is not None:
            ids = [str(b.get("id")) for b in payload.get("buttons") or [] if isinstance(b, dict)]
            if choice is not None and ids and str(choice) not in ids:
                raise ValueError(f"Unknown choice {choice!r}")
            result["choice"] = None if choice is None else str(choice)
            result["note"] = str(note or "")[:4000]
            payload["answer"] = {"choice": result["choice"], "note": result["note"]}
            self.db.update("approvals", "id", aid, {"payload": json.dumps(payload, default=str)})
        if row["kind"] == "effort" and status == "approved":
            result["token"] = APPROVALS.issue(aid, payload.get("effort", "max"))
        if row["kind"] == "effort" and status == "downgraded":
            result["effort"] = "high"
        self.db.update("approvals", "id", aid, {"status": status, "resolved_at": now()})
        fut = self._waiters.get(aid)
        if fut and not fut.done():
            fut.set_result(result)
        self.bus.publish("approval.resolved", {"id": aid, "kind": row["kind"], "status": status}, row["session_id"])
        return result

    def pending(self, session_id: str | None = None) -> list[dict]:
        sql, p = "SELECT * FROM approvals WHERE status='pending'", []
        if session_id:
            sql += " AND session_id=?"
            p = [session_id]
        rows = self.db.all(sql, p)
        for r in rows:
            r["payload"] = json.loads(r["payload"])
            # After a restart nobody is waiting on these any more.
            r["stale"] = r["id"] not in self._waiters
        return rows

    def expire_stale(self) -> None:
        """On startup: pending approvals from a previous run can't be answered."""
        self.db.execute("UPDATE approvals SET status='expired', resolved_at=? WHERE status='pending'", [now()])
