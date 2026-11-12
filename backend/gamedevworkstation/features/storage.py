"""Storage: what the app keeps on disk, daily maintenance and on-demand compaction.

Daily (and at startup): events older than [sessions] event_retention_days (7) are pruned and
the database gives its free pages back (`PRAGMA incremental_vacuum`; new databases are created
with auto_vacuum=INCREMENTAL, older ones switch at the first full VACUUM). Settings → Storage
shows the sizes and runs a full VACUUM on demand.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI

from ..config import data_dir, logs_dir, media_dir
from ..events import EVENT_RETENTION_DAYS

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)
DAY_S = 86400
LAST_RUN_KEY = "storage.maintenance_at"


def dir_size(p: Path) -> int:
    """Bytes of the regular files under `p` (symlinks not followed)."""
    total = 0
    if not p.exists():
        return 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                st = os.lstat(os.path.join(root, f))
            except OSError:
                continue
            total += st.st_size
    return total


def _file_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


class Storage:
    def __init__(self, app: "AppState"):
        self.app = app
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def retention_days(self) -> float:
        try:
            return max(float(self.app.config.sessions.get("event_retention_days", EVENT_RETENTION_DAYS)), 1.0)
        except (TypeError, ValueError):
            return float(EVENT_RETENTION_DAYS)

    def maintain(self) -> dict:
        """Prune old events and give free pages back to the filesystem. Quick; runs daily."""
        pruned = self.app.bus.prune(self.retention_days())
        self.app.db.incremental_vacuum()
        self.app.db.kv_set(LAST_RUN_KEY, time.time())
        if pruned:
            log.info("storage maintenance: pruned %s old events", pruned)
        return {"pruned_events": pruned}

    def compact(self) -> dict:
        """maintain() plus a full VACUUM, which rewrites the database file at its smallest."""
        before = self.db_bytes()
        res = self.maintain()
        self.app.db.vacuum()
        return {**res, "freed_bytes": max(before - self.db_bytes(), 0)}

    def db_bytes(self) -> int:
        p = Path(self.app.db.path)
        return sum(_file_size(Path(f"{p}{suffix}")) for suffix in ("", "-wal", "-shm"))

    def usage(self) -> dict:
        db = self.app.db
        snap = db.one("SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(content)), 0) AS b, "
                      "COALESCE(SUM(too_large), 0) AS big FROM snapshots") or {}
        ev = db.one("SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(data)), 0) AS b FROM events") or {}
        root = data_dir()
        return {
            # free_bytes: empty pages (freelist_count * page_size) plus the write-ahead log, which a
            # checkpoint folds back. Half-empty pages aren't counted (SQLite can't report them cheaply),
            # so Compact can free more than this: the page shows it as a lower bound.
            "database": {"path": db.path, "bytes": self.db_bytes(),
                         "free_bytes": db.free_bytes() + _file_size(Path(f"{db.path}-wal")),
                         "auto_vacuum": db.auto_vacuum_mode(), "schema_version": db.user_version()},
            "events": {"count": ev.get("n", 0), "bytes": ev.get("b", 0), "retention_days": self.retention_days()},
            "snapshots": {"count": snap.get("n", 0), "bytes": snap.get("b", 0), "too_large": snap.get("big", 0)},
            "media": {"path": str(media_dir()), "bytes": dir_size(media_dir())},
            "transcripts": {"path": str(root / "subagents"), "bytes": dir_size(root / "subagents")},
            "logs": {"path": str(logs_dir()), "bytes": dir_size(logs_dir())},
            "last_maintenance": db.kv_get(LAST_RUN_KEY),
        }

    async def run_maintenance(self) -> dict:
        async with self._lock:
            return await asyncio.to_thread(self.maintain)

    async def run_compact(self) -> dict:
        async with self._lock:
            return await asyncio.to_thread(self.compact)

    async def astart(self) -> None:
        async def loop() -> None:
            while True:
                last = self.app.db.kv_get(LAST_RUN_KEY) or 0
                wait = max(0.0, last + DAY_S - time.time())
                if wait:
                    await asyncio.sleep(min(wait, DAY_S))
                    continue
                try:
                    await self.run_maintenance()
                except Exception:  # noqa: BLE001 — never take the app down over housekeeping
                    log.exception("storage maintenance failed")
                    await asyncio.sleep(3600)

        self._task = asyncio.create_task(loop())

    async def aclose(self) -> None:
        if self._task:
            self._task.cancel()


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    storage = Storage(S)
    S.extensions["storage"] = storage

    @api.get("/storage")
    async def get_storage() -> dict:
        return await asyncio.to_thread(storage.usage)

    @api.post("/storage/compact")
    async def compact() -> dict:
        """Prune old events and VACUUM the database now (Settings → Storage)."""
        res = await storage.run_compact()
        return {**res, "usage": await asyncio.to_thread(storage.usage)}
