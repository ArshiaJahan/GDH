"""SQLite storage. One file, WAL mode, a single connection guarded by a lock.

All app state lives here so a reload or relaunch restores everything.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import data_dir

log = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT 'New session',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 0,
  folder TEXT,                         -- NULL = chat (no folder)
  model TEXT NOT NULL,
  effort TEXT NOT NULL DEFAULT 'medium',
  account TEXT NOT NULL DEFAULT 'default',
  mode TEXT NOT NULL DEFAULT 'ask',    -- ask | accept_edits | plan
  harness TEXT NOT NULL DEFAULT 'builtin', -- builtin | agent_sdk | codex_cli
  location TEXT NOT NULL DEFAULT 'local',
  settings TEXT NOT NULL DEFAULT '{}', -- json: connectors, skills, shared_tools, ...
  status TEXT NOT NULL DEFAULT 'idle'  -- idle | running | paused
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,               -- json list of content blocks
  meta TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  compacted INTEGER NOT NULL DEFAULT 0 -- 1 = summarized away, kept for history
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  type TEXT NOT NULL,
  data TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id, seq);

CREATE TABLE IF NOT EXISTS usage_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  session_id TEXT,
  provider TEXT NOT NULL,
  profile TEXT NOT NULL DEFAULT 'default',
  model TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'main',   -- main | subagent | compact | tool
  run_id TEXT,
  effort TEXT,
  feature TEXT,                        -- chat | tts | stt | sfx | music | voice_changer ...
  voice TEXT,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  cache_write_tokens INTEGER DEFAULT 0,
  reasoning_tokens INTEGER DEFAULT 0,
  characters INTEGER DEFAULT 0,
  credits REAL DEFAULT 0,
  cost_usd REAL DEFAULT 0,
  latency_ms INTEGER DEFAULT 0,
  ok INTEGER NOT NULL DEFAULT 1,
  error_kind TEXT,                     -- rate_limit | auth | other
  context_fill REAL,                   -- fraction of context window used
  rate_limits TEXT
);
CREATE INDEX IF NOT EXISTS usage_ts ON usage_records(ts);
CREATE INDEX IF NOT EXISTS usage_model ON usage_records(model, ts);

CREATE TABLE IF NOT EXISTS auth_status (
  provider TEXT NOT NULL,
  profile TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  models TEXT NOT NULL DEFAULT '[]',
  extra TEXT NOT NULL DEFAULT '{}',
  checked_at REAL NOT NULL,
  PRIMARY KEY (provider, profile)
);

CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  session_id TEXT,
  kind TEXT NOT NULL,                  -- effort | command | edit | elevenlabs | shared_tool | delete
  payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', -- pending | approved | downgraded | denied
  created_at REAL NOT NULL,
  resolved_at REAL
);

CREATE TABLE IF NOT EXISTS jobs (                -- background tasks
  id TEXT PRIMARY KEY,
  session_id TEXT,
  kind TEXT NOT NULL,                  -- subagent | command | codex_cli | elevenlabs | scheduled
  title TEXT NOT NULL,
  status TEXT NOT NULL,                -- queued | running | done | failed | cancelled
  started_at REAL NOT NULL,
  ended_at REAL,
  log_tail TEXT NOT NULL DEFAULT '',
  meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS jobs_session ON jobs(session_id, started_at);

CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  session_id TEXT,
  message_id TEXT,
  kind TEXT NOT NULL,                  -- artifact | media | file | link
  subtype TEXT,                        -- html, md, svg, code, image, audio, video, pdf, ...
  provider TEXT,                       -- anthropic | openai | elevenlabs | user
  model TEXT,
  source TEXT NOT NULL,                -- user | agent | tool
  title TEXT,
  filename TEXT,
  path TEXT,
  url TEXT,
  size INTEGER,
  mime TEXT,
  extracted_text TEXT,
  meta TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  parent_id TEXT,                      -- previous version of an artifact
  created_at REAL NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_session ON items(session_id, kind, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS items_link_dedupe ON items(session_id, url) WHERE kind = 'link' AND deleted = 0;

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
  title, filename, url, extracted_text, content='items', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
  INSERT INTO items_fts(rowid, title, filename, url, extracted_text)
  VALUES (new.rowid, new.title, new.filename, new.url, new.extracted_text);
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, filename, url, extracted_text)
  VALUES ('delete', old.rowid, old.title, old.filename, old.url, old.extracted_text);
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, filename, url, extracted_text)
  VALUES ('delete', old.rowid, old.title, old.filename, old.url, old.extracted_text);
  INSERT INTO items_fts(rowid, title, filename, url, extracted_text)
  VALUES (new.rowid, new.title, new.filename, new.url, new.extracted_text);
END;

CREATE TABLE IF NOT EXISTS delegation_stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  session_id TEXT,
  job_id TEXT,
  unit TEXT,
  job_type TEXT NOT NULL,
  provider TEXT NOT NULL,
  tier TEXT,
  model TEXT,
  effort TEXT,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  reasoning_tokens INTEGER DEFAULT 0,
  characters INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0,
  wall_time_s REAL DEFAULT 0,
  success INTEGER NOT NULL,
  escalation_steps INTEGER DEFAULT 0,
  approval_requested INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS delegation_type ON delegation_stats(job_type);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  prompt TEXT NOT NULL,
  schedule TEXT NOT NULL,              -- cron expression or 'once:<iso>'
  model TEXT NOT NULL,
  effort TEXT NOT NULL,
  folder TEXT,
  mode TEXT NOT NULL DEFAULT 'ask',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_runs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
  session_id TEXT,
  started_at REAL NOT NULL,
  ended_at REAL,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (       -- file contents before each agent write
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  path TEXT NOT NULL,
  content BLOB,                        -- NULL = file did not exist
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS snapshots_session ON snapshots(session_id, path);

CREATE TABLE IF NOT EXISTS mcp_servers (
  name TEXT PRIMARY KEY,
  transport TEXT NOT NULL,             -- stdio | http
  command TEXT,
  args TEXT NOT NULL DEFAULT '[]',
  env TEXT NOT NULL DEFAULT '{}',
  url TEXT,
  headers TEXT NOT NULL DEFAULT '{}',
  enabled_default INTEGER NOT NULL DEFAULT 1,
  shared INTEGER NOT NULL DEFAULT 0    -- comes from another machine
);

CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS session_groups (  -- sidebar groups ("folders" of sessions)
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT NOT NULL DEFAULT 'gray',  -- one of store.GROUP_COLORS
  sort_order REAL NOT NULL DEFAULT 0,
  collapsed INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
"""

