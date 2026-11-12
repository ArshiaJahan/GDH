"""Session management: groups, Trash, archive, duplicate/fork, read state, search and auto-titles.

Registered by server.py *before* the `/sessions/{sid}` routes, so `/sessions/search` and
`/sessions/bulk` aren't taken for session ids. Every change goes through SessionStore, which
publishes `session.created` / `session.updated` / `session.deleted` / `groups.updated`.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException

from ..core.types import ChatRequest, Message

if TYPE_CHECKING:
    from ..app import AppState

TITLE_PROMPT = """Write a short title (3 to 6 words) for the conversation below, in the language it is written in.
Reply with the title only: no quotes, no trailing punctuation, no preamble."""
DAY_S = 86400


async def halt_session(app: "AppState", sid: str) -> None:
    """Stop a session's run and everything waiting on it: its background jobs and approval cards."""
    task = app.runner.running.get(sid)
    await app.runner.stop(sid)
    if task and not task.done():
        await asyncio.wait([task], timeout=5)
    app.approvals.expire_session(sid)
    for j in app.jobs.list(sid, limit=500):
        if j["status"] in ("running", "queued"):
            await app.jobs.cancel(j["id"])


async def purge_session(app: "AppState", sid: str) -> None:
    """Delete a session for good: stop it, remove its rows, then its subagent worktrees
    (unmerged work stays on its `gdw/<unit>` branch; see worktrees.cleanup_session)."""
    from .worktrees import cleanup_session

    await halt_session(app, sid)
    app.store.delete(sid)
    # Its gate results go with it; campaigns survive, keeping the session in their history (ended).
    app.db.execute("DELETE FROM gate_runs WHERE session_id=?", [sid])
    app.db.execute("UPDATE campaign_sessions SET ended_at=COALESCE(ended_at, ?), end_reason=COALESCE(end_reason, "
                   "'deleted') WHERE session_id=?", [time.time(), sid])
    app.db.execute("UPDATE campaigns SET claim_session=NULL WHERE claim_session=?", [sid])
    await cleanup_session(app, sid)


def valid_group(app: "AppState", gid: Any) -> str | None:
    """A group id from the client: None/"" = ungrouped; an unknown id is a 400."""
    if gid in (None, ""):
        return None
    if not app.store.group(str(gid)):
        raise HTTPException(400, "No such group")
    return str(gid)


def number_arg(v: Any, name: str) -> float:
    """A finite number from the client (sort orders); anything else is a 400."""
    try:
        if isinstance(v, bool):
            raise TypeError
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{name} must be a number") from None
    if not math.isfinite(f):
        raise HTTPException(400, f"{name} must be a number")
    return f


def _clean_title(text: str) -> str:
    line = next((ln for ln in (text or "").splitlines() if ln.strip()), "")
    line = re.sub(r"^\s*(title\s*:\s*)", "", line, flags=re.I)
    line = re.sub(r"\s+", " ", line).strip().strip("\"'`*#“”‘’ ").rstrip(".:;,!").strip()
    words = line.split(" ")
    if len(words) > 10:
        line = " ".join(words[:6])
    return line[:60].strip()


