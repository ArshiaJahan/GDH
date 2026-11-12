"""Session management: migration, groups, Trash, archive, bulk actions, duplicate/fork, unread,
search and auto-titles."""
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from workspace.app import AppState
from workspace.core.types import Message, ToolResultBlock, ToolUseBlock
from workspace.providers.base import ProviderError
from workspace.providers.fake import FakeProvider, text_response
from workspace.server import create_app

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def state(tmp_path):
    return AppState(db_path=tmp_path / "t.db")


@pytest.fixture
def fake(state):
    f = FakeProvider()
    state.providers.override("anthropic", "default", f)
    return f


@pytest.fixture
def client(state):
    with TestClient(create_app(TOKEN, state)) as c:
        yield c


def wait_for(cond, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return
        time.sleep(0.02)
    raise TimeoutError


def wait_idle(client, sid):
    wait_for(lambda: not client.get(f"/api/sessions/{sid}", headers=H).json()["running"])


def new(client, **body) -> str:
    return client.post("/api/sessions", json=body, headers=H).json()["id"]


def titles(client, view="active"):
    return [s["title"] for s in client.get(f"/api/sessions?view={view}", headers=H).json()]


# ------------------------------------------------------------------ migration

OLD_SCHEMA = """
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT 'New session', created_at REAL NOT NULL,
  updated_at REAL NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, folder TEXT, model TEXT NOT NULL,
  effort TEXT NOT NULL DEFAULT 'medium', account TEXT NOT NULL DEFAULT 'default',
  mode TEXT NOT NULL DEFAULT 'ask', harness TEXT NOT NULL DEFAULT 'builtin',
  location TEXT NOT NULL DEFAULT 'local', settings TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'idle');
CREATE TABLE messages (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, role TEXT NOT NULL,
  content TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, compacted INTEGER NOT NULL DEFAULT 0);
"""


def test_migration_keeps_old_data(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(OLD_SCHEMA)
    con.execute("INSERT INTO sessions (id, title, created_at, updated_at, pinned, model) "
                "VALUES ('ses_old', 'Old one', 100, 200, 1, 'claude-opus-5-5')")
    con.execute("INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?,?,?,?,?)",
                ["msg_1", "ses_old", "user", json.dumps([{"type": "text", "text": "kumquat marmalade recipe"}]), 150])
    con.commit()
    con.close()

    s = AppState(db_path=db)
    old = s.store.get("ses_old")
    assert old["title"] == "Old one" and old["pinned"] and old["model"] == "claude-opus-5-5"
    assert old["group_id"] is None and not old["archived"] and not old["deleted"]
    assert old["activity_at"] == 150 and not old["unread"]  # backfilled: everything starts read
    assert s.store.messages("ses_old")[0].text() == "kumquat marmalade recipe"
    hits = s.store.search("kumquat")  # the FTS index was backfilled from existing messages
    assert hits and hits[0]["session_id"] == "ses_old" and hits[0]["match"] == "message"
    assert s.store.groups() == []
    s.db.close()
    s2 = AppState(db_path=db)  # running the migration again changes nothing
    assert s2.store.get("ses_old")["title"] == "Old one"
    assert len(s2.store.search("kumquat")) == 1


# --------------------------------------------------------------------- groups

def test_groups_crud_and_reorder(client, state):
    a = client.post("/api/groups", json={"name": "Work"}, headers=H).json()
    b = client.post("/api/groups", json={"name": "Home", "color": "green"}, headers=H).json()
    assert b["color"] == "green" and a["color"] in ("blue", "teal", "green", "yellow", "orange", "red", "violet")
    assert client.post("/api/groups", json={"name": " "}, headers=H).status_code == 400
    assert [g["name"] for g in client.get("/api/groups", headers=H).json()] == ["Work", "Home"]

    g = client.patch(f"/api/groups/{a['id']}", json={"name": "Job", "color": "red", "collapsed": True},
                     headers=H).json()
    assert g["name"] == "Job" and g["color"] == "red" and g["collapsed"] is True
    assert client.patch(f"/api/groups/{a['id']}", json={"color": "plaid"}, headers=H).json()["color"] == "red"

    client.post("/api/groups/reorder", json={"ids": [b["id"], a["id"]]}, headers=H)
    assert [g["name"] for g in client.get("/api/groups", headers=H).json()] == ["Home", "Job"]
    assert any(e["type"] == "groups.updated" for e in state.bus.replay(0))

    sid = new(client, title="Inside", group_id=a["id"])
    assert client.get(f"/api/sessions/{sid}", headers=H).json()["group_id"] == a["id"]
    client.delete(f"/api/groups/{a['id']}", headers=H)
    s = client.get(f"/api/sessions/{sid}", headers=H).json()
    assert s["group_id"] is None and not s["deleted"]  # ungrouped, never deleted
    assert [g["name"] for g in client.get("/api/groups", headers=H).json()] == ["Home"]
    assert client.patch(f"/api/sessions/{sid}", json={"group_id": "grp_nope"}, headers=H).status_code == 400


def test_new_group_with_sessions_and_move(client):
    s1, s2 = new(client, title="One"), new(client, title="Two")
    g = client.post("/api/groups", json={"name": "Batch", "session_ids": [s1, s2]}, headers=H).json()
    assert {s["group_id"] for s in client.get("/api/sessions", headers=H).json()} == {g["id"]}
    client.patch(f"/api/sessions/{s1}", json={"group_id": None}, headers=H)
    assert client.get(f"/api/sessions/{s1}", headers=H).json()["group_id"] is None


# ------------------------------------------------------------ bulk / archive

def test_bulk_actions_and_archive_filtering(client):
    ids = [new(client, title=t) for t in ("A", "B", "C")]
    g = client.post("/api/groups", json={"name": "G"}, headers=H).json()

    def bulk(action, sel=ids, **kw):
        return client.post("/api/sessions/bulk", json={"ids": sel, "action": action, **kw}, headers=H)

    assert bulk("move", group_id=g["id"]).json()["count"] == 3
    assert bulk("move", group_id="grp_missing").status_code == 400
    assert bulk("explode").status_code == 400
    bulk("pin", ids[:2])
    listed = client.get("/api/sessions", headers=H).json()
    assert [s["pinned"] for s in listed] == [True, True, False]
    bulk("unpin", ids[:1])

    bulk("archive", ids[1:])
    assert titles(client) == ["A"]
    assert sorted(titles(client, "archived")) == ["B", "C"]
    bulk("unarchive", ids[2:])
    assert sorted(titles(client)) == ["A", "C"]

    bulk("delete", ids[:1])
    assert titles(client) == ["C"] and titles(client, "trash") == ["A"]
    bulk("restore", ids[:1])
    assert sorted(titles(client)) == ["A", "C"]
    assert sorted(titles(client, "all")) == ["A", "B", "C"]


def test_pinned_reorder(client):
    a, b, c = (new(client, title=t) for t in ("A", "B", "C"))
    for sid in (a, b, c):
        client.patch(f"/api/sessions/{sid}", json={"pinned": True}, headers=H)
    assert titles(client) == ["C", "B", "A"]  # each new pin goes on top
    client.post("/api/sessions/reorder", json={"ids": [a, c, b]}, headers=H)
    assert titles(client) == ["A", "C", "B"]


# ------------------------------------------------------------- trash / purge

def test_soft_delete_restore_and_purge(client, state):
    sid = new(client, title="Doomed")
    state.store.add_message(sid, Message.user("see https://example.com/x"))
    state.items.index_message(sid, Message.user("see https://example.com/x"), provider="user", model=None,
                              source="user")
    assert state.db.one("SELECT COUNT(*) n FROM items WHERE session_id=? AND deleted=0", [sid])["n"] == 1

    assert client.delete(f"/api/sessions/{sid}", headers=H).json()["purged"] is False
    assert titles(client) == [] and titles(client, "trash") == ["Doomed"]
    got = client.get(f"/api/sessions/{sid}", headers=H).json()
    assert got["deleted"] and got["deleted_at"]
    assert client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}, headers=H).status_code == 409
    assert state.store.search("example") == []  # Trash is left out of search
    assert state.db.one("SELECT COUNT(*) n FROM messages WHERE session_id=?", [sid])["n"] == 1  # still there

    client.post(f"/api/sessions/{sid}/restore", headers=H)
    assert titles(client) == ["Doomed"]

    client.delete(f"/api/sessions/{sid}?purge=1", headers=H)
    assert client.get(f"/api/sessions/{sid}", headers=H).status_code == 404
    assert state.db.one("SELECT COUNT(*) n FROM messages WHERE session_id=?", [sid])["n"] == 0
    assert state.db.one("SELECT COUNT(*) n FROM messages_fts WHERE session_id=?", [sid])["n"] == 0
    assert state.db.one("SELECT COUNT(*) n FROM items WHERE session_id=? AND deleted=0", [sid])["n"] == 0
    assert any(e["type"] == "session.deleted" for e in state.bus.replay(0, sid))
    assert client.delete(f"/api/sessions/{sid}", headers=H).status_code == 404