# Columns added to `sessions` after the first release. `_migrate` adds whichever are missing, so new
# and old databases end up with the same table (ALTER TABLE ADD COLUMN keeps every existing row).
SESSION_COLUMNS = {
    "group_id": "TEXT",                    # session_groups.id; NULL = ungrouped
    "archived_at": "REAL",                 # set = archived (hidden from the default list)
    "deleted_at": "REAL",                  # set = in Trash (purged after [sessions] trash_days)
    "sort_order": "REAL NOT NULL DEFAULT 0",  # manual order of pinned sessions
    "activity_at": "REAL",                 # last message time ("Last activity"); NULL = no messages
    "last_read_at": "REAL",                # unread = activity_at > last_read_at
    "last_error": "TEXT",                  # the last turn failed with this (cleared when a turn starts)
    "forked_from": "TEXT",                 # json {session_id, message_id, title}
}

# Full-text index over the text blocks of chat messages (sidebar "In messages" search). Kept in sync
# by triggers; the FTS table holds its own copy of the text (not the JSON or any media).
# json_extract only ever sees object elements (CASE is evaluated lazily): on a string element it
# raises "malformed JSON", which would abort the backfill and fail the message INSERT via the trigger.
_MSG_TEXT = ("SELECT group_concat(CASE WHEN j.type = 'object' THEN json_extract(j.value, '$.text') END, ' ') AS t "
             "FROM json_each(CASE WHEN json_valid({c}) THEN {c} ELSE '[]' END) j "
             "WHERE (CASE WHEN j.type = 'object' THEN json_extract(j.value, '$.type') END) = 'text'")
