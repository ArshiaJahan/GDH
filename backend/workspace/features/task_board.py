"""Task board: a Kanban board the user and the agent share.

Boards have ordered columns (the default "Game" board: Backlog, To do, In progress, Review and the
done column Done). Every task gets a code from one global counter, Task00001, Task00002, … (five
digits, more once it passes 99999), handed out inside a write transaction and never reused, even
after the task is deleted. Anything that takes a task (REST, tools, /task commands) accepts the
code in any case, the bare number ("1", "00001", "#1") or the internal id.

Tasks carry a Markdown description, priority, labels, a due date, assignees ("me" is the user,
"agent" the agent, any other name as typed), linked sessions, subtasks with checklists, comments
and an activity history. Archiving moves a task to "Recently deleted", where it can be restored.

The user works on the Tasks page and with /task in the composer; the agent with the task_* tools
(read tools for subagents too; Plan only mode leaves the board read-only). Every change is
published as a task.* event so open windows update at once.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException

from ..agent.tools import Tool, ToolContext, ToolDenied, ToolOutput, obj
from ..core.types import Message, TextBlock, ToolSpec, new_id

if TYPE_CHECKING:
    from ..app import AppState

PRIORITIES = ["none", "low", "medium", "high", "urgent"]
DUE_FILTERS = ["overdue", "today", "week", "none"]
ME, AGENT = "me", "agent"
TITLE_MAX = 300
DESCRIPTION_MAX = 20_000
COMMENT_MAX = 20_000
MAX_SUBTASKS = 50
MAX_ITEMS = 50
MAX_OPS = 100
MAX_LABELS = 20
ACTIVITY_SHOWN = 30
DEFAULT_COLUMNS = [("Backlog", False), ("To do", False), ("In progress", False), ("Review", False), ("Done", True)]
SUBTASK_OPS = ["add", "rename", "toggle", "move", "remove",
               "add_item", "rename_item", "toggle_item", "move_item", "remove_item"]

# "Task00001", "task1", "TASK-7", "#1", "#Task00001", "00001", "1"
_CODE = re.compile(r"^\s*#?\s*(?:task\s*[-_ ]?\s*)?0*(\d{1,12})\s*$", re.I)
# A code inside free text (chat messages): Task + at least five digits.
MENTION = re.compile(r"(?<![A-Za-z0-9_])task(\d{5,})(?![A-Za-z0-9_])", re.I)

# One line for the main agent's system prompt (fixed per session, so the prompt stays cached).
PROMPT_NOTE = ("Task board: the app has a Kanban board the user also uses. Tasks have codes like Task00042; "
               "refer to tasks by code, and when the user mentions one, look it up with task_get.")


class TaskError(ValueError):
    status = 400


class NotFound(TaskError):
    status = 404


def format_code(num: int) -> str:
    return f"Task{int(num):05d}"


def parse_code(ref: Any) -> int | None:
    """The number in a task reference ("Task00012", "task12", "#12", "00012", "12"), or None."""
    if isinstance(ref, bool):
        return None
    if isinstance(ref, int):
        return ref if ref > 0 else None
    m = _CODE.match(str(ref or ""))
    n = int(m.group(1)) if m else 0
    return n or None


def mentioned_codes(text: str) -> list[str]:
    """Task codes mentioned in free text, normalised and in order of first mention."""
    out: list[str] = []
    for m in MENTION.finditer(text or ""):
        c = format_code(int(m.group(1)))
        if int(m.group(1)) > 0 and c not in out:
            out.append(c)
    return out


def _norm(name: str) -> str:
    return re.sub(r"[\W_]+", "", (name or "").lower())


def _today() -> dt.date:
    return dt.date.today()


def _fmt_ts(ts: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else ""


def _title(v: Any, what: str = "Title") -> str:
    t = re.sub(r"\s+", " ", str(v or "")).strip()
    if not t:
        raise TaskError(f"{what} can't be empty.")
    if len(t) > TITLE_MAX:
        raise TaskError(f"{what} is longer than {TITLE_MAX} characters.")
    return t


def _str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = v.split(",")
    if not isinstance(v, (list, tuple)):
        raise TaskError("Expected a list of names.")
    return [str(x).strip() for x in v if str(x).strip()]


def norm_labels(v: Any) -> list[str]:
    out: list[str] = []
    for x in _str_list(v):
        x = x.lstrip("#").strip()[:40]
        if x and x.lower() not in {o.lower() for o in out}:
            out.append(x)
    if len(out) > MAX_LABELS:
        raise TaskError(f"At most {MAX_LABELS} labels.")
    return out


def norm_assignee(x: str) -> str:
    x = str(x).strip().lstrip("@").strip()[:60]
    low = x.lower()
    if low in ("me", "user", "you", "i", "myself"):
        return ME
    if low in ("agent", "the agent", "claude", "assistant", "ai"):
        return AGENT
    return x


def norm_assignees(v: Any) -> list[str]:
    out: list[str] = []
    for x in _str_list(v):
        a = norm_assignee(x)
        if a and a.lower() not in {o.lower() for o in out}:
            out.append(a)
    if len(out) > 20:
        raise TaskError("At most 20 assignees.")
    return out


def norm_priority(v: Any) -> str:
    p = str(v or "none").strip().lower()
    if p not in PRIORITIES:
        raise TaskError(f'Priority "{v}" not understood; use one of {", ".join(PRIORITIES)}.')
    return p


def norm_due(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if not s or s in ("none", "null", "no date"):
        return None
    if s == "today":
        return _today().isoformat()
    if s == "tomorrow":
        return (_today() + dt.timedelta(days=1)).isoformat()
    try:
        return dt.date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        raise TaskError(f'Due date "{v}" not understood; use YYYY-MM-DD.') from None


_SELECT = """SELECT t.*, c.name AS column_name, c.is_done AS is_done, c.sort_order AS col_order,
  b.name AS board_name,
  (SELECT COUNT(*) FROM task_subtasks s WHERE s.task_id = t.id) AS st_total,
  (SELECT COUNT(*) FROM task_subtasks s WHERE s.task_id = t.id AND s.done = 1) AS st_done,
  (SELECT COUNT(*) FROM task_comments m WHERE m.task_id = t.id) AS n_comments,
  (SELECT COUNT(*) FROM task_sessions x WHERE x.task_id = t.id) AS n_sessions