class Titler:
    """Names a session after its first reply with claude.fast at low effort, through the normal
    provider adapter (so effort checks and usage recording apply). Never blocks or fails a turn."""

    def __init__(self, app: "AppState"):
        self.app = app
        self._tasks: set[asyncio.Task] = set()

    def enabled(self) -> bool:
        return bool(self.app.config.sessions.get("auto_title", True))

    def wants_title(self, sid: str) -> bool:
        s = self.app.store.get(sid)
        if not s or not self.enabled() or s["deleted"]:
            return False
        src = s["settings"].get("title_source")
        if not (s["title"] == "New session" or src == "message"):
            return False  # named by the user, a scheduled task, a copy, or already auto-titled
        msgs = self.app.store.messages(sid)
        return any(m.role == "assistant" and not m.meta.get("error") and not m.meta.get("notice") and m.text().strip()
                   for m in msgs)

    def schedule(self, sid: str) -> None:
        """Called when a turn finished. Fire and forget."""
        try:
            if not self.wants_title(sid):
                return
        except Exception:  # noqa: BLE001
            return
        t = asyncio.create_task(self._quiet(sid))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _quiet(self, sid: str) -> None:
        try:
            await self.generate(sid)
        except Exception:  # noqa: BLE001 — no key, provider down, budget hit: keep the title we have
            pass

    async def generate(self, sid: str, *, force: bool = False) -> str | None:
        app = self.app
        s = app.store.get(sid)
        if not s:
            raise KeyError(sid)
        parts: list[str] = []
        for m in app.store.messages(sid):
            if m.meta.get("tool_results") or m.meta.get("summary") or m.meta.get("error") or m.meta.get("notice"):
                continue
            if txt := m.text().strip():
                parts.append(f"{m.role.upper()}: {txt[:1500]}")
            if len(parts) >= 4:
                break
        if not parts:
            return None
        model = app.config.resolve("claude.fast")
        mcfg = app.config.model(model)
        profile = app.config.profile_for(s, mcfg.provider)  # the session's key profile for that provider
        provider = app.providers.for_model(model, profile)
        app.usage.check(sid)
        req = ChatRequest(model=model, effort="low", max_tokens=2000, show_thinking=False, system=TITLE_PROMPT,
                          messages=[Message.user("\n\n".join(parts)[:6000])], metadata={"run_id": f"title:{sid}"})
        try:
            resp = await provider.complete(req)
        except Exception:
            from ..core.types import Usage

            app.usage.record(provider=mcfg.provider, model=model, usage=Usage(), session_id=sid, profile=profile,
                             role="title", effort="low", feature="title", ok=False, error_kind="other")
            raise
        app.usage.record(provider=mcfg.provider, model=model, usage=resp.usage, session_id=sid, profile=profile,
                         role="title", effort="low", feature="title", latency_ms=resp.latency_ms)
        title = _clean_title(resp.text())
        if not title:
            return None
        cur = app.store.get(sid)
        if not cur or (not force and cur["title"] != s["title"]):  # renamed while we were asking
            return None
        app.store.update(sid, title=title, settings={"title_source": "auto"})
        return title

    async def aclose(self) -> None:
        for t in list(self._tasks):
            t.cancel()


