"""Media a command produced, indexed as items so the viewer can show or play it inline.

A `run_command` whose output has lines `TRAILER_OUTPUT: <path>` (trailer-maker's scripts) or
`ARTIFACT: <path>` (any script) gets each such file indexed as an item when it:
- resolves inside the session folder or its worktrees (relative paths: against the session folder),
- exists, and
- is an image, video or audio file by MIME type.
At most MAX_PER_CALL files per command. One item per (session, path): an unchanged file is left alone, and a
re-render of the same path updates that item (size, stamp, time) instead of adding a duplicate.

The file checks and item lookups run in a worker thread (asyncio.to_thread, as the quality ladder does); items are
added / updated and events published back on the event loop.

Hook: post_tool `media.outputs` (order 30, after ladder.observe), fail open.
"""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, FastAPI

from ..db import now
from .hookbus import HookEvent, HookResult

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)

HOOK = "media.outputs"
MAX_PER_CALL = 20
RE_LINE = re.compile(r"^\s*(?:TRAILER_OUTPUT|ARTIFACT):\s*(.+?)\s*$", re.M)
_UNTRUSTED = re.compile(r'<untrusted-[0-9a-f]{8} source="[^"]*">\n(.*?)\n</untrusted-[0-9a-f]{8}>', re.S)


def media_paths(text: str) -> list[str]:
    """The paths announced in a command's output, in order, without duplicates."""
    m = _UNTRUSTED.search(text or "")
    body = m.group(1) if m else (text or "")
    seen: dict[str, None] = {}
    for raw in RE_LINE.findall(body):
        seen.setdefault(raw.strip().strip("'\""), None)
    return list(seen)


def _mime(p: Path) -> str | None:
    mime = mimetypes.guess_type(p.name)[0]
    return mime if mime and mime.split("/")[0] in ("image", "video", "audio") else None


def _meta(raw: Any) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


class MediaOutputs:
    def __init__(self, app: "AppState"):
        self.app = app

    async def observe(self, ev: HookEvent) -> HookResult | None:
        out, ctx = ev.output, ev.ctx
        if out is None or not ctx.folder or not out.text.startswith("exit code "):
            return None
        paths = media_paths(out.text)
        if not paths:
            return None
        try:
            plans = await asyncio.to_thread(self._plan, ctx, paths[:MAX_PER_CALL])
        except Exception:  # noqa: BLE001  (fail open)
            log.info("media_out: couldn't check %s", paths[:3], exc_info=True)
            return None
        added: list[str] = []
        for plan in plans:
            if self._apply(ctx, plan):
                added.append(plan["path"].name)
        if not added:
            return None
        return HookResult(action="note", note="[Media] indexed as items: " + ", ".join(added))

    def _plan(self, ctx, paths: list[str]) -> list[dict]:
        """Blocking part (worker thread): resolve, stat and classify the files, find their existing items.
        Returns one plan per file to add ({"item_id": None}) or update ({"item_id": id}); unchanged files are left out."""
        plans: list[dict] = []
        for raw in paths:
            q = Path(raw).expanduser()
            try:
                p = (q if q.is_absolute() else Path(ctx.folder) / q).resolve()
                if not p.is_file() or not ctx.within_roots(p):
                    continue
                st = p.stat()
            except OSError:
                continue
            mime = _mime(p)
            if not mime:
                continue
            stamp = f"{st.st_size}:{int(st.st_mtime)}"
            rows = self.app.db.all("SELECT id, meta FROM items WHERE session_id=? AND path=? AND deleted=0 "
                                   "ORDER BY created_at DESC", [ctx.session_id, str(p)])
            if any(_meta(r["meta"]).get("stamp") == stamp for r in rows):
                continue  # unchanged since it was indexed
            plans.append({"path": p, "mime": mime, "stamp": stamp, "size": st.st_size,
                          "item_id": rows[0]["id"] if rows else None, "meta": _meta(rows[0]["meta"]) if rows else {}})
        return plans

    def _apply(self, ctx, plan: dict) -> str | None:
        """Event-loop part: add the item, or update the existing one in place (a re-render of the same path)."""
        meta = {**plan["meta"], "stamp": plan["stamp"], "from": "run_command", "mime": plan["mime"]}
        try:
            if plan["item_id"]:
                iid = plan["item_id"]
                self.app.db.update("items", "id", iid, {"size": plan["size"], "meta": meta, "created_at": now(),
                                                        "message_id": ctx.message_id, "provider": ctx.provider,
                                                        "model": ctx.model})
                self.app.bus.publish("item.updated", self.app.items.get(iid), ctx.session_id)
                return iid
            return self.app.items.add_file(plan["path"], source="tool", session_id=ctx.session_id,
                                           provider=ctx.provider, model=ctx.model, message_id=ctx.message_id,
                                           title=plan["path"].name, extracted_text="", meta=meta)
        except Exception:  # noqa: BLE001  (fail open: indexing never breaks a turn)
            log.info("media_out: couldn't index %s", plan["path"], exc_info=True)
            return None


def install(app: "AppState") -> MediaOutputs:
    """Register the observer (idempotent). register() calls this; tests call it on a bare AppState."""
    mo = app.extensions.get("media_out")
    if isinstance(mo, MediaOutputs):
        return mo
    mo = MediaOutputs(app)
    app.extensions["media_out"] = mo
    app.hooks.register("post_tool", HOOK, mo.observe, order=30, when=lambda ev: ev.tool == "run_command")
    return mo


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    install(S)