def test_empty_trash_and_auto_purge_by_age(tmp_path):
    state = AppState(db_path=tmp_path / "a.db")
    old, recent, keep = (state.store.create(title=t)["id"] for t in ("old", "recent", "keep"))
    state.store.trash(old)
    state.store.trash(recent)
    state.db.execute("UPDATE sessions SET deleted_at=? WHERE id=?", [time.time() - 31 * 86400, old])
    with TestClient(create_app(TOKEN, state)) as c:  # startup runs the janitor once
        assert state.store.get(old) is None
        assert state.store.get(recent)["deleted"] and state.store.get(keep)
        assert c.post("/api/trash/empty", headers=H).json() == {"purged": 1}
        assert state.store.get(recent) is None and state.store.get(keep)


def test_delete_stops_the_run_and_its_approval_cards(client, state, fake):
    sid = new(client, effort="max")  # waits on an effort approval card
    client.post(f"/api/sessions/{sid}/messages", json={"text": "think"}, headers=H)
    wait_for(lambda: client.get(f"/api/approvals?session_id={sid}", headers=H).json())
    jid = state.jobs.start(sid, "command", "sleepy")
    client.delete(f"/api/sessions/{sid}", headers=H)
    assert not state.runner.is_running(sid)
    assert client.get(f"/api/approvals?session_id={sid}", headers=H).json() == []
    assert state.jobs.get(jid)["status"] == "cancelled"
    assert not fake.calls