class TrashJanitor:
    """Empties Trash of sessions deleted more than [sessions] trash_days (30) ago: at startup, then daily."""

    def __init__(self, app: "AppState"):
        self.app = app
        self._task: asyncio.Task | None = None

    def days(self) -> float:
        return float(self.app.config.sessions.get("trash_days", 30) or 30)

    def run_once(self) -> list[str]:
        return self.app.store.purge_expired(self.days())

    async def run_once_async(self) -> list[str]:
        """run_once, then remove the purged sessions' subagent worktrees."""
        from .worktrees import cleanup_session

        ids = self.run_once()
        for sid in ids:
            await cleanup_session(self.app, sid)
        return ids

    async def astart(self) -> None:
        try:
            await self.run_once_async()
        except Exception:  # noqa: BLE001 — never block startup
            pass

        async def loop() -> None:
            while True:
                await asyncio.sleep(DAY_S)
                try:
                    await self.run_once_async()
                except Exception:  # noqa: BLE001
                    pass

        self._task = asyncio.create_task(loop())

    async def aclose(self) -> None:
        if self._task:
            self._task.cancel()


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    titler = Titler(S)
    S.extensions["titler"] = titler
    S.extensions["trash_janitor"] = TrashJanitor(S)
    store = S.store

    def need(sid: str) -> dict:
        s = store.get(sid)
        if not s:
            raise HTTPException(404, "No such session")
        return s

    def group_arg(gid: Any) -> str | None:
        return valid_group(S, gid)

    # ------------------------------------------------------------ sessions

    @api.get("/sessions/search")
    async def search(q: str = "", limit: int = 30) -> list[dict]:
        return store.search(q, max(1, min(limit, 100)))

    @api.post("/sessions/bulk")
    async def bulk(body: dict = Body(...)) -> dict:
        ids = [i for i in body.get("ids") or [] if isinstance(i, str)]
        action = body.get("action")
        if action not in ("pin", "unpin", "archive", "unarchive", "delete", "restore", "purge", "move", "read",
                          "unread"):
            raise HTTPException(400, f"Unknown action: {action}")
        gid = group_arg(body.get("group_id")) if action == "move" else None
        done = 0
        for sid in ids:
            if not store.get(sid):
                continue
            if action in ("pin", "unpin"):
                store.update(sid, pinned=action == "pin")
            elif action in ("archive", "unarchive"):
                store.update(sid, archived=action == "archive")
            elif action in ("delete", "purge"):
                store.trash(sid)  # first, so no new message can start a run while we stop this one
                if action == "purge":
                    await purge_session(S, sid)
                else:
                    await halt_session(S, sid)
            elif action == "restore":
                store.restore(sid)
            elif action == "move":
                store.update(sid, group_id=gid)
            elif action == "read":
                store.mark_read(sid)
            elif action == "unread":
                store.mark_unread(sid)
            done += 1
        return {"ok": True, "count": done}

    @api.post("/sessions/reorder")
    async def reorder(body: dict = Body(...)) -> dict:
        store.reorder([i for i in body.get("ids") or [] if isinstance(i, str)])
        return {"ok": True}

    @api.post("/sessions/{sid}/restore")
    async def restore(sid: str) -> dict:
        need(sid)
        return store.restore(sid)  # type: ignore[return-value]

    @api.post("/sessions/{sid}/duplicate")
    async def duplicate(sid: str) -> dict:
        need(sid)
        return store.duplicate(sid)

    @api.post("/sessions/{sid}/fork")
    async def fork(sid: str, body: dict = Body(...)) -> dict:
        need(sid)
        try:
            return store.fork(sid, str(body.get("message_id") or ""))
        except KeyError:
            raise HTTPException(400, "That message isn't in this session") from None

    @api.post("/sessions/{sid}/read")
    async def read(sid: str) -> dict:
        need(sid)
        return store.mark_read(sid)  # type: ignore[return-value]

    @api.post("/sessions/{sid}/unread")
    async def unread(sid: str) -> dict:
        need(sid)
        return store.mark_unread(sid)  # type: ignore[return-value]

    @api.post("/sessions/{sid}/title")
    async def regenerate_title(sid: str) -> dict:
        """Regenerate the title now (whatever the current one is)."""
        need(sid)
        try:
            title = await titler.generate(sid, force=True)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"Couldn't generate a title: {e}") from e
        if not title:
            raise HTTPException(400, "Nothing to name yet: send a message first.")
        return need(sid)

    @api.post("/trash/empty")
    async def empty_trash() -> dict:
        purged = 0
        for s in store.list(view="trash"):
            cur = store.get(s["id"])  # purging the ones before may take a while: skip any restored meanwhile
            if not cur or not cur["deleted"]:
                continue
            await purge_session(S, s["id"])
            purged += 1
        return {"purged": purged}

    # -------------------------------------------------------------- groups

    @api.get("/groups")
    async def list_groups() -> list[dict]:
        return store.groups()

    @api.post("/groups")
    async def create_group(body: dict = Body(...)) -> dict:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "A group needs a name")
        sids = body.get("session_ids") or []
        if not isinstance(sids, list) or not all(isinstance(i, str) for i in sids):
            raise HTTPException(400, "session_ids must be a list of session ids")
        g = store.create_group(name, body.get("color"))
        for sid in sids:  # "New group…" from Move to: create and move at once
            if store.get(sid):
                store.update(sid, group_id=g["id"])
        return g

    @api.post("/groups/reorder")
    async def reorder_groups(body: dict = Body(...)) -> list[dict]:
        store.reorder_groups([i for i in body.get("ids") or [] if isinstance(i, str)])
        return store.groups()

    @api.patch("/groups/{gid}")
    async def patch_group(gid: str, body: dict = Body(...)) -> dict:
        if not store.group(gid):
            raise HTTPException(404, "No such group")
        fields = {k: body[k] for k in ("name", "color", "collapsed", "sort_order") if k in body}
        if "sort_order" in fields:
            fields["sort_order"] = number_arg(fields["sort_order"], "sort_order")
        return store.update_group(gid, **fields)  # type: ignore[return-value]

    @api.delete("/groups/{gid}")
    async def delete_group(gid: str) -> dict:
        if not store.group(gid):
            raise HTTPException(404, "No such group")
        store.delete_group(gid)
        return {"ok": True}
