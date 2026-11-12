"""Sessions and messages."""
from __future__ import annotations

import contextlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from .config import Config
from .core.types import ContentBlock, Message, new_id
from .db import DB, now
from .events import EventBus

_blocks = TypeAdapter(list[ContentBlock])

SESSION_FIELDS = ("title", "pinned", "folder", "model", "effort", "account", "mode", "harness", "location", "status",
                  "group_id", "sort_order", "last_error")
# Settings that belong to one session only: provider resume ids, the scheduled task that made it,
# and where its title came from. Duplicates and forks don't copy them.
NOT_COPIED = ("agent_sdk_session", "codex_thread", "claude_code_session", "claude_code_totals", "claude_code_since",
              "claude_code_sent", "scheduled_task", "title_source")
MAX_CLEARS = 100  # /clear times kept in settings.cleared_at (for forks from before a clear)
GROUP_COLORS = ("gray", "blue", "teal", "green", "yellow", "orange", "red", "violet")
VIEWS = {  # GET /api/sessions?view=
    "active": "deleted_at IS NULL AND archived_at IS NULL",
    "archived": "deleted_at IS NULL AND archived_at IS NOT NULL",
    "trash": "deleted_at IS NOT NULL",
    "all": "1=1",
}
ORDER = "pinned DESC, CASE WHEN pinned THEN sort_order ELSE 0 END, COALESCE(activity_at, created_at) DESC"
SNIPPET_MARKS = ("\x02", "\x03")  # match start/end in search snippets (the UI highlights them; no HTML)


def valid_claude_code_session(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f-]{36}", value, re.I) is not None


def _claude_settings(settings: dict) -> dict:
    settings = dict(settings)
    if settings.get("claude_code_session") is not None and not valid_claude_code_session(settings["claude_code_session"]):
        settings.pop("claude_code_session")
    totals = settings.get("claude_code_totals")
    if isinstance(totals, dict) and totals.get("session_id") is not None and not valid_claude_code_session(totals["session_id"]):
        settings.pop("claude_code_totals")
    return settings


def _session_row(r: dict) -> dict:
    r = dict(r)
    r["settings"] = json.loads(r.get("settings") or "{}")
    r["pinned"] = bool(r["pinned"])
    r["archived"] = r.get("archived_at") is not None
    r["deleted"] = r.get("deleted_at") is not None
    r["unread"] = bool(r.get("activity_at")) and r["activity_at"] > (r.get("last_read_at") or 0)
    r["forked_from"] = json.loads(r["forked_from"]) if r.get("forked_from") else None
    return r


def _group_row(r: dict) -> dict:
    return {**r, "collapsed": bool(r["collapsed"])}


def fts_query(q: str) -> str | None:
    """User text → a safe FTS5 query: every word must appear; the last one may be a prefix."""
    words = re.findall(r"\w+", q, re.UNICODE)
    if not words:
        return None
    return " ".join(f'"{w}"' for w in words[:-1]) + (" " if len(words) > 1 else "") + f'"{words[-1]}"*'


def remove_claude_code_folder(sid: str) -> None:
    """Remove data_dir/claude_code/<sid>/, only if it resolves inside data_dir/claude_code."""
    from .config import data_dir

    root = (data_dir() / "claude_code").resolve()
    folder = (root / sid).resolve()
    if folder != root and folder.is_relative_to(root) and folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


