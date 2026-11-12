"""Event bus: every state change is an event, persisted to SQLite and pushed to all
connected WebSocket clients. Streaming deltas are pushed but not persisted (the final
message they build is)."""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any

from .db import DB

# Pushed live only; the durable result is stored as its own event. status.updated is a snapshot
# the Usage page re-reads from /api/status when it opens, so replaying old ones adds nothing.
# mcp.auto_enabled is a one-time notice (a toast); the change itself is a persisted session.updated.
# skills.loaded likewise: a skill entered the session's loaded set; session.updated carries the change.
EPHEMERAL = {"message.delta", "thinking.delta", "tool.input_delta", "job.log", "terminal.output", "status.updated",
             "mcp.auto_enabled", "skills.loaded"}
# The event log only serves replay to a window that briefly lost its connection: a (re)loaded UI
# reads everything from the REST API and continues from /api/state's last_seq. Older events go.
EVENT_RETENTION_DAYS = 7
# Ephemeral text streams a lagging client gets merged into one event: (data key naming the stream, text key).
COALESCE = {"message.delta": ("id", "text"), "thinking.delta": ("id", "text"), "job.log": ("id", "text"),
            "terminal.output": ("tab", "data")}
QUEUE_MAX = 5000
REPLAY_MAX = 5000  # a client further behind than this reloads its state (ws.resync) instead


class Subscriber:
    """One client's outgoing events. When it falls QUEUE_MAX events behind it is cut off: the queue
    is dropped and get() returns None, so the socket closes and the client reconnects with its last
    seq (replaying what it missed) instead of silently hanging on a dead queue."""

    def __init__(self, maxsize: int = QUEUE_MAX):
        self.items: deque[dict] = deque()
        self.maxsize = maxsize
        self.overflowed = False
        self.closed = False
        self._wake = asyncio.Event()

    def put(self, ev: dict) -> bool:
        if self.closed:
            return False
        if (spec := COALESCE.get(ev["type"])) and self.items:
            last = self.items[-1]  # still unsent: the client is behind, so merge instead of queueing more
            key, text = spec
            if (last["type"] == ev["type"] and last["session_id"] == ev["session_id"]
                    and last["data"].get(key) == ev["data"].get(key) and len(last["data"].get(text) or "") < 262_144):
                self.items[-1] = {**last, "data": {**last["data"], text: (last["data"].get(text) or "") + (
                    ev["data"].get(text) or "")}, "ts": ev["ts"]}
                return True
        if len(self.items) >= self.maxsize:
            self.items.clear()
            self.overflowed = True
            self.close()
            return False
        self.items.append(ev)
        self._wake.set()
        return True

    def close(self) -> None:
        self.closed = True
        self._wake.set()

    async def get(self) -> dict | None:
        """The next event, or None once closed (overflow or the client went away)."""
        while not self.items:
            if self.closed:
                return None
            self._wake.clear()
            await self._wake.wait()
        return self.items.popleft()

    def get_nowait(self) -> dict:
        if not self.items:
            raise asyncio.QueueEmpty
        return self.items.popleft()

    def qsize(self) -> int:
        return len(self.items)

    def empty(self) -> bool:
        return not self.items


class EventBus:
    def __init__(self, db: DB):
        self.db = db
        self._subs: set[Subscriber] = set()

    def publish(self, type: str, data: dict[str, Any] | None = None, session_id: str | None = None) -> dict:
        data = data or {}
        ev = {"type": type, "session_id": session_id, "data": data, "ts": time.time(), "seq": None}
        if type not in EPHEMERAL:
            ev["seq"] = self.db.insert("events", {"session_id": session_id, "type": type,
                                                  "data": json.dumps(data, default=str), "ts": ev["ts"]})
        for q in list(self._subs):
            if not q.put(ev) and q.closed:  # slow client: cut off; it reconnects and replays
                self._subs.discard(q)
        return ev

    def subscribe(self, maxsize: int = QUEUE_MAX) -> Subscriber:
        q = Subscriber(maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: Subscriber) -> None:
        self._subs.discard(q)
        q.close()

    def replay(self, since: int, session_id: str | None = None, limit: int = REPLAY_MAX) -> list[dict]:
        sql = "SELECT * FROM events WHERE seq > ?"
        params: list[Any] = [since]
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        rows = self.db.all(sql + " ORDER BY seq LIMIT ?", [*params, limit])
        return [{"seq": r["seq"], "type": r["type"], "session_id": r["session_id"],
                 "data": json.loads(r["data"]), "ts": r["ts"]} for r in rows]

    def last_seq(self) -> int:
        # sqlite_sequence too: seq keeps counting after old events are pruned (AUTOINCREMENT).
        r = self.db.one("SELECT MAX(COALESCE((SELECT MAX(seq) FROM events), 0), "
                        "COALESCE((SELECT seq FROM sqlite_sequence WHERE name='events'), 0)) AS s")
        return (r or {}).get("s") or 0

    def replay_gap(self, since: int) -> bool:
        """True when events after `since` were pruned, so a replay would leave the client stale."""
        if since <= 0:
            return False
        r = self.db.one("SELECT MIN(seq) AS s FROM events")
        first = (r or {}).get("s")
        return (first if first is not None else self.last_seq() + 1) > since + 1

    def prune(self, keep_days: float = EVENT_RETENTION_DAYS) -> int:
        """Delete events older than `keep_days`. Messages, jobs, items etc. live in their own tables,
        so nothing the UI shows depends on old events."""
        cur = self.db.execute("DELETE FROM events WHERE ts < ?", [time.time() - keep_days * 86400])
        return cur.rowcount or 0