FTS_TRIGGERS = ("messages_fts_ai", "messages_fts_ad", "messages_fts_au")
MESSAGES_FTS = [
    "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
    "text, session_id UNINDEXED, message_id UNINDEXED, tokenize='porter unicode61')",
    "CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN "
    "INSERT INTO messages_fts(rowid, text, session_id, message_id) "
    f"SELECT new.rowid, t, new.session_id, new.id FROM ({_MSG_TEXT.format(c='new.content')}) "
    "WHERE t IS NOT NULL; END",
    "CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN "
    "DELETE FROM messages_fts WHERE rowid = old.rowid; END",
    "CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE OF content ON messages BEGIN "
    "DELETE FROM messages_fts WHERE rowid = old.rowid; "
    "INSERT INTO messages_fts(rowid, text, session_id, message_id) "
    f"SELECT new.rowid, t, new.session_id, new.id FROM ({_MSG_TEXT.format(c='new.content')}) "
    "WHERE t IS NOT NULL; END",
]


def _columns(c: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def _v1_session_columns(c: sqlite3.Connection) -> None:
    """v1: the sessions columns added after the first release (idempotent, so databases that
    already got some of them from versions before user_version was used come out the same)."""
    missing = [k for k in SESSION_COLUMNS if k not in _columns(c, "sessions")]
    for k in missing:
        c.execute(f"ALTER TABLE sessions ADD COLUMN {k} {SESSION_COLUMNS[k]}")
    if "activity_at" in missing:  # existing sessions: last message time, all read
        c.execute("UPDATE sessions SET activity_at = (SELECT MAX(created_at) FROM messages m "
                  "WHERE m.session_id = sessions.id)")
    if "last_read_at" in missing:
        c.execute("UPDATE sessions SET last_read_at = activity_at")
    c.execute("CREATE INDEX IF NOT EXISTS sessions_group ON sessions(group_id)")
    c.execute("CREATE INDEX IF NOT EXISTS sessions_deleted ON sessions(deleted_at)")


def _v2_storage(c: sqlite3.Connection) -> None:
    """v2: snapshots of files too large to keep (revert disabled for them), and an index for
    pruning old events by time."""
    if "too_large" not in _columns(c, "snapshots"):
        c.execute("ALTER TABLE snapshots ADD COLUMN too_large INTEGER NOT NULL DEFAULT 0")
    c.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(ts)")


V3_CITADEL = [
    # Trusted project / user-skill hook files (kind "file") and Unity gate consent (kind "preset").
    # detail: json {tools: [...], commands: [...]} consented at approval time.
    """CREATE TABLE IF NOT EXISTS hook_trust (
      project TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
      sha256 TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}',
      approved_at REAL NOT NULL, PRIMARY KEY (project, path, kind))""",
    # Every gate evaluation (status pass | fail | skipped | error); written by HookBus.record_gate.
    """CREATE TABLE IF NOT EXISTS gate_runs (
      id TEXT PRIMARY KEY, session_id TEXT, campaign_id TEXT, gate TEXT NOT NULL, level TEXT,
      status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, subjects TEXT NOT NULL DEFAULT '[]',
      summary TEXT, detail TEXT NOT NULL DEFAULT '{}', started_at REAL NOT NULL, ended_at REAL)""",
    "CREATE INDEX IF NOT EXISTS gate_runs_session ON gate_runs(session_id, started_at)",
    # Observed results the quality ladder counts. subjects: json story/AC ids; observed: tool |
    # command | human | gate.
    """CREATE TABLE IF NOT EXISTS ladder_evidence (
      id TEXT PRIMARY KEY, project TEXT NOT NULL, session_id TEXT, campaign_id TEXT,
      level TEXT NOT NULL, status TEXT NOT NULL, subjects TEXT NOT NULL DEFAULT '[]',
      source TEXT NOT NULL, observed TEXT NOT NULL,
      path TEXT, item_id TEXT, detail TEXT NOT NULL DEFAULT '{}', ts REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ladder_project ON ladder_evidence(project, ts)",
    # Campaigns and chains (kind chain | campaign). phases: json, the resolved template plus
    # per-phase state. The claim columns make resuming exclusive.
    """CREATE TABLE IF NOT EXISTS campaigns (
      id TEXT PRIMARY KEY, slug TEXT NOT NULL, title TEXT NOT NULL, kind TEXT NOT NULL,
      template TEXT NOT NULL, folder TEXT NOT NULL, file TEXT, status TEXT NOT NULL,
      phase INTEGER NOT NULL DEFAULT 0, phases TEXT NOT NULL DEFAULT '[]',
      autopilot INTEGER NOT NULL DEFAULT 0, model TEXT, effort TEXT, mode TEXT, group_id TEXT,
      budget_usd REAL, max_sessions INTEGER, auto_turns INTEGER NOT NULL DEFAULT 0, stall INTEGER NOT NULL DEFAULT 0,
      claim_session TEXT, claim_heartbeat REAL, breaker TEXT NOT NULL DEFAULT '{}',
      created_at REAL NOT NULL, updated_at REAL NOT NULL, UNIQUE (folder, slug))""",
    """CREATE TABLE IF NOT EXISTS campaign_sessions (
      campaign_id TEXT NOT NULL, session_id TEXT NOT NULL, phase INTEGER, started_at REAL NOT NULL,
      ended_at REAL, end_reason TEXT, PRIMARY KEY (campaign_id, session_id))""",
    # Fleet waves and their units (one subagent each; scope: json list of claimed paths).
    """CREATE TABLE IF NOT EXISTS fleet_waves (
      id TEXT PRIMARY KEY, session_id TEXT NOT NULL, campaign_id TEXT, n INTEGER NOT NULL, status TEXT NOT NULL,
      strikes INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, closed_at REAL)""",
    """CREATE TABLE IF NOT EXISTS fleet_units (
      wave_id TEXT NOT NULL, sub_id TEXT NOT NULL, scope TEXT NOT NULL, read_only INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL, merged INTEGER NOT NULL DEFAULT 0, discoveries TEXT, PRIMARY KEY (wave_id, sub_id))""",
]


def _v3_citadel(c: sqlite3.Connection) -> None:
    """v3: hook trust and gate consent, gate runs, quality-ladder evidence, campaigns and their
    sessions, fleet waves and units (new tables only; nothing existing changes)."""
    for stmt in V3_CITADEL:
        c.execute(stmt)


V4_TASK_BOARD = [
    # Kanban boards and their ordered columns; is_done marks "done columns" (search leaves their
    # tasks out unless include_done).
    """CREATE TABLE IF NOT EXISTS task_boards (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, sort_order REAL NOT NULL DEFAULT 0,
      created_at REAL NOT NULL, updated_at REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS task_columns (
      id TEXT PRIMARY KEY, board_id TEXT NOT NULL REFERENCES task_boards(id) ON DELETE CASCADE,
      name TEXT NOT NULL, sort_order REAL NOT NULL DEFAULT 0, is_done INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS task_columns_board ON task_columns(board_id, sort_order)",
    # The one global code counter (Task00001, Task00002, …): next number to hand out. Numbers are
    # taken inside a write transaction and never reused, even after a task is deleted.
    "CREATE TABLE IF NOT EXISTS task_counter (id INTEGER PRIMARY KEY CHECK (id = 1), next INTEGER NOT NULL)",
    "INSERT OR IGNORE INTO task_counter (id, next) VALUES (1, 1)",
    # labels, assignees: json lists of strings. due: YYYY-MM-DD or NULL. archived_at set = in
    # "Recently deleted" (restorable). agent_touched: the agent created or changed it at least once.
    """CREATE TABLE IF NOT EXISTS board_tasks (
      id TEXT PRIMARY KEY, num INTEGER NOT NULL UNIQUE,
      board_id TEXT NOT NULL REFERENCES task_boards(id) ON DELETE CASCADE,
      column_id TEXT NOT NULL REFERENCES task_columns(id), position REAL NOT NULL DEFAULT 0,
      title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', priority TEXT NOT NULL DEFAULT 'none',
      labels TEXT NOT NULL DEFAULT '[]', due TEXT, assignees TEXT NOT NULL DEFAULT '[]',
      created_by TEXT NOT NULL DEFAULT 'user', agent_touched INTEGER NOT NULL DEFAULT 0,
      archived_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS board_tasks_column ON board_tasks(column_id, position)",
    "CREATE INDEX IF NOT EXISTS board_tasks_board ON board_tasks(board_id, archived_at)",
    """CREATE TABLE IF NOT EXISTS task_subtasks (
      id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES board_tasks(id) ON DELETE CASCADE,
      title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS task_subtasks_task ON task_subtasks(task_id, position)",
    """CREATE TABLE IF NOT EXISTS task_checklist (
      id TEXT PRIMARY KEY, subtask_id TEXT NOT NULL REFERENCES task_subtasks(id) ON DELETE CASCADE,
      title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, position INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS task_checklist_subtask ON task_checklist(subtask_id, position)",
    # author: user | agent (by_agent marks the agent's comments); session_id: where the agent was.
    """CREATE TABLE IF NOT EXISTS task_comments (
      id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES board_tasks(id) ON DELETE CASCADE,
      author TEXT NOT NULL, by_agent INTEGER NOT NULL DEFAULT 0, body TEXT NOT NULL,
      session_id TEXT, created_at REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS task_comments_task ON task_comments(task_id, created_at)",
    """CREATE TABLE IF NOT EXISTS task_activity (
      id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES board_tasks(id) ON DELETE CASCADE,
      actor TEXT NOT NULL, action TEXT NOT NULL, text TEXT NOT NULL, session_id TEXT, ts REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS task_activity_task ON task_activity(task_id, ts)",
    # Sessions that work on a task (a session can show the tasks it's linked to).
    """CREATE TABLE IF NOT EXISTS task_sessions (
      task_id TEXT NOT NULL REFERENCES board_tasks(id) ON DELETE CASCADE, session_id TEXT NOT NULL,
      linked_at REAL NOT NULL, PRIMARY KEY (task_id, session_id))""",
    "CREATE INDEX IF NOT EXISTS task_sessions_session ON task_sessions(session_id)",
]
# The board every database starts with ("Game"); Done is its done column.
DEFAULT_BOARD = ("brd_game", "Game", [("col_backlog", "Backlog", 0), ("col_todo", "To do", 0),
                                      ("col_doing", "In progress", 0), ("col_review", "Review", 0),
                                      ("col_done", "Done", 1)])


def _v4_task_board(c: sqlite3.Connection) -> None:
    """v4: the Kanban task board (boards, columns, tasks with Task00001 codes, subtasks and
    checklists, comments, activity, linked sessions) and its default "Game" board."""
    for stmt in V4_TASK_BOARD:
        c.execute(stmt)
    if not c.execute("SELECT 1 FROM task_boards LIMIT 1").fetchone():
        ts = time.time()
        bid, name, cols = DEFAULT_BOARD
        c.execute("INSERT INTO task_boards (id, name, sort_order, created_at, updated_at) VALUES (?, ?, 0, ?, ?)",
                  [bid, name, ts, ts])
        for i, (cid, cname, done) in enumerate(cols):
            c.execute("INSERT INTO task_columns (id, board_id, name, sort_order, is_done, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?)", [cid, bid, cname, i, done, ts])


# Versioned migrations: PRAGMA user_version is the last one applied. Each runs once, in its own
# transaction together with the version bump. Append new steps; never change a released one.
MIGRATIONS: list[tuple[int, Any]] = [(1, _v1_session_columns), (2, _v2_storage), (3, _v3_citadel)]
MIGRATIONS.append((4, _v4_task_board))
SCHEMA_VERSION = MIGRATIONS[-1][0]


class DB:
    def __init__(self, path: Path | str | None = None):
        self.path = str(path or (data_dir() / "workspace.db"))
        fresh = self.path == ":memory:" or not Path(self.path).exists() or Path(self.path).stat().st_size == 0
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if fresh:  # only takes effect before the first table exists; older files switch at VACUUM
                self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self._conn.executescript(SCHEMA)
            self._migrate()

    def user_version(self) -> int:
        with self._lock:
            return self._conn.execute("PRAGMA user_version").fetchone()[0]

    def _migrate(self) -> None:
        """Bring the database up to date: the versioned MIGRATIONS it hasn't had yet, then the
        message search index (re-created on every start, see _ensure_message_search)."""
        c = self._conn
        version = c.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            log.warning("The database is at version %s, newer than this app (%s); running it as is.",
                        version, SCHEMA_VERSION)
        for v, step in MIGRATIONS:
            if version >= v:
                continue
            c.execute("BEGIN")
            try:
                step(c)
                c.execute(f"PRAGMA user_version={int(v)}")
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
            log.info("database migrated to version %s", v)
        self._ensure_message_search()

    def _ensure_message_search(self) -> None:
        """Message search index: created (and backfilled) when missing, its triggers refreshed on
        every start. Never blocks startup: without FTS5 search falls back to LIKE."""
        c = self._conn
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='messages_fts'").fetchone():
            c.execute("BEGIN")
            try:
                for stmt in MESSAGES_FTS:
                    c.execute(stmt)
                c.execute("INSERT INTO messages_fts(rowid, text, session_id, message_id) "
                          "SELECT rid, t, sid, mid FROM (SELECT m.rowid AS rid, m.session_id AS sid, m.id AS mid, "
                          f"({_MSG_TEXT.format(c='m.content')}) AS t FROM messages m) WHERE t IS NOT NULL")
                c.execute("COMMIT")
            except sqlite3.DatabaseError as e:  # e.g. SQLite without FTS5/JSON1: search falls back to LIKE
                c.execute("ROLLBACK")
                log.warning("Message search index not created (%s); searching messages falls back to LIKE "
                            "(retried at the next start).", e)
            except BaseException:
                c.execute("ROLLBACK")
                raise
        else:
            # Re-create the triggers, so a fix to _MSG_TEXT reaches databases indexed by an older version.
            c.execute("BEGIN")
            try:
                for name in FTS_TRIGGERS:
                    c.execute(f"DROP TRIGGER IF EXISTS {name}")
                for stmt in MESSAGES_FTS[1:]:
                    c.execute(stmt)
                c.execute("COMMIT")
            except sqlite3.DatabaseError as e:  # keep the old triggers; never block startup
                c.execute("ROLLBACK")
                log.warning("Couldn't refresh the message search triggers: %s", e)
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    @contextmanager
    def transaction(self) -> Iterator["DB"]:
        """All-or-nothing writes: holds the lock and a write transaction (BEGIN IMMEDIATE, so another
        process can't interleave either); commits at the end, rolls back if the block raises.
        Re-entrant: inside another transaction it just joins it."""
        with self._lock:
            if self._conn.in_transaction:
                yield self
                return
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self._conn.executemany(sql, rows)

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def insert(self, table: str, row: dict[str, Any], *, replace: bool = False) -> int:
        cols = list(row)
        vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()]
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        sql = f"{verb} INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        with self._lock:
            return self._conn.execute(sql, vals).lastrowid

    def update(self, table: str, key: str, key_val: Any, fields: dict[str, Any]) -> None:
        if not fields:
            return
        sets = ",".join(f"{k}=?" for k in fields)
        vals = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
        self.execute(f"UPDATE {table} SET {sets} WHERE {key}=?", [*vals, key_val])

    def kv_get(self, key: str, default: Any = None) -> Any:
        r = self.one("SELECT value FROM kv WHERE key=?", [key])
        return json.loads(r["value"]) if r else default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?, ?)", [key, json.dumps(value)])

    # ------------------------------------------------------------- maintenance

    def auto_vacuum_mode(self) -> str:
        with self._lock:
            mode = self._conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        return {0: "none", 1: "full", 2: "incremental"}.get(mode, str(mode))

    def free_bytes(self) -> int:
        """Space inside the file that deleted rows left behind (reclaimed by vacuuming)."""
        with self._lock:
            free = self._conn.execute("PRAGMA freelist_count").fetchone()[0]
            size = self._conn.execute("PRAGMA page_size").fetchone()[0]
        return int(free) * int(size)

    def incremental_vacuum(self) -> None:
        """Give free pages back to the filesystem (a no-op unless auto_vacuum is incremental) and
        fold the write-ahead log into the database so it shrinks too."""
        with self._lock:
            self._conn.execute("PRAGMA incremental_vacuum").fetchall()  # fetchall: runs every step
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()

    def vacuum(self) -> None:
        """Rewrite the whole file compactly. Also switches databases made before incremental
        auto-vacuum to it, so the daily maintenance can shrink them from then on."""
        with self._lock:
            self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self._conn.execute("VACUUM")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def now() -> float:
    return time.time()