class SessionStore:
    def __init__(self, db: DB, bus: EventBus, config: Config):
        self.db, self.bus, self.config = db, bus, config

    # ------------------------------------------------------------------ sessions

    def create(self, title: str = "New session", folder: str | None = None, model: str | None = None,
               effort: str | None = None, mode: str | None = None, **settings: Any) -> dict:
        settings = _claude_settings(settings)
        o = self.config.orchestrator
        global_skills = self.db.kv_get("skills_global", ["delegation"])
        if "skill_mode" not in settings:  # a caller choosing the mode brings its own skill settings
            settings = {**self.skill_disclosure_defaults(global_skills), **settings}
        row = {
            "id": new_id("ses_"), "title": title, "created_at": now(), "updated_at": now(), "pinned": 0,
            "folder": folder, "model": self.config.resolve(model or o.get("model", "claude-opus-5-5")),
            "effort": effort or o.get("effort", "medium"),
            "account": self.config.profiles("anthropic")[0],
            "mode": mode or self.config.modes.get("default", "ask"),
            "harness": "builtin", "location": "local",
            "settings": json.dumps({"skills": global_skills, "connectors": {},
                                   "shared_tools": False, "accounts": self.config.session_accounts(None),
                                   **settings}),
        }
        self.db.insert("sessions", row)
        s = self.get(row["id"])
        self.bus.publish("session.created", s, s["id"])
        return s

    def skill_disclosure_defaults(self, global_skills: list[str]) -> dict:
        """Skill-disclosure settings for a session created now ([skills] disclosure). Applied only
        at creation (every creator goes through create), so existing sessions keep what they had:
        a session without skill_mode is a legacy ("full") one."""
        if self.config.skills.get("disclosure") != "progressive":
            return {}
        from .skills import pinned_skill_names

        return {"skill_mode": "progressive", "pinned_skills": pinned_skill_names({"pinned_skills": global_skills}),
                "loaded_skills": []}

    def get(self, sid: str) -> dict | None:
        r = self.db.one("SELECT * FROM sessions WHERE id=?", [sid])
        return _session_row(r) if r else None

    def list(self, q: str | None = None, view: str = "active") -> list[dict]:
        """Sessions in sidebar order. `view`: active (default) | archived | trash | all."""
        sql, params = f"SELECT * FROM sessions WHERE ({VIEWS.get(view, VIEWS['active'])})", []
        if q:
            sql += " AND (title LIKE ? OR id IN (SELECT session_id FROM messages WHERE content LIKE ?))"
            params = [f"%{q}%", f"%{q}%"]
        return [_session_row(r) for r in self.db.all(f"{sql} ORDER BY {ORDER}", params)]

    def update(self, sid: str, **fields: Any) -> dict | None:
        cur = self.get(sid)
        if not cur:  # deleted meanwhile (e.g. a cancelled run finishing after a purge)
            return None
        upd = {k: v for k, v in fields.items() if k in SESSION_FIELDS}
        if "pinned" in upd:
            upd["pinned"] = int(bool(upd["pinned"]))
            if upd["pinned"] and not cur["pinned"] and "sort_order" not in upd:  # new pins go on top
                r = self.db.one("SELECT MIN(sort_order) AS m FROM sessions WHERE pinned=1")
                upd["sort_order"] = ((r or {}).get("m") or 0) - 1
        if "archived" in fields:
            upd["archived_at"] = (cur["archived_at"] or now()) if fields["archived"] else None
        if upd.get("model"):
            upd["model"] = self.config.resolve(upd["model"])
        if "settings" in fields or "accounts" in fields or "account" in upd:
            new = _claude_settings({**cur["settings"], **_claude_settings(fields.get("settings") or {})})
            # Profile choices per provider: merged, not replaced; `account` mirrors the Anthropic one.
            accounts = {**self.config.session_accounts(cur), **((fields.get("settings") or {}).get("accounts") or {}),
                        **(fields.get("accounts") or {})}
            if "account" in upd and "anthropic" not in (fields.get("accounts") or {}):
                accounts["anthropic"] = upd["account"]
            new["accounts"] = accounts
            upd["account"] = accounts["anthropic"]
            upd["settings"] = json.dumps(new)
        upd["updated_at"] = now()
        self.db.update("sessions", "id", sid, upd)
        return self._changed(sid)

    def _changed(self, sid: str) -> dict | None:
        s = self.get(sid)
        if s:
            self.bus.publish("session.updated", s, sid)
        return s

    def touch(self, sid: str) -> None:
        t = now()
        self.db.update("sessions", "id", sid, {"updated_at": t, "activity_at": t})

    def delete(self, sid: str) -> None:
        """Delete for good, with everything the session owns: its messages (cascade), events (which
        hold copies of its messages), file snapshots, jobs, approval cards, indexed items and the
        files the app stored for them (unless another session still uses one), subagent
        transcripts and its scratch folder. Usage records stay for My usage. Worktrees are removed
        by the caller (worktrees.cleanup_session)."""
        from .config import data_dir, media_dir, sessions_dir

        db = self.db
        job_rows = db.all("SELECT id, meta FROM jobs WHERE session_id=?", [sid])
        subs = {json.loads(r["meta"] or "{}").get("subagent") for r in job_rows}
        paths = {r["path"] for r in db.all("SELECT DISTINCT path FROM items WHERE session_id=? AND path IS NOT NULL",
                                           [sid])}
        # Files its messages point at: converted copies sent instead of the original (uploads/<id>/send/,
        # converted/), images in tool results, … Only those under the media dir are candidates below.
        for r in db.all("SELECT content FROM messages WHERE session_id=?", [sid]):
            with contextlib.suppress(ValueError, TypeError):
                paths |= _paths_in(json.loads(r["content"]))
        db.execute("DELETE FROM sessions WHERE id=?", [sid])
        db.execute("DELETE FROM kv WHERE key=?", [f"gallery:{sid}"])
        for table in ("events", "snapshots", "jobs", "approvals", "items"):
            db.execute(f"DELETE FROM {table} WHERE session_id=?", [sid])
        media_raw = media_dir()
        media = media_raw.resolve()
        upload_dirs: set[str] = set()
        for p in paths:
            f = Path(p).resolve()
            if not f.is_relative_to(media) or f == media:
                continue  # the user's own folders are never touched
            rel = f.relative_to(media).parts
            if rel[0] == "uploads" and len(rel) >= 3:  # uploads/<id>/…: the per-upload folder, handled whole
                upload_dirs.add(rel[1])
                continue
            if not self._file_in_use(p) and f.is_file():  # shared files stay
                f.unlink(missing_ok=True)
        for uid in upload_dirs:
            d = media / "uploads" / uid
            if Path(uid).name != uid or d.parent != media / "uploads" or not d.is_dir():
                continue
            if any(self._prefix_in_use(f"{base}/") for base in {str(d), str(media_raw / "uploads" / uid)}):
                continue  # another session (a duplicate or fork) still shows something from it
            shutil.rmtree(d, ignore_errors=True)
        tdir = data_dir() / "subagents"
        for sub in subs:
            if isinstance(sub, str) and sub and Path(sub).name == sub:
                (tdir / f"{sub}.json").unlink(missing_ok=True)
        jdir = data_dir() / "jobs"  # command output logs (full command output)
        for r in job_rows:
            jid = r["id"]
            if isinstance(jid, str) and jid and Path(jid).name == jid:
                (jdir / f"{jid}.log").unlink(missing_ok=True)
        if Path(sid).name == sid and sid:
            shutil.rmtree(sessions_dir() / sid, ignore_errors=True)
        remove_claude_code_folder(sid)
        self.bus.publish("session.deleted", {"id": sid}, sid)

    def _file_in_use(self, path: str) -> bool:
        """Another item, or a message of another session (duplicates and forks copy messages), refers to it."""
        if self.db.one("SELECT 1 FROM items WHERE path=? LIMIT 1", [path]):
            return True
        needle = json.dumps(path)[1:-1]  # as the path appears inside a message's JSON content
        return bool(self.db.one("SELECT 1 FROM messages WHERE instr(content, ?) > 0 LIMIT 1", [needle]))

    def _prefix_in_use(self, prefix: str) -> bool:
        """An item or message (of a session still there) refers to a file under folder `prefix` (ends in /)."""
        if self.db.one("SELECT 1 FROM items WHERE substr(path, 1, ?) = ? LIMIT 1", [len(prefix), prefix]):
            return True
        needle = json.dumps(prefix)[1:-1]
        return bool(self.db.one("SELECT 1 FROM messages WHERE instr(content, ?) > 0 LIMIT 1", [needle]))

    purge = delete

    # ------------------------------------------------------------- trash/read

    def trash(self, sid: str) -> dict | None:
        """Move to Trash (the caller stops the run first). Restorable until purged."""
        self.db.execute("UPDATE sessions SET deleted_at=? WHERE id=? AND deleted_at IS NULL", [now(), sid])
        return self._changed(sid)

    def restore(self, sid: str) -> dict | None:
        self.db.execute("UPDATE sessions SET deleted_at=NULL WHERE id=?", [sid])
        return self._changed(sid)

    def purge_expired(self, days: float = 30) -> list[str]:
        """Empty Trash of sessions deleted more than `days` ago."""
        ids = [r["id"] for r in self.db.all("SELECT id FROM sessions WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                                             [now() - days * 86400])]
        for sid in ids:
            self.delete(sid)
        return ids

    def mark_read(self, sid: str, publish: bool = True) -> dict | None:
        self.db.execute("UPDATE sessions SET last_read_at=? WHERE id=?", [now(), sid])
        return self._changed(sid) if publish else self.get(sid)

    def mark_unread(self, sid: str) -> dict | None:
        self.db.execute("UPDATE sessions SET activity_at=COALESCE(activity_at, created_at), last_read_at=0 "
                        "WHERE id=?", [sid])
        return self._changed(sid)

    def reorder(self, ids: list[str]) -> None:
        """Manual order (pinned sessions): position in `ids`."""
        for i, sid in enumerate(ids):
            self.db.execute("UPDATE sessions SET sort_order=? WHERE id=?", [i, sid])
            self._changed(sid)

    # ------------------------------------------------------- duplicate/fork

    def duplicate(self, sid: str, upto: str | None = None, title: str | None = None,
                  forked_from: dict | None = None) -> dict:
        """A new session with this one's settings and messages (all of them, or up to and including
        message `upto`). Provider resume ids aren't copied: the copy starts its own provider thread
        (the agent_sdk/codex_cli harnesses then recap the copied history). A full copy keeps every
        message's compacted flag; a fork hides what the model didn't see at `upto` (_visible_at_fork)."""
        src = self.get(sid)
        if not src:
            raise KeyError(sid)
        rows = self.db.all("SELECT * FROM messages WHERE session_id=? ORDER BY created_at, rowid", [sid])
        settings = {k: v for k, v in src["settings"].items() if k not in NOT_COPIED}
        hidden = [r["compacted"] for r in rows]
        if upto is not None:
            idx = next((i for i, r in enumerate(rows) if r["id"] == upto), None)
            if idx is None:
                raise KeyError(upto)
            cut = idx + 1
            # Keep the tool results that answer the last message's tool calls (hidden in the UI).
            if cut < len(rows) and rows[idx]["role"] == "assistant" and json.loads(rows[cut]["meta"] or "{}").get(
                    "tool_results"):
                cut += 1
            rows = rows[:cut]
            end = rows[-1]["created_at"]
            # Compactions and /clears made after that message don't apply to the fork.
            clears = [c for c in _clears(settings) if c <= end]
            if "cleared_at" in settings:
                settings["cleared_at"] = clears
            hidden = _visible_at_fork(rows, max(clears) if clears else None)
        t = now()
        new = {k: src[k] for k in ("folder", "model", "effort", "account", "mode", "harness", "location", "group_id")}
        settings["title_source"] = "copy"
        new.update({
            "id": new_id("ses_"), "title": title or f"{src['title']} (copy)", "created_at": t, "updated_at": t,
            "pinned": 0, "settings": json.dumps(settings), "status": "idle",
            "activity_at": t if rows else None, "last_read_at": t,
            "forked_from": json.dumps(forked_from) if forked_from else None,
        })
        self.db.insert("sessions", new)
        self.db.executemany(
            "INSERT INTO messages (id, session_id, role, content, meta, created_at, compacted) VALUES (?,?,?,?,?,?,?)",
            [[new_id("msg_"), new["id"], r["role"], r["content"], r["meta"], r["created_at"], h]
             for r, h in zip(rows, hidden)])
        s = self.get(new["id"])
        self.bus.publish("session.created", s, s["id"])
        return s

    def fork(self, sid: str, message_id: str) -> dict:
        src = self.get(sid)
        if not src:
            raise KeyError(sid)
        return self.duplicate(sid, upto=message_id, title=f"{src['title']} (fork)",
                              forked_from={"session_id": sid, "message_id": message_id, "title": src["title"]})

    # ---------------------------------------------------------------- search

    def search(self, q: str, limit: int = 30) -> list[dict]:
        """Sessions (not in Trash) whose title or message text matches: title hits first, then
        message hits (best message per session, with a snippet whose match is wrapped in
        SNIPPET_MARKS)."""
        q = q.strip()
        if not q:
            return []
        out: list[dict] = []
        for r in self.db.all("SELECT id, title, archived_at FROM sessions WHERE deleted_at IS NULL AND title LIKE ? "
                             "ORDER BY COALESCE(activity_at, created_at) DESC LIMIT ?", [f"%{q}%", limit]):
            out.append({"session_id": r["id"], "title": r["title"], "archived": r["archived_at"] is not None,
                        "match": "title", "message_id": None, "snippet": None})
        seen: set[str] = set()
        hits: list[dict] = []
        fq = fts_query(q)
        rows: list[dict] = []
        try:
            if fq:
                rows = self.db.all(
                    "SELECT f.session_id, f.message_id, snippet(messages_fts, 0, ?, ?, '…', 14) AS snippet, "
                    "s.title, s.archived_at FROM messages_fts f JOIN sessions s ON s.id = f.session_id "
                    "WHERE messages_fts MATCH ? AND s.deleted_at IS NULL ORDER BY bm25(messages_fts) LIMIT 400",
                    [*SNIPPET_MARKS, fq])
        except Exception:  # noqa: BLE001 — no FTS5 or a query it can't parse: a bounded LIKE instead
            rows = self.db.all(
                "SELECT m.session_id, m.id AS message_id, NULL AS snippet, s.title, s.archived_at FROM messages m "
                "JOIN sessions s ON s.id = m.session_id WHERE m.content LIKE ? AND s.deleted_at IS NULL "
                "ORDER BY m.created_at DESC LIMIT 400", [f"%{q}%"])
        for r in rows:
            if r["session_id"] in seen:
                continue
            seen.add(r["session_id"])
            hits.append({"session_id": r["session_id"], "title": r["title"], "archived": r["archived_at"] is not None,
                         "match": "message", "message_id": r["message_id"], "snippet": r["snippet"]})
            if len(hits) >= limit:
                break
        return out + hits

    # ---------------------------------------------------------------- groups

    def groups(self) -> list[dict]:
        return [_group_row(r) for r in self.db.all("SELECT * FROM session_groups ORDER BY sort_order, created_at")]

    def group(self, gid: str) -> dict | None:
        r = self.db.one("SELECT * FROM session_groups WHERE id=?", [gid])
        return _group_row(r) if r else None

    def _groups_changed(self) -> None:
        self.bus.publish("groups.updated", {"groups": self.groups()})

    def create_group(self, name: str, color: str | None = None) -> dict:
        n = self.db.one("SELECT COUNT(*) AS n, MAX(sort_order) AS m FROM session_groups") or {}
        color = color if color in GROUP_COLORS else GROUP_COLORS[1 + (n.get("n") or 0) % (len(GROUP_COLORS) - 1)]
        gid = new_id("grp_")
        self.db.insert("session_groups", {"id": gid, "name": name.strip()[:80] or "Group", "color": color,
                                          "sort_order": (n.get("m") or 0) + 1, "collapsed": 0, "created_at": now()})
        self._groups_changed()
        return self.group(gid)  # type: ignore[return-value]

    def update_group(self, gid: str, **f: Any) -> dict | None:
        upd: dict[str, Any] = {}
        if f.get("name") is not None and str(f["name"]).strip():
            upd["name"] = str(f["name"]).strip()[:80]
        if f.get("color") in GROUP_COLORS:
            upd["color"] = f["color"]
        if "collapsed" in f:
            upd["collapsed"] = int(bool(f["collapsed"]))
        if "sort_order" in f:
            upd["sort_order"] = float(f["sort_order"])
        self.db.update("session_groups", "id", gid, upd)
        self._groups_changed()
        return self.group(gid)

    def delete_group(self, gid: str) -> None:
        """Remove a group; its sessions become ungrouped (never deleted)."""
        ids = [r["id"] for r in self.db.all("SELECT id FROM sessions WHERE group_id=?", [gid])]
        self.db.execute("UPDATE sessions SET group_id=NULL WHERE group_id=?", [gid])
        self.db.execute("DELETE FROM session_groups WHERE id=?", [gid])
        for sid in ids:
            self._changed(sid)
        self._groups_changed()

    def reorder_groups(self, ids: list[str]) -> None:
        for i, gid in enumerate(ids):
            self.db.execute("UPDATE session_groups SET sort_order=? WHERE id=?", [i, gid])
        self._groups_changed()

    # ------------------------------------------------------------------ messages

    def add_message(self, sid: str, msg: Message, created_at: float | None = None) -> Message:
        self.db.insert("messages", {
            "id": msg.id, "session_id": sid, "role": msg.role,
            "content": json.dumps([b.model_dump(exclude_none=True) for b in msg.content]),
            "meta": json.dumps({k: v for k, v in msg.meta.items() if k not in ("created_at", "compacted")},
                               default=str),
            "created_at": created_at or now(),
        })
        self.touch(sid)
        self.bus.publish("message.created", {"message": self.message_dict(msg)}, sid)
        return msg

    def replace_content(self, sid: str, mid: str, msg: Message) -> None:
        self.db.update("messages", "id", mid, {
            "content": json.dumps([b.model_dump(exclude_none=True) for b in msg.content]),
            "meta": json.dumps(msg.meta, default=str)})
        self.bus.publish("message.updated", {"message": self.message_dict(msg)}, sid)

    @staticmethod
    def message_dict(msg: Message) -> dict:
        return {"id": msg.id, "role": msg.role, "meta": msg.meta,
                "content": [_strip_heavy(b.model_dump(exclude_none=True)) for b in msg.content]}

    def _row_to_message(self, r: dict) -> Message:
        return Message(id=r["id"], role=r["role"], content=_blocks.validate_python(json.loads(r["content"])),
                       meta={**json.loads(r["meta"]), "created_at": r["created_at"], "compacted": bool(r["compacted"])})

    def messages(self, sid: str, *, include_compacted: bool = True) -> list[Message]:
        sql = "SELECT * FROM messages WHERE session_id=?"
        if not include_compacted:
            sql += " AND compacted=0"
        return [self._row_to_message(r) for r in self.db.all(sql + " ORDER BY created_at, rowid", [sid])]

    def messages_page(self, sid: str, before: str | None = None, limit: int = 200,
                      include_compacted: bool = False) -> dict:
        """The newest `limit` messages (older than message `before`, when given), oldest first, plus
        whether older ones exist and how many messages are compacted. Long sessions open fast and
        the UI loads older pages on scroll-up."""
        where, params = "session_id=?", [sid]
        if not include_compacted:
            where += " AND compacted=0"
        if before:
            ref = self.db.one("SELECT created_at, rowid FROM messages WHERE id=? AND session_id=?", [before, sid])
            if ref:
                where += " AND (created_at < ? OR (created_at = ? AND rowid < ?))"
                params += [ref["created_at"], ref["created_at"], ref["rowid"]]
        rows = self.db.all(f"SELECT rowid, * FROM messages WHERE {where} ORDER BY created_at DESC, rowid DESC LIMIT ?",
                           [*params, max(1, limit) + 1])
        has_more = len(rows) > limit
        rows = rows[:limit][::-1]
        hidden = (self.db.one("SELECT COUNT(*) n FROM messages WHERE session_id=? AND compacted=1", [sid])
                  or {}).get("n", 0)  # always: the UI's show/hide toggle needs it either way
        return {"messages": [self._row_to_message(r) for r in rows], "has_more": has_more, "compacted": hidden}

    def repair_dangling_tool_calls(self, sid: str) -> int:
        """If a run was stopped or the app quit mid-tool, close every unanswered tool call
        with an 'interrupted' result so the next request is valid."""
        from .core.types import ToolResultBlock

        msgs = self.messages(sid, include_compacted=False)
        answered = {b.tool_use_id for m in msgs for b in m.content if isinstance(b, ToolResultBlock)}
        missing = [c.id for m in msgs if m.role == "assistant" for c in m.tool_calls() if c.id not in answered]
        if missing:
            self.add_message(sid, Message(role="user", meta={"tool_results": True, "repaired": True}, content=[
                ToolResultBlock.text(i, "Interrupted: the run was stopped before this tool finished.", is_error=True)
                for i in missing]))
        return len(missing)

    def mark_compacted(self, ids: list[str]) -> None:
        self.db.executemany("UPDATE messages SET compacted=1 WHERE id=?", [[i] for i in ids])

    def clear(self, sid: str) -> None:
        """/clear: hide all history from the model (kept for the record). The time is kept in
        settings.cleared_at, so a fork from before it can show the model what it saw then."""
        t = now()
        self.db.execute("UPDATE messages SET compacted=1 WHERE session_id=?", [sid])
        if cur := self.get(sid):
            clears = [*_clears(cur["settings"]), t][-MAX_CLEARS:]
            self.db.update("sessions", "id", sid, {"settings": json.dumps({**cur["settings"], "cleared_at": clears})})
        self.bus.publish("session.cleared", {"id": sid}, sid)


def _paths_in(blocks: Any) -> set[str]:
    """Every `path` of the content blocks (tool results' nested blocks included)."""
    out: set[str] = set()
    if isinstance(blocks, list):
        for b in blocks:
            if isinstance(b, dict):
                if isinstance(b.get("path"), str) and b["path"]:
                    out.add(b["path"])
                out |= _paths_in(b.get("content"))
    return out


def _clears(settings: dict) -> list[float]:
    v = settings.get("cleared_at")
    return [c for c in v if isinstance(c, (int, float)) and not isinstance(c, bool)] if isinstance(v, list) else []


def _visible_at_fork(rows: list[dict], cleared: float | None) -> list[int]:
    """`compacted` flags for a fork's copied rows, as the model saw them at the last one: rows before
    the latest /clear up to then are hidden; after it, the last compaction summary (if any) and
    everything after it are visible, and what it summarized stays hidden. Compactions and clears
    done later (which would leave the fork without visible history) are ignored."""
    start = 0
    if cleared is not None:
        start = next((i for i, r in enumerate(rows) if r["created_at"] >= cleared), len(rows))
    for i in range(len(rows) - 1, -1, -1):
        # A summary sits just before the turns it kept (0.5 ms earlier), so allow it a little slack.
        if json.loads(rows[i]["meta"] or "{}").get("summary") and (cleared is None
                                                                   or rows[i]["created_at"] >= cleared - 0.01):
            start = i
            break
    return [int(i < start) for i in range(len(rows))]


def _strip_heavy(b: dict) -> dict:
    """Don't push base64 media over the WebSocket; the UI loads it by item/path."""
    if "data" in b and b.get("type") in ("image", "audio", "file"):
        b = {**b, "data": None, "has_data": True}
    if b.get("type") == "tool_result":
        b = {**b, "content": [_strip_heavy(c) for c in b.get("content", [])]}
    return b