FROM board_tasks t JOIN task_columns c ON c.id = t.column_id JOIN task_boards b ON b.id = t.board_id"""


def _like(word: str) -> str:
    return "%" + word.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class TaskBoard:
    def __init__(self, app: "AppState"):
        self.app = app
        self.db = app.db

    # ------------------------------------------------------------------ boards & columns

    def boards(self) -> list[dict]:
        bs = self.db.all("SELECT * FROM task_boards ORDER BY sort_order, created_at")
        if not bs:
            self._seed()
            bs = self.db.all("SELECT * FROM task_boards ORDER BY sort_order, created_at")
        cols = self.db.all("SELECT c.*, (SELECT COUNT(*) FROM board_tasks t WHERE t.column_id = c.id "
                           "AND t.archived_at IS NULL) AS count FROM task_columns c ORDER BY sort_order, created_at")
        for b in bs:
            b["columns"] = [{**c, "is_done": bool(c["is_done"])} for c in cols if c["board_id"] == b["id"]]
        return bs

    def people(self) -> list[str]:
        names = [r["v"] for r in self.db.all(
            "SELECT DISTINCT j.value AS v FROM board_tasks t, json_each(t.assignees) j WHERE t.archived_at IS NULL")]
        return [ME, AGENT, *sorted({n for n in names if n not in (ME, AGENT)}, key=str.lower)]

    def _seed(self) -> None:
        self.create_board("Game", publish=False)

    def board(self, ref: Any = None) -> dict:
        """A board by id or name (case and spacing don't matter); None = the first board."""
        bs = self.boards()
        if ref is None or str(ref).strip() == "":
            return bs[0]
        r = str(ref).strip()
        for b in bs:
            if b["id"] == r or b["name"].lower() == r.lower():
                return b
        hits = [b for b in bs if _norm(b["name"]) == _norm(r)] or [b for b in bs if _norm(b["name"]).startswith(_norm(r))]
        if len(hits) == 1:
            return hits[0]
        raise NotFound(f'No board "{ref}". Boards: {", ".join(b["name"] for b in bs)}.')

    def column(self, board: dict, ref: Any) -> dict:
        """A column of `board` by id or name: exact, then a unique prefix, then a unique part
        ("todo" finds "To do", "progress" finds "In progress")."""
        cols = board["columns"]
        r = str(ref or "").strip()
        for c in cols:
            if c["id"] == r or c["name"].lower() == r.lower():
                return c
        n = _norm(r)
        for test in (lambda c: _norm(c["name"]) == n, lambda c: _norm(c["name"]).startswith(n),
                     lambda c: n in _norm(c["name"])):
            hits = [c for c in cols if n and test(c)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                break
        raise NotFound(f'No column "{ref}" on board {board["name"]}. Columns: {", ".join(c["name"] for c in cols)}.')

    def _column_board(self, cid: str) -> tuple[dict, dict]:
        for b in self.boards():
            for c in b["columns"]:
                if c["id"] == cid:
                    return b, c
        raise NotFound("No such column.")

    def create_board(self, name: Any, columns: list | None = None, *, publish: bool = True) -> dict:
        name = _title(name, "Board name")
        if any(b["name"].lower() == name.lower() for b in self.db.all("SELECT name FROM task_boards")):
            raise TaskError(f'There is already a board called "{name}".')
        cols = [(_title(c, "Column name"), False) for c in columns] if columns else DEFAULT_COLUMNS
        ts = time.time()
        bid = new_id("brd_")
        with self.db.transaction():
            order = (self.db.one("SELECT MAX(sort_order) AS m FROM task_boards") or {}).get("m")
            self.db.insert("task_boards", {"id": bid, "name": name, "sort_order": (order or 0) + 1 if order is not None else 0,
                                           "created_at": ts, "updated_at": ts})
            for i, (cname, done) in enumerate(cols):
                self.db.insert("task_columns", {"id": new_id("col_"), "board_id": bid, "name": cname, "sort_order": i,
                                                "is_done": int(done), "created_at": ts})
        if publish:
            self._boards_changed()
        return self.board(bid)

    def update_board(self, bid: str, *, name: Any = None, sort_order: float | None = None) -> dict:
        b = self.board(bid)
        fields: dict[str, Any] = {"updated_at": time.time()}
        if name is not None:
            n = _title(name, "Board name")
            if any(o["name"].lower() == n.lower() and o["id"] != b["id"] for o in self.boards()):
                raise TaskError(f'There is already a board called "{n}".')
            fields["name"] = n
        if sort_order is not None:
            fields["sort_order"] = float(sort_order)
        self.db.update("task_boards", "id", b["id"], fields)
        self._boards_changed()
        return self.board(b["id"])

    def delete_board(self, bid: str, *, force: bool = False) -> None:
        b = self.board(bid)
        if len(self.boards()) <= 1:
            raise TaskError("This is the only board; add another one before deleting it.")
        n = (self.db.one("SELECT COUNT(*) AS n FROM board_tasks WHERE board_id=?", [b["id"]]) or {}).get("n", 0)
        if n and not force:
            raise TaskError(f'Board "{b["name"]}" still has {n} task(s) (archived ones included). '
                            "Move them first, or delete with force to delete them too.")
        with self.db.transaction():
            self.db.execute("DELETE FROM board_tasks WHERE board_id=?", [b["id"]])
            self.db.execute("DELETE FROM task_columns WHERE board_id=?", [b["id"]])
            self.db.execute("DELETE FROM task_boards WHERE id=?", [b["id"]])
        self._boards_changed()

    def add_column(self, bid: str, name: Any, *, is_done: bool = False, index: int | None = None) -> dict:
        b = self.board(bid)
        name = _title(name, "Column name")
        if any(c["name"].lower() == name.lower() for c in b["columns"]):
            raise TaskError(f'Board {b["name"]} already has a column "{name}".')
        cid = new_id("col_")
        ids = [c["id"] for c in b["columns"]]
        ids.insert(len(ids) if index is None else max(0, min(int(index), len(ids))), cid)
        with self.db.transaction():
            self.db.insert("task_columns", {"id": cid, "board_id": b["id"], "name": name, "sort_order": 0,
                                            "is_done": int(bool(is_done)), "created_at": time.time()})
            for i, c in enumerate(ids):
                self.db.execute("UPDATE task_columns SET sort_order=? WHERE id=?", [i, c])
        self._boards_changed()
        return self._column_board(cid)[1]

    def update_column(self, cid: str, *, name: Any = None, is_done: bool | None = None) -> dict:
        b, c = self._column_board(cid)
        fields: dict[str, Any] = {}
        if name is not None:
            n = _title(name, "Column name")
            if any(o["name"].lower() == n.lower() and o["id"] != cid for o in b["columns"]):
                raise TaskError(f'Board {b["name"]} already has a column "{n}".')
            fields["name"] = n
        if is_done is not None:
            fields["is_done"] = int(bool(is_done))
        self.db.update("task_columns", "id", cid, fields)
        self._boards_changed()
        return self._column_board(cid)[1]

    def reorder_columns(self, bid: str, ids: list[str]) -> dict:
        b = self.board(bid)
        have = [c["id"] for c in b["columns"]]
        if sorted(ids) != sorted(have):
            raise TaskError("The new order must list every column of the board exactly once.")
        with self.db.transaction():
            for i, c in enumerate(ids):
                self.db.execute("UPDATE task_columns SET sort_order=? WHERE id=?", [i, c])
        self._boards_changed()
        return self.board(b["id"])

    def delete_column(self, cid: str, *, move_to: str | None = None) -> None:
        """Delete a column; its tasks (archived ones too) move to `move_to` (another column of the
        same board, by id or name), by default the first other column."""
        b, c = self._column_board(cid)
        others = [o for o in b["columns"] if o["id"] != cid]
        if not others:
            raise TaskError("A board needs at least one column.")
        target = self.column({**b, "columns": others}, move_to) if move_to else others[0]
        with self.db.transaction():
            base = (self.db.one("SELECT MAX(position) AS m FROM board_tasks WHERE column_id=?", [target["id"]]) or {}).get("m")
            base = (base if base is not None else -1) + 1
            for i, r in enumerate(self.db.all("SELECT id FROM board_tasks WHERE column_id=? ORDER BY position, num", [cid])):
                self.db.execute("UPDATE board_tasks SET column_id=?, position=? WHERE id=?", [target["id"], base + i, r["id"]])
                self._log(r["id"], ME, "moved", f'moved to {target["name"]} (column "{c["name"]}" was deleted)')
            self.db.execute("DELETE FROM task_columns WHERE id=?", [cid])
        self._boards_changed()

    def _boards_changed(self) -> None:
        self.app.bus.publish("task.boards_updated", {})

    # ------------------------------------------------------------------ reading tasks

    def _row(self, ref: Any) -> dict:
        r = None
        s = str(ref or "").strip()
        if s.startswith("tk_"):
            r = self.db.one(_SELECT + " WHERE t.id = ?", [s])
        elif (n := parse_code(ref)) is not None:
            r = self.db.one(_SELECT + " WHERE t.num = ?", [n])
        if not r:
            raise NotFound(f'No task "{ref}". Use a code like Task00001 (task_search finds tasks).')
        return r

    def summary(self, r: dict) -> dict:
        due = r.get("due")
        return {
            "id": r["id"], "code": format_code(r["num"]), "num": r["num"], "title": r["title"],
            "board_id": r["board_id"], "board": r["board_name"], "column_id": r["column_id"], "column": r["column_name"],
            "done": bool(r["is_done"]), "position": r["position"], "priority": r["priority"],
            "labels": json.loads(r["labels"] or "[]"), "due": due,
            "overdue": bool(due and due < _today().isoformat() and not r["is_done"]),
            "assignees": json.loads(r["assignees"] or "[]"), "agent_touched": bool(r["agent_touched"]),
            "created_by": r["created_by"], "subtasks": {"done": r["st_done"], "total": r["st_total"]},
            "comments": r["n_comments"], "sessions": r["n_sessions"], "archived": r["archived_at"] is not None,
            "archived_at": r["archived_at"], "created_at": r["created_at"], "updated_at": r["updated_at"],
        }

    def _subtasks(self, tid: str) -> list[dict]:
        subs = self.db.all("SELECT id, title, done FROM task_subtasks WHERE task_id=? ORDER BY position", [tid])
        items = self.db.all("SELECT i.id, i.subtask_id, i.title, i.done FROM task_checklist i JOIN task_subtasks s "
                            "ON s.id = i.subtask_id WHERE s.task_id=? ORDER BY i.position", [tid])
        for s in subs:
            s["done"] = bool(s["done"])
            s["items"] = [{"id": i["id"], "title": i["title"], "done": bool(i["done"])} for i in items
                          if i["subtask_id"] == s["id"]]
        return subs

    def detail(self, r: dict) -> dict:
        d = self.summary(r)
        tid = r["id"]
        sessions = self.db.all("SELECT x.session_id AS id, x.linked_at, s.title, s.deleted_at FROM task_sessions x "
                               "LEFT JOIN sessions s ON s.id = x.session_id WHERE x.task_id=? ORDER BY x.linked_at", [tid])
        d.update({
            "description": r["description"],
            "subtasks_list": self._subtasks(tid),
            "comments_list": [{**c, "by_agent": bool(c["by_agent"])} for c in self.db.all(
                "SELECT id, author, by_agent, body, session_id, created_at FROM task_comments WHERE task_id=? "
                "ORDER BY created_at, rowid", [tid])],
            "activity": self.db.all("SELECT actor, action, text, session_id, ts FROM task_activity WHERE task_id=? "
                                    "ORDER BY id DESC LIMIT ?", [tid, ACTIVITY_SHOWN]),
            "linked_sessions": [{"id": s["id"], "title": s["title"] or "(deleted session)", "linked_at": s["linked_at"],
                                 "missing": s["title"] is None, "in_trash": s["deleted_at"] is not None} for s in sessions],
        })
        return d

    def get(self, ref: Any) -> dict:
        return self.detail(self._row(ref))

    def search(self, *, query: str | None = None, assignee: str | None = None, label: str | None = None,
               priority: str | None = None, due: str | None = None, board: str | None = None,
               column: str | None = None, include_done: bool = False, archived: bool = False,
               limit: int = 30) -> tuple[list[dict], int]:
        """Matching tasks (summaries, in board and column order; archived ones newest first) and
        how many match in all."""
        where = ["t.archived_at IS NOT NULL" if archived else "t.archived_at IS NULL"]
        params: list[Any] = []
        cols: list[dict] = []
        if board:
            b = self.board(board)
            where.append("t.board_id = ?")
            params.append(b["id"])
            if column:
                cols = [self.column(b, column)]
        elif column:
            for b in self.boards():
                try:
                    cols.append(self.column(b, column))
                except NotFound:
                    pass
            if not cols:
                raise NotFound(f'No column "{column}" on any board.')
        if cols:
            where.append(f"t.column_id IN ({','.join('?' * len(cols))})")
            params += [c["id"] for c in cols]
        # Done columns are left out unless asked for (or the search names only done columns).
        if not include_done and not archived and not (cols and all(c["is_done"] for c in cols)):
            where.append("c.is_done = 0")
        if query and query.strip():
            q = query.strip()
            n = parse_code(q) if re.match(r"^\s*(#|task|\d)", q, re.I) else None
            words = [w for w in re.split(r"\s+", q) if w]
            hay = "lower(t.title || ' ' || t.description || ' ' || t.labels || ' task' || printf('%05d', t.num))"
            word_sql = " AND ".join(f"{hay} LIKE ? ESCAPE '\\'" for _ in words)
            if n is not None:
                where.append(f"(t.num = ? OR ({word_sql}))")
                params.append(n)
            else:
                where.append(f"({word_sql})")
            params += [_like(w) for w in words]
        if assignee and assignee.strip():
            if assignee.strip().lower() in ("unassigned", "nobody", "none"):
                where.append("json_array_length(t.assignees) = 0")
            else:
                where.append("EXISTS (SELECT 1 FROM json_each(t.assignees) j WHERE lower(j.value) = lower(?))")
                params.append(norm_assignee(assignee))
        if label and label.strip():
            where.append("EXISTS (SELECT 1 FROM json_each(t.labels) j WHERE lower(j.value) = lower(?))")
            params.append(label.strip().lstrip("#"))
        if priority:
            where.append("t.priority = ?")
            params.append(norm_priority(priority))
        if due:
            d = str(due).strip().lower()
            today = _today()
            if d == "overdue":
                where.append("t.due IS NOT NULL AND t.due < ? AND c.is_done = 0")
                params.append(today.isoformat())
            elif d == "today":
                where.append("t.due = ?")
                params.append(today.isoformat())
            elif d in ("week", "within 7 days", "7d"):
                where.append("t.due >= ? AND t.due <= ?")
                params += [today.isoformat(), (today + dt.timedelta(days=7)).isoformat()]
            elif d in ("none", "no date"):
                where.append("t.due IS NULL")
            else:
                raise TaskError(f'Due filter "{due}" not understood; use overdue, today, week or none.')
        sql_where = " WHERE " + " AND ".join(where)
        order = (" ORDER BY t.archived_at DESC" if archived
                 else " ORDER BY b.sort_order, b.created_at, c.sort_order, t.position, t.num")
        total = (self.db.one("SELECT COUNT(*) AS n FROM board_tasks t JOIN task_columns c ON c.id = t.column_id "
                             "JOIN task_boards b ON b.id = t.board_id" + sql_where, params) or {}).get("n", 0)
        rows = self.db.all(_SELECT + sql_where + order + " LIMIT ?", [*params, max(1, min(int(limit or 30), 2000))])
        return [self.summary(r) for r in rows], total

    def suggest(self, q: str = "", limit: int = 12) -> list[dict]:
        """For code autocomplete: tasks whose code starts with what's typed ("Task0001", "12"),
        else whose title contains it; newest changes first."""
        q = (q or "").strip()
        limit = max(1, min(int(limit), 50))
        base = _SELECT + " WHERE t.archived_at IS NULL"
        m = re.match(r"^(#?)\s*(task\s*[-_ ]?)?\s*(\d*)$", q, re.I)
        if not q:
            rows = self.db.all(base + " ORDER BY t.updated_at DESC LIMIT ?", [limit])
        elif "task".startswith(q.lower().lstrip("#").strip()):  # "T", "Ta", "Tas": the start of a code
            rows = self.db.all(base + " ORDER BY t.num DESC LIMIT ?", [limit])
        elif m and (m.group(2) or m.group(3)):
            digits = m.group(3)
            if m.group(2):  # typed from the start of the code: "Task", "Task0001" → Task00010…Task00019
                rows = self.db.all(base + " AND ('task' || printf('%05d', t.num)) LIKE ? ORDER BY t.num DESC LIMIT ?",
                                   ["task" + digits + "%", limit])
            else:  # a bare number ("12", "#12"): that task first, then numbers starting with it
                d = digits.lstrip("0") or "0"
                rows = self.db.all(base + " AND CAST(t.num AS TEXT) LIKE ? ORDER BY (t.num = ?) DESC, t.num DESC LIMIT ?",
                                   [d + "%", int(digits), limit])
        else:
            rows = self.db.all(base + " AND lower(t.title) LIKE ? ESCAPE '\\' ORDER BY t.updated_at DESC LIMIT ?",
                               [_like(q), limit])
        return [{"code": format_code(r["num"]), "title": r["title"], "column": r["column_name"],
                 "board": r["board_name"], "done": bool(r["is_done"])} for r in rows]

    def by_session(self, sid: str) -> list[dict]:
        rows = self.db.all(_SELECT + " WHERE t.archived_at IS NULL AND t.id IN "
                           "(SELECT task_id FROM task_sessions WHERE session_id=?) ORDER BY t.num", [sid])
        return [self.summary(r) for r in rows]

    # ------------------------------------------------------------------ writing tasks

    def _log(self, tid: str, actor: str, action: str, text: str, session_id: str | None = None) -> None:
        self.db.insert("task_activity", {"task_id": tid, "actor": actor, "action": action, "text": text[:500],
                                         "session_id": session_id, "ts": time.time()})

    def _emit(self, kind: str, tid: str, actor: str) -> dict:
        r = self._row(tid)
        self.app.bus.publish(f"task.{kind}", {"task": self.summary(r), "actor": actor})
        return self.detail(r)

    def _place(self, tid: str, column_id: str, where: Any = "bottom") -> None:
        """Put the task in `column_id` at `where`: "top", "bottom" or a 0-based index among the
        column's other live tasks; renumbers the column's positions 0..n-1."""
        ids = [r["id"] for r in self.db.all("SELECT id FROM board_tasks WHERE column_id=? AND id<>? AND archived_at IS NULL "
                                            "ORDER BY position, num", [column_id, tid])]
        if where == "top":
            at = 0
        elif where in (None, "", "bottom"):
            at = len(ids)
        else:
            try:
                at = max(0, min(int(where), len(ids)))
            except (TypeError, ValueError):
                raise TaskError('Position must be "top", "bottom" or an index.') from None
        ids.insert(at, tid)
        for i, x in enumerate(ids):
            if x == tid:
                self.db.execute("UPDATE board_tasks SET column_id=?, position=? WHERE id=?", [column_id, i, x])
            else:
                self.db.execute("UPDATE board_tasks SET position=? WHERE id=?", [i, x])

    def _next_num(self) -> int:
        """Take the next code number (call inside a transaction)."""
        r = self.db.one("SELECT next FROM task_counter WHERE id=1")
        top = (self.db.one("SELECT MAX(num) AS m FROM board_tasks") or {}).get("m") or 0
        n = max(int(r["next"]) if r else 1, top + 1)
        self.db.execute("INSERT INTO task_counter (id, next) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET next=excluded.next",
                        [n + 1])
        return n

    def create(self, *, title: Any, actor: str = ME, session_id: str | None = None, board: Any = None,
               column: Any = None, description: Any = "", priority: Any = "none", labels: Any = None,
               due: Any = None, assignees: Any = None, link_session: bool = False,
               position: Any = "bottom") -> dict:
        title = _title(title)
        desc = str(description or "")
        if len(desc) > DESCRIPTION_MAX:
            raise TaskError(f"Description is longer than {DESCRIPTION_MAX:,} characters.")
        b = self.board(board)
        col = self.column(b, column) if column else b["columns"][0]
        fields = {"priority": norm_priority(priority), "labels": norm_labels(labels), "due": norm_due(due),
                  "assignees": norm_assignees(assignees)}
        if link_session and session_id and not self.app.store.get(session_id):
            raise NotFound("No such session to link.")
        tid = new_id("tk_")
        ts = time.time()
        with self.db.transaction():
            num = self._next_num()
            self.db.insert("board_tasks", {"id": tid, "num": num, "board_id": b["id"], "column_id": col["id"],
                                           "position": 0, "title": title, "description": desc, **fields,
                                           "created_by": actor, "agent_touched": int(actor == AGENT),
                                           "created_at": ts, "updated_at": ts})
            self._place(tid, col["id"], position)
            self._log(tid, actor, "created", f'created in {b["name"]} › {col["name"]}', session_id)
            if link_session and session_id:
                self.db.execute("INSERT OR IGNORE INTO task_sessions (task_id, session_id, linked_at) VALUES (?, ?, ?)",
                                [tid, session_id, ts])
        return self._emit("created", tid, actor)

    def update(self, ref: Any, changes: dict, *, actor: str = ME, session_id: str | None = None) -> tuple[dict, list[str]]:
        """Apply `changes` all at once (or none of them, if any is invalid). Keys: title,
        description, priority, labels, due, assignees (replace), add_assignees, remove_assignees,
        board, column, position ("top" | "bottom") or index, subtasks (ops), link_session.
        Returns the task and what changed, as short texts."""
        r = self._row(ref)
        tid = r["id"]
        known = {"title", "description", "priority", "labels", "due", "assignees", "add_assignees", "remove_assignees",
                 "board", "column", "position", "index", "subtasks", "link_session"}
        if bad := sorted(set(changes) - known):
            raise TaskError(f"Unknown field(s): {', '.join(bad)}.")
        fields: dict[str, Any] = {}
        notes: list[str] = []
        if "title" in changes and changes["title"] is not None:
            t = _title(changes["title"])
            if t != r["title"]:
                fields["title"] = t
                notes.append(f'renamed to “{t}”')
        if "description" in changes and changes["description"] is not None:
            desc = str(changes["description"])
            if len(desc) > DESCRIPTION_MAX:
                raise TaskError(f"Description is longer than {DESCRIPTION_MAX:,} characters.")
            if desc != r["description"]:
                fields["description"] = desc
                notes.append("edited the description")
        if "priority" in changes and changes["priority"] is not None:
            p = norm_priority(changes["priority"])
            if p != r["priority"]:
                fields["priority"] = p
                notes.append(f"priority {r['priority']} → {p}")
        if "labels" in changes and changes["labels"] is not None:
            labels = norm_labels(changes["labels"])
            if labels != json.loads(r["labels"]):
                fields["labels"] = labels
                notes.append("labels: " + (", ".join(labels) or "none"))
        if "due" in changes:
            d = norm_due(changes["due"])
            if d != r["due"]:
                fields["due"] = d
                notes.append(f"due {d}" if d else "removed the due date")
        cur_assignees = json.loads(r["assignees"])
        new_assignees = list(cur_assignees)
        if changes.get("assignees") is not None:
            new_assignees = norm_assignees(changes["assignees"])
        for a in norm_assignees(changes.get("add_assignees")):
            if a.lower() not in {x.lower() for x in new_assignees}:
                new_assignees.append(a)
        if rm := {a.lower() for a in norm_assignees(changes.get("remove_assignees"))}:
            new_assignees = [a for a in new_assignees if a.lower() not in rm]
        if len(new_assignees) > 20:
            raise TaskError("At most 20 assignees.")
        if new_assignees != cur_assignees:
            fields["assignees"] = new_assignees
            notes.append("assignees: " + (", ".join(new_assignees) or "nobody"))
        # Where it goes.
        move_to: dict | None = None
        where: Any = None
        if changes.get("board") or changes.get("column"):
            b = self.board(changes["board"]) if changes.get("board") else self.board(r["board_id"])
            if changes.get("column"):
                col = self.column(b, changes["column"])
            elif b["id"] == r["board_id"]:  # the board it's already on: stays in its column
                col = {"id": r["column_id"]}
            else:
                col = b["columns"][0]
            if col["id"] != r["column_id"]:
                move_to = {"board": b, "column": col}
        if changes.get("index") is not None:
            where = changes["index"]
        elif changes.get("position"):
            if str(changes["position"]) not in ("top", "bottom"):
                raise TaskError('position must be "top" or "bottom".')
            where = changes["position"]
        # Subtasks: worked out in memory first; an op that doesn't apply rejects the whole update.
        new_subs = None
        if changes.get("subtasks"):
            new_subs, sub_notes = apply_subtask_ops(self._subtasks(tid), changes["subtasks"])
            notes += sub_notes
        link = bool(changes.get("link_session")) and bool(session_id)
        if link and not self.app.store.get(session_id):  # type: ignore[arg-type]
            raise NotFound("No such session to link.")
        with self.db.transaction():
            if move_to:
                self._place(tid, move_to["column"]["id"], "bottom" if where is None else where)
                fields["board_id"] = move_to["board"]["id"]
                src = f'{r["board_name"]} › {r["column_name"]}' if move_to["board"]["id"] != r["board_id"] else r["column_name"]
                dst = (f'{move_to["board"]["name"]} › {move_to["column"]["name"]}'
                       if move_to["board"]["id"] != r["board_id"] else move_to["column"]["name"])
                self._log(tid, actor, "moved", f"moved from {src} to {dst}", session_id)
            elif where is not None:
                self._place(tid, r["column_id"], where)
                self._log(tid, actor, "reordered", f'moved to {where if isinstance(where, str) else "position " + str(where)} '
                                                   f'of {r["column_name"]}', session_id)
            if new_subs is not None:
                self._write_subtasks(tid, new_subs)
            if link:
                cur = self.db.execute("INSERT OR IGNORE INTO task_sessions (task_id, session_id, linked_at) VALUES (?, ?, ?)",
                                      [tid, session_id, time.time()])
                if cur.rowcount:
                    notes.append("linked a session")
            for n in notes:
                action = "subtasks" if n.startswith(("subtask", "checklist")) else "updated"
                self._log(tid, actor, action, n, session_id)
            touched = bool(fields or move_to or where is not None or new_subs is not None or notes)
            if touched:
                fields["updated_at"] = time.time()
                if actor == AGENT:
                    fields["agent_touched"] = 1
                self.db.update("board_tasks", "id", tid, fields)
        if move_to:
            notes.insert(0, f'moved to {move_to["column"]["name"]}')
        return (self._emit("updated", tid, actor) if touched else self.get(tid)), notes

    def _write_subtasks(self, tid: str, subs: list[dict]) -> None:
        self.db.execute("DELETE FROM task_subtasks WHERE task_id=?", [tid])  # checklist items cascade
        for i, s in enumerate(subs):
            self.db.insert("task_subtasks", {"id": s["id"], "task_id": tid, "title": s["title"], "done": int(s["done"]),
                                             "position": i})
            for j, it in enumerate(s["items"]):
                self.db.insert("task_checklist", {"id": it["id"], "subtask_id": s["id"], "title": it["title"],
                                                  "done": int(it["done"]), "position": j})

    def move(self, ref: Any, column: Any, *, board: Any = None, where: Any = "bottom", actor: str = ME,
             session_id: str | None = None) -> dict:
        ch: dict[str, Any] = {"column": column, ("index" if isinstance(where, int) else "position"): where}
        if board:
            ch["board"] = board
        return self.update(ref, ch, actor=actor, session_id=session_id)[0]

    def complete(self, ref: Any, *, actor: str = ME, session_id: str | None = None) -> dict:
        """Move to the board's done column (its first one; the last column if it has none)."""
        r = self._row(ref)
        b = self.board(r["board_id"])
        done = next((c for c in b["columns"] if c["is_done"]), b["columns"][-1])
        if done["id"] == r["column_id"]:
            return self.get(r["id"])
        return self.update(r["id"], {"column": done["id"], "position": "top"}, actor=actor, session_id=session_id)[0]

    def comment(self, ref: Any, body: Any, *, actor: str = ME, session_id: str | None = None) -> dict:
        r = self._row(ref)
        text = str(body or "").strip()
        if not text:
            raise TaskError("The comment is empty.")
        if len(text) > COMMENT_MAX:
            raise TaskError(f"The comment is longer than {COMMENT_MAX:,} characters.")
        cid = new_id("cm_")
        with self.db.transaction():
            self.db.insert("task_comments", {"id": cid, "task_id": r["id"], "author": actor, "by_agent": int(actor == AGENT),
                                             "body": text, "session_id": session_id, "created_at": time.time()})
            self._log(r["id"], actor, "commented", "commented: " + text[:80] + ("…" if len(text) > 80 else ""), session_id)
            self.db.update("board_tasks", "id", r["id"], {"updated_at": time.time(),
                                                           **({"agent_touched": 1} if actor == AGENT else {})})
        return self._emit("updated", r["id"], actor)

    def archive(self, ref: Any, *, actor: str = ME, session_id: str | None = None) -> dict:
        r = self._row(ref)
        if r["archived_at"] is not None:
            return self.get(r["id"])
        with self.db.transaction():
            self.db.update("board_tasks", "id", r["id"], {"archived_at": time.time(), "updated_at": time.time(),
                                                           **({"agent_touched": 1} if actor == AGENT else {})})
            self._log(r["id"], actor, "archived", "moved to Recently deleted", session_id)
        return self._emit("archived", r["id"], actor)

    def restore(self, ref: Any, *, actor: str = ME, session_id: str | None = None) -> dict:
        r = self._row(ref)
        if r["archived_at"] is None:
            return self.get(r["id"])
        with self.db.transaction():
            self.db.update("board_tasks", "id", r["id"], {"archived_at": None, "updated_at": time.time(),
                                                           **({"agent_touched": 1} if actor == AGENT else {})})
            self._place(r["id"], r["column_id"], "bottom")
            self._log(r["id"], actor, "restored", f'restored to {r["column_name"]}', session_id)
        return self._emit("restored", r["id"], actor)

    def delete(self, ref: Any) -> dict:
        """Delete an archived task for good (the user only). Its code is never handed out again."""
        r = self._row(ref)
        if r["archived_at"] is None:
            raise TaskError("Only tasks in Recently deleted can be deleted for good; archive it first.")
        self.db.execute("DELETE FROM board_tasks WHERE id=?", [r["id"]])
        code = format_code(r["num"])
        self.app.bus.publish("task.deleted", {"id": r["id"], "code": code, "actor": ME})
        return {"id": r["id"], "code": code}

    def link(self, ref: Any, session_id: str, *, actor: str = ME) -> dict:
        r = self._row(ref)
        if not self.app.store.get(session_id):
            raise NotFound("No such session.")
        with self.db.transaction():
            cur = self.db.execute("INSERT OR IGNORE INTO task_sessions (task_id, session_id, linked_at) VALUES (?, ?, ?)",
                                  [r["id"], session_id, time.time()])
            if cur.rowcount:
                self._log(r["id"], actor, "linked", "linked a session", session_id)
        return self._emit("updated", r["id"], actor)

    def unlink(self, ref: Any, session_id: str, *, actor: str = ME) -> dict:
        r = self._row(ref)
        with self.db.transaction():
            cur = self.db.execute("DELETE FROM task_sessions WHERE task_id=? AND session_id=?", [r["id"], session_id])
            if cur.rowcount:
                self._log(r["id"], actor, "unlinked", "unlinked a session", session_id)
        return self._emit("updated", r["id"], actor)

    def attach(self, ref: Any, session_id: str) -> dict:
        """`/task <code>`: link the task to the session and put it in the session's context, as a
        user message the chat shows as a collapsed row (meta.task_context = code)."""
        s = self.app.store.get(session_id)
        if not s:
            raise NotFound("No such session.")
        if self.app.runner.is_running(session_id):
            raise TaskError("The agent is working in this session; attach the task once it's done.")
        d = self.link(ref, session_id)
        text = (f"[The user attached task {d['code']} from the task board to this conversation.]\n\n"
                + format_detail(d, comments=5, activity=0))
        self.app.store.add_message(session_id, Message(role="user", content=[TextBlock(text=text)],
                                                       meta={"task_context": d["code"]}))
        return d


# ===================================================================== subtask ops


def apply_subtask_ops(subs: list[dict], ops: Any) -> tuple[list[dict], list[str]]:
    """Apply subtask and checklist ops to a copy of `subs`, in order. Raises TaskError (naming the
    op) if any one of them doesn't apply, so a caller saves all of them or nothing."""
    if not isinstance(ops, list):
        raise TaskError("subtasks must be a list of ops.")
    if len(ops) > MAX_OPS:
        raise TaskError(f"At most {MAX_OPS} subtask ops per call.")
    subs = copy.deepcopy(subs)
    notes: list[str] = []

    def find(lst: list[dict], sid: Any, what: str, i: int) -> dict:
        for x in lst:
            if x["id"] == sid:
                return x
        raise TaskError(f'Op {i}: no {what} with id "{sid}".')

    def index(v: Any, n: int, i: int) -> int:
        try:
            return max(0, min(int(v), n))
        except (TypeError, ValueError):
            raise TaskError(f"Op {i}: index must be a number.") from None

    for i, op in enumerate(ops, 1):
        if not isinstance(op, dict):
            raise TaskError(f"Op {i}: expected an object.")
        kind = op.get("op")
        if kind not in SUBTASK_OPS:
            raise TaskError(f'Op {i}: unknown op "{kind}"; use one of {", ".join(SUBTASK_OPS)}.')
        try:
            if kind == "add":
                if len(subs) >= MAX_SUBTASKS:
                    raise TaskError(f"Op {i}: a task has at most {MAX_SUBTASKS} subtasks.")
                new = {"id": new_id("st_")[:11], "title": _title(op.get("title"), "Subtask title"), "done": False, "items": []}
                if op.get("after"):
                    at = subs.index(find(subs, op["after"], "subtask", i)) + 1
                    subs.insert(at, new)
                else:
                    subs.append(new)
                notes.append(f'subtask added: “{new["title"]}” ({new["id"]})')
            elif kind in ("rename", "toggle", "move", "remove"):
                s = find(subs, op.get("id"), "subtask", i)
                if kind == "rename":
                    s["title"] = _title(op.get("title"), "Subtask title")
                    notes.append(f'subtask renamed: “{s["title"]}”')
                elif kind == "toggle":
                    s["done"] = (not s["done"]) if op.get("done") is None else bool(op["done"])
                    notes.append(f'subtask {"done" if s["done"] else "not done"}: “{s["title"]}”')
                elif kind == "move":
                    subs.remove(s)
                    subs.insert(index(op.get("index"), len(subs), i), s)
                    notes.append(f'subtask moved: “{s["title"]}”')
                else:
                    subs.remove(s)
                    notes.append(f'subtask removed: “{s["title"]}”')
            else:
                s = find(subs, op.get("subtaskId") or op.get("subtask_id") or op.get("subtask"), "subtask", i)
                items = s["items"]
                if kind == "add_item":
                    if len(items) >= MAX_ITEMS:
                        raise TaskError(f"Op {i}: a subtask has at most {MAX_ITEMS} checklist items.")
                    it = {"id": new_id("ci_")[:11], "title": _title(op.get("title"), "Checklist item"), "done": False}
                    items.append(it)
                    notes.append(f'checklist item added to “{s["title"]}”: “{it["title"]}” ({it["id"]})')
                else:
                    it = find(items, op.get("id"), "checklist item", i)
                    if kind == "rename_item":
                        it["title"] = _title(op.get("title"), "Checklist item")
                        notes.append(f'checklist item renamed: “{it["title"]}”')
                    elif kind == "toggle_item":
                        it["done"] = (not it["done"]) if op.get("done") is None else bool(op["done"])
                        notes.append(f'checklist item {"checked" if it["done"] else "unchecked"}: “{it["title"]}”')
                    elif kind == "move_item":
                        items.remove(it)
                        items.insert(index(op.get("index"), len(items), i), it)
                        notes.append(f'checklist item moved: “{it["title"]}”')
                    else:
                        items.remove(it)
                        notes.append(f'checklist item removed: “{it["title"]}”')
        except TaskError as e:
            msg = str(e)
            raise TaskError(msg if msg.startswith("Op ") else f"Op {i} ({kind}): {msg}") from None
    return subs, notes


# ===================================================================== text for the model


def format_line(t: dict) -> str:
    parts = [f'{t["code"]} [{t["board"]} › {t["column"]}] {t["title"]}']
    if t["priority"] != "none":
        parts.append(t["priority"])
    if t["labels"]:
        parts.append(" ".join("#" + x for x in t["labels"]))
    if t["due"]:
        parts.append(f'due {t["due"]}' + (" (overdue)" if t["overdue"] else ""))
    if t["assignees"]:
        parts.append(", ".join("@" + a for a in t["assignees"]))
    if t["subtasks"]["total"]:
        parts.append(f'subtasks {t["subtasks"]["done"]}/{t["subtasks"]["total"]}')
    if t["archived"]:
        parts.append(f'in Recently deleted since {_fmt_ts(t["archived_at"])}')
    return " · ".join(parts)


def format_subtasks(subs: list[dict]) -> list[str]:
    if not subs:
        return []
    out = [f'Subtasks ({sum(s["done"] for s in subs)}/{len(subs)} done):']
    for s in subs:
        out.append(f'- [{"x" if s["done"] else " "}] {s["title"]} (id {s["id"]})')
        out += [f'    - [{"x" if it["done"] else " "}] {it["title"]} (id {it["id"]})' for it in s["items"]]
    return out


def format_detail(d: dict, *, comments: int = 20, activity: int = 10) -> str:
    out = [f'{d["code"]}: {d["title"]}',
           f'Board: {d["board"]} › {d["column"]}{" (done column)" if d["done"] else ""} · Priority: {d["priority"]}'
           + (f' · Due: {d["due"]}' + (" (overdue)" if d["overdue"] else "") if d["due"] else " · No due date"),
           "Labels: " + (", ".join(d["labels"]) or "none") + " · Assignees: " + (", ".join(d["assignees"]) or "nobody")]
    if d["archived"]:
        out.append(f'Archived (in Recently deleted) since {_fmt_ts(d["archived_at"])}; task_restore brings it back.')
    out.append(f'Created {_fmt_ts(d["created_at"])} by {d["created_by"]} · updated {_fmt_ts(d["updated_at"])}')
    if d["linked_sessions"]:
        out.append("Linked sessions: " + "; ".join(f'{s["title"]} ({s["id"]})' for s in d["linked_sessions"]))
    out += ["", "Description:", d["description"].strip() or "(none)"]
    if d["subtasks_list"]:
        out += ["", *format_subtasks(d["subtasks_list"])]
    cms = d["comments_list"][-comments:] if comments else []
    if cms:
        more = len(d["comments_list"]) - len(cms)
        out += ["", f'Comments ({len(d["comments_list"])}' + (f", last {len(cms)}" if more else "") + "):"]
        out += [f'- {c["author"]}, {_fmt_ts(c["created_at"])}: {c["body"]}' for c in cms]
    if activity and d["activity"]:
        out += ["", "Recent activity:"]
        out += [f'- {_fmt_ts(a["ts"])} {a["actor"]}: {a["text"]}' for a in d["activity"][:activity]]
    return "\n".join(out)


def format_boards(boards: list[dict], people: list[str]) -> str:
    out = []
    for b in boards:
        cols = ", ".join(f'{c["name"]}{" (done)" if c["is_done"] else ""}: {c["count"]}' for c in b["columns"])
        out.append(f'{b["name"]} (id {b["id"]}) — {cols}')
    out.append("Assignees in use: " + ", ".join(people) + ' ("me" is the user, "agent" is you).')
    return "\n".join(out)


# ===================================================================== agent tools

_SUBTASK_OP = {"type": "object", "properties": {
    "op": {"type": "string", "enum": SUBTASK_OPS},
    "id": {"type": "string", "description": "Subtask id (rename/toggle/move/remove) or checklist item id (*_item ops)"},
    "subtaskId": {"type": "string", "description": "The subtask a checklist item belongs to (*_item ops)"},
    "title": {"type": "string"}, "done": {"type": "boolean"},
    "index": {"type": "integer", "description": "0-based new position (move, move_item)"},
    "after": {"type": "string", "description": "add: put the new subtask after this subtask id"}},
    "required": ["op"]}
_TASK = {"type": "string", "description": "Task code, e.g. Task00012 (or just 12)"}


def board_tools_offered(session: dict) -> bool:
    """The task tools are on unless the session turned them off (settings.task_board = false)."""
    return (session.get("settings") or {}).get("task_board", True) is not False


def _writable(ctx: ToolContext) -> None:
    if ctx.mode == "plan":
        raise ToolDenied("Session is in Plan only mode: the task board is read-only. Describe the change instead.")


def _err(e: TaskError) -> ToolOutput:
    return ToolOutput(str(e), is_error=True)


def install(app: "AppState") -> TaskBoard:
    """Create the board service and register its tools on an app (idempotent). register() calls
    this; tests call it on a bare AppState."""
    tb = app.extensions.get("task_board")
    if isinstance(tb, TaskBoard):
        return tb
    tb = TaskBoard(app)
    app.extensions["task_board"] = tb
    notes = getattr(app, "prompt_notes", None)
    if isinstance(notes, list):
        notes.append(lambda s: PROMPT_NOTE if board_tools_offered(s) else None)
    reg = app.tools

    def add(name: str, desc: str, schema: dict, fn: Any, *, write: bool) -> None:
        reg.register(Tool(ToolSpec(name=name, description=desc, input_schema=schema, read_only=not write), fn,
                          main_only=write, when=board_tools_offered))

    async def t_boards(ctx: ToolContext, a: dict) -> ToolOutput:
        return ToolOutput(format_boards(tb.boards(), tb.people()))

    async def t_search(ctx: ToolContext, a: dict) -> ToolOutput:
        try:
            limit = max(1, min(int(a.get("limit") or 30), 100))
            rows, total = tb.search(query=a.get("query"), assignee=a.get("assignee"), label=a.get("label"),
                                    priority=a.get("priority"), due=a.get("due"), board=a.get("board"),
                                    column=a.get("column"), include_done=bool(a.get("include_done")),
                                    archived=bool(a.get("archived")), limit=limit)
        except TaskError as e:
            return _err(e)
        if not rows:
            return ToolOutput("No matching tasks." + ("" if a.get("include_done") or a.get("archived")
                                                     else " (Done columns are left out; set include_done to search them.)"))
        head = f"{total} task(s)" + (f", showing {len(rows)}" if total > len(rows) else "") + ":"
        return ToolOutput("\n".join([head, *map(format_line, rows)]))

    async def t_get(ctx: ToolContext, a: dict) -> ToolOutput:
        try:
            return ToolOutput(format_detail(tb.get(a.get("task"))))
        except TaskError as e:
            return _err(e)

    async def t_create(ctx: ToolContext, a: dict) -> ToolOutput:
        _writable(ctx)
        try:
            d = tb.create(title=a.get("title"), actor=AGENT, session_id=ctx.session_id, board=a.get("board"),
                          column=a.get("column"), description=a.get("description") or "", priority=a.get("priority") or "none",
                          labels=a.get("labels"), due=a.get("due"), assignees=a.get("assignees"),
                          link_session=a.get("link_session", True) is not False)
        except TaskError as e:
            return _err(e)
        return ToolOutput(f"Created {format_line(d)}")

    async def t_update(ctx: ToolContext, a: dict) -> ToolOutput:
        _writable(ctx)
        ch = {k: v for k, v in a.items() if k != "task"}
        try:
            d, notes = tb.update(a.get("task"), ch, actor=AGENT, session_id=ctx.session_id)
        except TaskError as e:
            return _err(e)
        what = "; ".join(notes) if notes else "nothing changed"
        text = f"Updated {d['code']} ({what}).\n{format_line(d)}"
        if ch.get("subtasks"):  # the ids of what was just added, for the next ops
            text += "\n\n" + "\n".join(format_subtasks(d["subtasks_list"]) or ["No subtasks."])
        return ToolOutput(text)

    async def t_comment(ctx: ToolContext, a: dict) -> ToolOutput:
        _writable(ctx)
        try:
            d = tb.comment(a.get("task"), a.get("body"), actor=AGENT, session_id=ctx.session_id)
        except TaskError as e:
            return _err(e)
        return ToolOutput(f"Commented on {d['code']} ({len(d['comments_list'])} comment(s) now).")

    async def t_archive(ctx: ToolContext, a: dict) -> ToolOutput:
        _writable(ctx)
        try:
            d = tb.archive(a.get("task"), actor=AGENT, session_id=ctx.session_id)
        except TaskError as e:
            return _err(e)
        return ToolOutput(f"Archived {d['code']} (moved to Recently deleted; task_restore brings it back).")

    async def t_restore(ctx: ToolContext, a: dict) -> ToolOutput:
        _writable(ctx)
        try:
            d = tb.restore(a.get("task"), actor=AGENT, session_id=ctx.session_id)
        except TaskError as e:
            return _err(e)
        return ToolOutput(f"Restored {format_line(d)}")

    add("task_boards", "The task boards with their columns (task counts) and the assignees in use.", obj({}),
        t_boards, write=False)
    add("task_search", "Find tasks on the task board by text (title, description, labels, code), assignee, label, "
        "priority, due (overdue, today, week, none), board or column. Done columns are left out unless include_done; "
        "archived: search Recently deleted instead.",
        obj({"query": {"type": "string"}, "assignee": {"type": "string", "description": '"me" (the user), "agent", '
                                                       '"unassigned" or a name'},
             "label": {"type": "string"}, "priority": {"type": "string", "enum": PRIORITIES},
             "due": {"type": "string", "enum": DUE_FILTERS}, "board": {"type": "string"}, "column": {"type": "string"},
             "include_done": {"type": "boolean"}, "archived": {"type": "boolean"},
             "limit": {"type": "integer", "description": "default 30, at most 100"}}), t_search, write=False)
    add("task_get", "One task by code: fields, description, subtasks and checklist items (with ids), comments, "
        "linked sessions and recent activity.", obj({"task": _TASK}, ["task"]), t_get, write=False)
    add("task_create", "Create a task on the task board (default: the first board's first column, at the bottom). "
        "Links it to this session unless link_session is false.",
        obj({"title": {"type": "string"}, "description": {"type": "string", "description": "Markdown"},
             "board": {"type": "string"}, "column": {"type": "string"}, "priority": {"type": "string", "enum": PRIORITIES},
             "labels": {"type": "array", "items": {"type": "string"}},
             "due": {"type": "string", "description": "YYYY-MM-DD"},
             "assignees": {"type": "array", "items": {"type": "string"}, "description": '"me" = the user, "agent" = you'},
             "link_session": {"type": "boolean"}}, ["title"]), t_create, write=True)
    add("task_update", "Change a task: only the fields given change. column (and board) moves it; position top or "
        "bottom places it in the column. assignees replaces, add_assignees/remove_assignees adjust. subtasks: ops "
        "applied in order, all or nothing (ids from task_get). due \"\" removes the date.",
        obj({"task": _TASK, "title": {"type": "string"}, "description": {"type": "string"},
             "priority": {"type": "string", "enum": PRIORITIES}, "labels": {"type": "array", "items": {"type": "string"}},
             "due": {"type": "string"}, "board": {"type": "string"}, "column": {"type": "string"},
             "position": {"type": "string", "enum": ["top", "bottom"]},
             "assignees": {"type": "array", "items": {"type": "string"}},
             "add_assignees": {"type": "array", "items": {"type": "string"}},
             "remove_assignees": {"type": "array", "items": {"type": "string"}},
             "subtasks": {"type": "array", "items": _SUBTASK_OP}, "link_session": {"type": "boolean"}}, ["task"]),
        t_update, write=True)
    add("task_comment", "Add a Markdown comment to a task (shown as written by the agent).",
        obj({"task": _TASK, "body": {"type": "string"}}, ["task", "body"]), t_comment, write=True)
    add("task_archive", "Archive a task: it moves to Recently deleted, where it can be restored.",
        obj({"task": _TASK}, ["task"]), t_archive, write=True)
    add("task_restore", "Restore an archived task from Recently deleted to its column.",
        obj({"task": _TASK}, ["task"]), t_restore, write=True)
    return tb


# ===================================================================== REST


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    tb = install(S)

    def call(fn: Any, *args: Any, **kw: Any) -> Any:
        try:
            return fn(*args, **kw)
        except TaskError as e:
            raise HTTPException(e.status, str(e)) from None

    # The scheduled tasks (Schedule page) own /tasks, /tasks/{id} and /tasks/{id}/run; everything
    # here lives under /tasks/boards, /tasks/columns, /tasks/items, /tasks/search … instead.

    @api.get("/tasks/boards")
    async def boards() -> dict:
        return {"boards": tb.boards(), "people": tb.people(), "priorities": PRIORITIES}

    @api.post("/tasks/boards")
    async def create_board(body: dict = Body(...)) -> dict:
        return call(tb.create_board, body.get("name"), body.get("columns"))

    @api.patch("/tasks/boards/{bid}")
    async def update_board(bid: str, body: dict = Body(...)) -> dict:
        return call(tb.update_board, bid, name=body.get("name"), sort_order=body.get("sort_order"))

    @api.delete("/tasks/boards/{bid}")
    async def delete_board(bid: str, force: bool = False) -> dict:
        call(tb.delete_board, bid, force=force)
        return {"ok": True}

    @api.post("/tasks/boards/{bid}/columns")
    async def add_column(bid: str, body: dict = Body(...)) -> dict:
        return call(tb.add_column, bid, body.get("name"), is_done=bool(body.get("is_done")), index=body.get("index"))

    @api.post("/tasks/boards/{bid}/order")
    async def reorder_columns(bid: str, body: dict = Body(...)) -> dict:
        return call(tb.reorder_columns, bid, [str(x) for x in body.get("column_ids") or []])

    @api.patch("/tasks/columns/{cid}")
    async def update_column(cid: str, body: dict = Body(...)) -> dict:
        return call(tb.update_column, cid, name=body.get("name"), is_done=body.get("is_done"))

    @api.delete("/tasks/columns/{cid}")
    async def delete_column(cid: str, move_to: str | None = None) -> dict:
        call(tb.delete_column, cid, move_to=move_to)
        return {"ok": True}

    @api.get("/tasks/search")
    async def search(q: str | None = None, assignee: str | None = None, label: str | None = None,
                     priority: str | None = None, due: str | None = None, board: str | None = None,
                     column: str | None = None, include_done: bool = False, archived: bool = False,
                     limit: int = 500) -> dict:
        rows, total = call(tb.search, query=q, assignee=assignee, label=label, priority=priority, due=due, board=board,
                           column=column, include_done=include_done, archived=archived, limit=limit)
        return {"tasks": rows, "total": total}

    @api.get("/tasks/archived")
    async def archived(limit: int = 500) -> dict:
        rows, total = call(tb.search, archived=True, limit=limit)
        return {"tasks": rows, "total": total}

    @api.get("/tasks/suggest")
    async def suggest(q: str = "", limit: int = 12) -> list[dict]:
        return tb.suggest(q, limit)

    @api.get("/tasks/by-code/{code}")
    async def by_code(code: str) -> dict:
        return call(tb.get, code)

    @api.get("/tasks/by-session/{sid}")
    async def by_session(sid: str) -> list[dict]:
        return tb.by_session(sid)

    @api.post("/tasks/items")
    async def create_task(body: dict = Body(...)) -> dict:
        return call(tb.create, title=body.get("title"), board=body.get("board"), column=body.get("column"),
                    description=body.get("description") or "", priority=body.get("priority") or "none",
                    labels=body.get("labels"), due=body.get("due"), assignees=body.get("assignees"),
                    session_id=body.get("session_id"), link_session=bool(body.get("session_id")),
                    position=body.get("position") or "bottom")

    @api.get("/tasks/items/{code}")
    async def get_task(code: str) -> dict:
        return call(tb.get, code)

    @api.patch("/tasks/items/{code}")
    async def update_task(code: str, body: dict = Body(...)) -> dict:
        return call(tb.update, code, body)[0]

    @api.post("/tasks/items/{code}/subtasks")
    async def subtask_ops(code: str, body: dict = Body(...)) -> dict:
        return call(tb.update, code, {"subtasks": body.get("ops") or []})[0]

    @api.post("/tasks/items/{code}/done")
    async def complete(code: str) -> dict:
        return call(tb.complete, code)

    @api.post("/tasks/items/{code}/comments")
    async def comment(code: str, body: dict = Body(...)) -> dict:
        return call(tb.comment, code, body.get("body"))

    @api.post("/tasks/items/{code}/archive")
    async def archive(code: str) -> dict:
        return call(tb.archive, code)

    @api.post("/tasks/items/{code}/restore")
    async def restore(code: str) -> dict:
        return call(tb.restore, code)

    @api.delete("/tasks/items/{code}")
    async def delete(code: str) -> dict:
        return call(tb.delete, code)

    @api.post("/tasks/items/{code}/sessions")
    async def link(code: str, body: dict = Body(...)) -> dict:
        return call(tb.link, code, str(body.get("session_id") or ""))

    @api.delete("/tasks/items/{code}/sessions/{sid}")
    async def unlink(code: str, sid: str) -> dict:
        return call(tb.unlink, code, sid)

    @api.post("/tasks/items/{code}/attach")
    async def attach(code: str, body: dict = Body(...)) -> dict:
        return call(tb.attach, code, str(body.get("session_id") or ""))