# ----------------------------------------------------------- duplicate / fork

def _conversation(state, sid):
    state.store.update(sid, settings={"agent_sdk_session": "sdk_1", "codex_thread": "th_1", "skills": ["x"]})
    m1 = state.store.add_message(sid, Message.user("first question"))
    m2 = state.store.add_message(sid, Message.assistant(ToolUseBlock(id="tu_1", name="list_dir", input={})))
    m3 = state.store.add_message(sid, Message(role="user", meta={"tool_results": True},
                                              content=[ToolResultBlock.text("tu_1", "a.txt")]))
    m4 = state.store.add_message(sid, Message.user("second question"))
    return m1, m2, m3, m4


def test_duplicate_copies_settings_and_messages_but_not_resume_ids(client, state):
    sid = new(client, title="Orig")
    _conversation(state, sid)
    d = client.post(f"/api/sessions/{sid}/duplicate", headers=H).json()
    assert d["title"] == "Orig (copy)" and d["id"] != sid and d["forked_from"] is None
    assert d["settings"]["skills"] == ["x"]
    assert "agent_sdk_session" not in d["settings"] and "codex_thread" not in d["settings"]
    texts = [m.text() for m in state.store.messages(d["id"])]
    assert texts == [m.text() for m in state.store.messages(sid)] and len(texts) == 4
    assert {m.id for m in state.store.messages(d["id"])}.isdisjoint({m.id for m in state.store.messages(sid)})


def test_fork_copies_up_to_the_message(client, state):
    sid = new(client, title="Orig")
    m1, m2, _m3, _m4 = _conversation(state, sid)
    f = client.post(f"/api/sessions/{sid}/fork", json={"message_id": m1.id}, headers=H).json()
    assert f["forked_from"] == {"session_id": sid, "message_id": m1.id, "title": "Orig"}
    assert f["title"] == "Orig (fork)"
    assert [m.text() for m in state.store.messages(f["id"])] == ["first question"]
    assert "agent_sdk_session" not in f["settings"] and "codex_thread" not in f["settings"]
    # Forking at a tool call keeps the results that answer it, so the fork's history stays valid.
    f2 = client.post(f"/api/sessions/{sid}/fork", json={"message_id": m2.id}, headers=H).json()
    msgs = state.store.messages(f2["id"])
    assert len(msgs) == 3 and msgs[-1].meta.get("tool_results")
    assert state.store.repair_dangling_tool_calls(f2["id"]) == 0
    assert client.post(f"/api/sessions/{sid}/fork", json={"message_id": "msg_nope"}, headers=H).status_code == 400


# --------------------------------------------------------------------- unread

def test_unread_after_a_turn_and_read_marks(client, state, fake):
    fake.script = [text_response("done!")]
    sid = new(client)
    assert client.get(f"/api/sessions/{sid}", headers=H).json()["unread"] is False  # empty: never unread
    client.post(f"/api/sessions/{sid}/messages", json={"text": "go"}, headers=H)
    wait_idle(client, sid)
    assert client.get(f"/api/sessions/{sid}", headers=H).json()["unread"] is True  # reply nobody has seen
    assert client.post(f"/api/sessions/{sid}/read", headers=H).json()["unread"] is False
    assert client.post(f"/api/sessions/{sid}/unread", headers=H).json()["unread"] is True
    # Sending a message counts as reading the session.
    fake.script = [text_response("again")]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "more"}, headers=H)
    assert state.store.get(sid)["last_read_at"] > 0
    wait_idle(client, sid)
    assert client.post(f"/api/sessions/{sid}/read", headers=H).json()["unread"] is False
    empty = new(client)
    assert client.post(f"/api/sessions/{empty}/unread", headers=H).json()["unread"] is True


def test_last_error_is_set_and_cleared(client, state, fake):
    def boom(_req):
        raise ProviderError("overloaded")

    fake.script = [boom]
    sid = new(client)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "go"}, headers=H)
    wait_idle(client, sid)
    assert "overloaded" in client.get(f"/api/sessions/{sid}", headers=H).json()["last_error"]
    fake.script = [text_response("ok")]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "again"}, headers=H)
    wait_idle(client, sid)
    assert client.get(f"/api/sessions/{sid}", headers=H).json()["last_error"] is None


# --------------------------------------------------------------------- search

def test_search_titles_and_message_text(client, state):
    a = new(client, title="Budget planning")
    b = new(client, title="Misc")
    state.store.add_message(b, Message.user("Let's compare the quarterly budget against forecasts"))
    c = new(client, title="Other")
    state.store.add_message(c, Message.user("nothing relevant here"))
    hits = client.get("/api/sessions/search?q=budget", headers=H).json()
    assert [(h["session_id"], h["match"]) for h in hits] == [(a, "title"), (b, "message")]
    snip = hits[1]["snippet"]
    assert "\x02budget\x03" in snip and "<" not in snip
    assert client.get("/api/sessions/search?q=quarter", headers=H).json()[0]["session_id"] == b  # prefix
    assert client.get("/api/sessions/search?q=%22%29(*", headers=H).json() == []  # junk is safe
    assert client.get("/api/sessions/search?q=", headers=H).json() == []
    state.store.update(b, archived=True)  # archived sessions stay searchable
    assert client.get("/api/sessions/search?q=forecasts", headers=H).json()[0]["archived"] is True


# ----------------------------------------------------------------- auto-title

@pytest.mark.auto_title
def test_auto_title_uses_fast_tier_at_low_effort(client, state, fake):
    fake.script = [text_response("Here is a plan for your trip."), text_response('"Weekend Trip to Lisbon."')]
    sid = new(client)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "help me plan a weekend in lisbon"}, headers=H)
    wait_idle(client, sid)
    wait_for(lambda: state.store.get(sid)["title"] == "Weekend Trip to Lisbon")
    call = fake.calls[1]
    assert call.model == state.config.resolve("claude.fast") and call.effort == "low"
    row = state.db.one("SELECT * FROM usage_records WHERE session_id=? AND role='title'", [sid])
    assert row["ok"] == 1 and row["model"] == call.model and row["effort"] == "low"
    assert state.store.get(sid)["settings"]["title_source"] == "auto"
    # Only once: the next turn doesn't rename it again.
    fake.script = [text_response("more")]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "and food?"}, headers=H)
    wait_idle(client, sid)
    time.sleep(0.1)
    assert len(fake.calls) == 3 and state.store.get(sid)["title"] == "Weekend Trip to Lisbon"


@pytest.mark.auto_title
def test_auto_title_failure_never_fails_the_turn(client, state, fake):
    def boom(_req):
        raise ProviderError("no key")

    fake.script = [text_response("Answer."), boom]
    sid = new(client)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "hello there"}, headers=H)
    wait_idle(client, sid)
    wait_for(lambda: state.db.one("SELECT COUNT(*) n FROM usage_records WHERE role='title'")["n"] == 1)
    msgs = client.get(f"/api/sessions/{sid}/messages", headers=H).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"] and not msgs[1]["meta"].get("error")
    s = client.get(f"/api/sessions/{sid}", headers=H).json()
    assert s["title"] == "hello there" and s["last_error"] is None
    assert state.db.one("SELECT ok FROM usage_records WHERE role='title'")["ok"] == 0


@pytest.mark.auto_title
def test_manual_title_is_kept_and_regenerate(client, state, fake):
    sid = new(client)
    client.patch(f"/api/sessions/{sid}", json={"title": "My name"}, headers=H)
    fake.script = [text_response("Reply."), text_response("Better Title Here")]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}, headers=H)
    wait_idle(client, sid)
    time.sleep(0.1)
    assert state.store.get(sid)["title"] == "My name" and len(fake.calls) == 1
    s = client.post(f"/api/sessions/{sid}/title", headers=H).json()  # "Regenerate title"
    assert s["title"] == "Better Title Here" and fake.calls[-1].effort == "low"
    empty = new(client)
    assert client.post(f"/api/sessions/{empty}/title", headers=H).status_code == 400


@pytest.mark.auto_title
def test_auto_title_respects_config(client, state, fake):
    state.config.sessions["auto_title"] = False  # [sessions] auto_title = false
    fake.script = [text_response("Reply.")]
    sid = new(client)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}, headers=H)
    wait_idle(client, sid)
    time.sleep(0.1)
    assert len(fake.calls) == 1 and state.store.get(sid)["title"] == "hi"
