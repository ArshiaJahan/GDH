"""Regression tests for the second review's backend findings (A1-A8, B1-B4)."""
import asyncio
import json
import logging
import os
import stat
import time

import keyring
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from gamedevworkstation import db as db_mod
from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.config import save_config_patch
from gamedevworkstation.core.types import ChatRequest, Message, Response, Usage
from gamedevworkstation.db import DB, now
from gamedevworkstation.features import sessions_mgmt, skill_assistant
from gamedevworkstation.features.harnesses import Harnesses
from gamedevworkstation.features.status import StatusChecker
from gamedevworkstation.providers.base import ProviderError
from gamedevworkstation.providers.fake import FakeProvider, text_response
from gamedevworkstation.server import create_app
from gamedevworkstation.usage import BudgetExceeded

from .test_settings import MemoryKeyring

H = {"Authorization": "Bearer t"}
TWO = {"anthropic": ["default", "work"], "openai": ["default", "work"], "elevenlabs": ["default", "second"]}


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "r2.db")
    a.providers.override("anthropic", "default", FakeProvider("anthropic"))
    a.providers.override("openai", "default", FakeProvider("openai"))
    from gamedevworkstation.routes import register_routes

    register_routes(FastAPI(), APIRouter(), a)
    return a


@pytest.fixture
def client(tmp_path):
    s = AppState(db_path=tmp_path / "c.db")
    s.providers.override("anthropic", "default", FakeProvider("anthropic"))
    with TestClient(create_app("t", s)) as c:
        yield c, s


def _spend(app, usd, sid=None):
    app.usage.record(provider="anthropic", model="claude-haiku-5-5", usage=Usage(cost_usd=usd), session_id=sid)


def wait_idle(c, sid):
    for _ in range(300):
        if not c.get(f"/api/sessions/{sid}", headers=H).json()["running"]:
            return
        time.sleep(0.03)
    raise TimeoutError


async def _until(cond, timeout=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return
        await asyncio.sleep(0.02)
    raise TimeoutError


# ----------------------------------------------------------------- A1 SDK budget


def test_headroom_counts_resume_allowances_and_run_cap(app):
    sid = app.store.create()["id"]
    app.config.limits.update(global_daily_usd=0, session_usd=0)
    assert app.usage.headroom(sid) is None  # no limit set
    app.config.limits["session_usd"] = 0.05
    _spend(app, 0.06, sid)
    assert app.usage.headroom(sid) == pytest.approx(-0.01)
    app.usage.resume_session(sid)  # another limit's worth
    assert app.usage.headroom(sid) == pytest.approx(0.05)
    app.config.limits["global_daily_usd"] = 0.08  # the daily limit is tighter now
    assert app.usage.headroom(sid) == pytest.approx(0.02)
    _spend(app, 0.01, None)
    assert app.usage.headroom(sid, run_id="r1", run_cap=0.005) == pytest.approx(0.005)


@pytest.fixture
def sdk(monkeypatch):
    import claude_agent_sdk as sdk_mod
    from claude_agent_sdk import AssistantMessage, ResultMessage
    from claude_agent_sdk import TextBlock as T

    seen: list[dict] = []

    async def fake_query(*, prompt, options=None, transport=None):
        rec = {"opts": options}
        async for m in prompt:
            rec["prompt"] = m["message"]["content"]
        seen.append(rec)
        yield AssistantMessage(content=[T(text=f"reply {len(seen)}")], model="claude-sonnet-5-5")
        yield ResultMessage(subtype="success", duration_ms=10, duration_api_ms=10, is_error=False, num_turns=1,
                            session_id=f"sdk_{len(seen)}", total_cost_usd=0.0, usage={})

    monkeypatch.setattr(sdk_mod, "query", fake_query)
    return seen


def _sdk_session(c, tmp_path):
    folder = tmp_path / "p"
    folder.mkdir(exist_ok=True)
    sid = c.post("/api/sessions", json={"folder": str(folder), "model": "claude-sonnet-5-5", "mode": "plan"},
                 headers=H).json()["id"]
    c.patch(f"/api/sessions/{sid}", json={"harness": "agent_sdk"}, headers=H)
    return sid


def test_agent_sdk_budget_after_resume_anyway(client, sdk, tmp_path):
    c, s = client
    sid = _sdk_session(c, tmp_path)
    s.config.limits.update(global_daily_usd=0, session_usd=0)
    c.post(f"/api/sessions/{sid}/messages", json={"text": "one"}, headers=H)
    wait_idle(c, sid)
    assert sdk[-1]["opts"].max_budget_usd is None  # no limit set
    s.config.limits["session_usd"] = 0.05
    _spend(s, 0.06, sid)
    s.usage.resume_session(sid)  # "Resume anyway"
    c.post(f"/api/sessions/{sid}/messages", json={"text": "two"}, headers=H)
    wait_idle(c, sid)
    assert sdk[-1]["opts"].max_budget_usd == pytest.approx(0.05)  # was None: unlimited after resume


# ------------------------------------------------------------- A2 subagent backoff


class SpendingFlaky(FakeProvider):
    """429 once; meanwhile the session spends past its limit."""

    def __init__(self, app, sid):
        super().__init__("anthropic")
        self.app, self.sid, self.attempts = app, sid, 0

    async def complete(self, req: ChatRequest) -> Response:
        self.attempts += 1
        if self.attempts == 1:
            _spend(self.app, 1.0, self.sid)
            raise ProviderError("429", status=429, rate_limited=True, retry_after=0.01)
        return await super().complete(req)


async def test_subagent_backoff_rechecks_limits_before_retrying(app):
    s = app.store.create()
    app.config.limits["session_usd"] = 0.5
    flaky = SpendingFlaky(app, s["id"])
    app.providers.override("anthropic", "default", flaky)
    ctx = ToolContext(app=app, session=s, run_id=f"main:{s['id']}")
    await app.tools.run(ctx, "spawn_subagent", {"name": "x", "tier": "claude.fast", "instructions": "y"})
    sub = next(iter(app.extensions["subagents"].subs.values()))
    await asyncio.wait_for(sub.done_event.wait(), 5)
    assert flaky.attempts == 1 and sub.status == "failed" and "Session spend limit" in sub.error


# ------------------------------------------------------- A3/A4 usage profiles


async def test_main_loop_failure_billed_to_the_turns_profile(app):
    s = app.store.create()

    class Down(FakeProvider):
        async def stream(self, req):
            raise ProviderError("boom", status=500)
            yield  # pragma: no cover

    req = ChatRequest(model="claude-haiku-5-5", messages=[Message.user("hi")])
    with pytest.raises(ProviderError):
        await app.runner._stream_with_backoff(s["id"], "work", Down(), req, "anthropic", "claude-haiku-5-5",
                                              f"main:{s['id']}", "low")
    row = app.db.one("SELECT profile, ok FROM usage_records WHERE session_id=?", [s["id"]])
    assert row == {"profile": "work", "ok": 0}


async def test_auto_title_uses_the_sessions_profile_for_the_title_provider(tmp_path):
    a = AppState(config=save_config_patch({"accounts": TWO}), db_path=tmp_path / "t.db")
    oa = next(k for k, v in a.config.models.items() if v.provider == "openai")
    a.config.tiers["claude.fast"] = oa  # the title model is an OpenAI one
    work, default = FakeProvider("openai", script=[text_response("Work title")]), FakeProvider("openai")
    a.providers.override("openai", "work", work)
    a.providers.override("openai", "default", default)
    s = a.store.create()
    a.store.update(s["id"], accounts={"openai": "work"})  # the Anthropic profile stays default
    a.store.add_message(s["id"], Message.user("hello"))
    a.store.add_message(s["id"], Message.assistant("hi there"))
    assert await sessions_mgmt.Titler(a).generate(s["id"]) == "Work title"
    assert work.calls and not default.calls
    assert a.db.one("SELECT profile FROM usage_records WHERE role='title'")["profile"] == "work"


async def test_skill_assistant_records_the_profile_it_used(tmp_path):
    a = AppState(config=save_config_patch({"accounts": {"anthropic": ["main", "default"]}}), db_path=tmp_path / "s.db")
    a.providers.override("anthropic", "main", FakeProvider("anthropic", script=[text_response("done")]))
    skill_assistant.register(FastAPI(), APIRouter(), a)
    run = a.extensions["skill_assistant"].start("skill", "anything")
    await run.task
    rows = a.db.all("SELECT profile FROM usage_records WHERE run_id=?", [run.id])
    assert rows and {r["profile"] for r in rows} == {"main"}


# ------------------------------------------------------------- A5 profiles list


def test_posting_a_stale_profile_list_never_deletes_keys(tmp_path, monkeypatch):
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    monkeypatch.delenv("GDW_NO_KEYCHAIN")

    async def no_check(self, only=None):
        return []

    monkeypatch.setattr(StatusChecker, "check_all", no_check)
    s = AppState(config=save_config_patch({"accounts": TWO}), db_path=tmp_path / "k.db")
    with TestClient(create_app("t", s)) as c:
        c.post("/api/settings/keys", json={"provider": "openai", "profile": "work", "key": "sk-work-key-dummy"},
               headers=H)
        st = c.post("/api/settings/accounts/openai", json={"profiles": ["default"]}, headers=H).json()  # stale page
        assert [p["profile"] for p in st["accounts"]["openai"]] == ["default", "work"]
        assert ("GameDevWorkstation", "openai:work") in kr.d
        st = c.post("/api/settings/accounts/openai", json={"profiles": ["work"]}, headers=H).json()  # star
        assert [p["profile"] for p in st["accounts"]["openai"]] == ["work", "default"]
        st = c.post("/api/settings/accounts/openai", json={"profiles": ["work", "default", "new"]}, headers=H).json()
        assert [p["profile"] for p in st["accounts"]["openai"]] == ["work", "default", "new"]  # Add profile
        assert ("GameDevWorkstation", "openai:work") in kr.d


# ---------------------------------------------------------- A6 codex turn cancel


async def test_cancelled_codex_turn_kills_the_process_tree(app, tmp_path):
    s = app.store.create(folder=str(tmp_path))
    h = Harnesses(app)
    task = asyncio.create_task(h._codex_turn(s, ["sh", "-c", "sleep 30 & sleep 30"], "hi", "gpt-6.1-sol", "low"))
    await _until(lambda: bool(app.jobs.procs))
    proc = next(iter(app.jobs.procs.values()))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(proc.wait(), 3)
    with pytest.raises(ProcessLookupError):  # the whole group, not just the shell
        for _ in range(100):
            os.killpg(proc.pid, 0)
            await asyncio.sleep(0.03)


# ------------------------------------------------------------- A7 resume no-op


def test_resume_is_a_noop_when_not_paused(app):
    app.config.limits["global_daily_usd"] = 1.0
    app.config.limits["session_usd"] = 0.5
    sid = app.store.create()["id"]
    _spend(app, 0.4, sid)
    seq = app.bus.last_seq()
    app.usage.resume_all()
    app.usage.resume_session(sid)
    assert [e for e in app.bus.replay(seq) if e["type"] == "limits.resumed"] == []
    _spend(app, 0.11, sid)  # resuming early must not have moved the session limit to 0.4 + 0.5
    with pytest.raises(BudgetExceeded):
        app.usage.check(sid)


# ------------------------------------------------------------ A8 validation 400s


def test_bad_session_and_group_bodies_are_400s(client):
    c, s = client
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    ok = c.patch(f"/api/sessions/{sid}", json={"settings": {"accounts": None}}, headers=H)
    assert ok.status_code == 200 and ok.json()["settings"]["accounts"]["anthropic"] == "default"
    for body in ({"settings": {"accounts": {"anthropic": "nope"}}}, {"settings": {"accounts": "x"}},
                 {"settings": "x"}, {"account": "nope"}, {"account": None}, {"sort_order": "abc"},
                 {"sort_order": [1]}):
        assert c.patch(f"/api/sessions/{sid}", json=body, headers=H).status_code == 400, body
    g = c.post("/api/groups", json={"name": "G"}, headers=H).json()
    r = c.patch(f"/api/groups/{g['id']}", json={"gid": "other", "name": "H"}, headers=H)
    assert r.status_code == 200 and r.json()["name"] == "H"
    assert c.patch(f"/api/groups/{g['id']}", json={"sort_order": "abc"}, headers=H).status_code == 400
    assert c.patch(f"/api/groups/{g['id']}", json={"sort_order": 3}, headers=H).json()["sort_order"] == 3
    for ids in ([1], [{"a": 1}], "abc", 5):
        assert c.post("/api/groups", json={"name": "X", "session_ids": ids}, headers=H).status_code == 400, ids
    assert [g["name"] for g in c.get("/api/groups", headers=H).json()] == ["H"]  # nothing half-created


# --------------------------------------------------------------- B1 fork history


def _msgs(app, sid, base, items):
    out = {}
    for i, (key, role, text, meta) in enumerate(items):
        m = Message(role=role, content=[Message.user(text).content[0]], meta=meta or {})
        app.store.add_message(sid, m, created_at=base + i)
        out[key] = m.id
    return out


def _visible(app, sid):
    return [m.text() for m in app.store.messages(sid, include_compacted=False)]


def test_fork_from_before_a_compaction_keeps_the_history_the_model_saw(app):
    s = app.store.create()
    sid, base = s["id"], now() - 1000
    ids = _msgs(app, sid, base, [("u1", "user", "u1", None), ("a1", "assistant", "a1", None),
                                 ("u2", "user", "u2", None), ("a2", "assistant", "a2", None),
                                 ("u3", "user", "u3", None), ("a3", "assistant", "a3", None)])
    # First compaction: u1/a1 into S1 (just before u2). Second: S1, u2, a2 into S2 (just before u3).
    app.store.mark_compacted([ids["u1"], ids["a1"]])
    app.store.add_message(sid, Message(role="user", content=Message.user("S1").content, meta={"summary": True}),
                          created_at=base + 2 - 0.0005)
    s1 = app.store.messages(sid)[2].id
    app.store.mark_compacted([s1, ids["u2"], ids["a2"]])
    app.store.add_message(sid, Message(role="user", content=Message.user("S2").content, meta={"summary": True}),
                          created_at=base + 4 - 0.0005)
    assert _visible(app, sid) == ["S2", "u3", "a3"]
    assert _visible(app, app.store.fork(sid, ids["a2"])["id"]) == ["S1", "u2", "a2"]  # was []
    assert _visible(app, app.store.fork(sid, ids["a1"])["id"]) == ["u1", "a1"]
    assert _visible(app, app.store.fork(sid, ids["a3"])["id"]) == ["S2", "u3", "a3"]
    full = app.store.duplicate(sid)  # a full copy keeps every flag
    assert _visible(app, full["id"]) == ["S2", "u3", "a3"]
    assert len(app.store.messages(full["id"])) == 8


def test_fork_from_before_a_clear(app):
    sid = app.store.create()["id"]
    ids = _msgs(app, sid, now() - 1000, [("u1", "user", "u1", None), ("a1", "assistant", "a1", None)])
    app.store.clear(sid)
    u2 = app.store.add_message(sid, Message.user("u2")).id
    assert _visible(app, sid) == ["u2"]
    early = app.store.fork(sid, ids["a1"])
    assert _visible(app, early["id"]) == ["u1", "a1"]  # the clear came later
    assert _visible(app, app.store.fork(sid, u2)["id"]) == ["u2"]  # the clear came before
    # The early fork forgets the later clear, so forking it again keeps everything.
    u3 = app.store.add_message(early["id"], Message.user("u3")).id
    assert _visible(app, app.store.fork(early["id"], u3)["id"]) == ["u1", "a1", "u3"]


# -------------------------------------------------------- B2 recap for new threads


FAKE_CODEX = r"""#!/usr/bin/env python3
import json, sys, os
args = sys.argv[1:]
prompt = sys.stdin.read()
open(os.environ["FAKE_CODEX_LOG"], "a").write(json.dumps({"args": args, "prompt": prompt}) + "\n")
def emit(o): print(json.dumps(o), flush=True)
emit({"type": "thread.started", "thread_id": "thr_1"})
emit({"type": "item.completed", "item": {"id": "i3", "type": "agent_message", "text": "codex says hi"}})
emit({"type": "turn.completed", "usage": {"input_tokens": 20, "cached_input_tokens": 0, "output_tokens": 3}})
"""


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "codex"
    exe.write_text(FAKE_CODEX)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "codex.log"
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    return log


def test_codex_copy_gets_a_recap_of_the_copied_history(client, fake_codex, tmp_path):
    c, s = client
    s.config.modes["allowlist"] = ["codex_cli:*"]  # Accept edits asks for each Codex CLI turn otherwise
    sid = c.post("/api/sessions", json={"folder": str(tmp_path), "mode": "accept_edits"}, headers=H).json()["id"]
    c.patch(f"/api/sessions/{sid}", json={"harness": "codex_cli"}, headers=H)
    c.post(f"/api/sessions/{sid}/messages", json={"text": "remember the number 42"}, headers=H)
    wait_idle(c, sid)
    calls = lambda: [json.loads(x) for x in fake_codex.read_text().splitlines()]  # noqa: E731
    assert calls()[0]["prompt"] == "remember the number 42"  # nothing earlier: no recap
    copy = c.post(f"/api/sessions/{sid}/duplicate", headers=H).json()["id"]
    c.post(f"/api/sessions/{copy}/messages", json={"text": "which number?"}, headers=H)
    wait_idle(c, copy)
    last = calls()[-1]
    assert "resume" not in last["args"]
    p = last["prompt"]
    assert p.startswith("Earlier in this conversation:") and "remember the number 42" in p and "codex says hi" in p
    assert p.endswith("Now: which number?")
    c.post(f"/api/sessions/{sid}/messages", json={"text": "again"}, headers=H)  # the original resumes
    wait_idle(c, sid)
    assert calls()[-1]["prompt"] == "again" and "resume" in calls()[-1]["args"]


def test_agent_sdk_fork_gets_a_bounded_recap(client, sdk, tmp_path):
    c, s = client
    sid = _sdk_session(c, tmp_path)
    c.post(f"/api/sessions/{sid}/messages", json={"text": "first " + "x" * 5000}, headers=H)
    wait_idle(c, sid)
    assert sdk[-1]["prompt"].startswith("first ") and sdk[-1]["opts"].resume is None
    last = c.get(f"/api/sessions/{sid}/messages", headers=H).json()[-1]["id"]
    fork = c.post(f"/api/sessions/{sid}/fork", json={"message_id": last}, headers=H).json()["id"]
    c.post(f"/api/sessions/{fork}/messages", json={"text": "and now?"}, headers=H)
    wait_idle(c, fork)
    p = sdk[-1]["prompt"]
    assert sdk[-1]["opts"].resume is None and p.startswith("Earlier in this conversation:")
    assert "reply 1" in p and p.endswith("Now: and now?") and len(p) < 1000  # each message is cut short
    c.post(f"/api/sessions/{sid}/messages", json={"text": "next"}, headers=H)  # the original resumes
    wait_idle(c, sid)
    assert sdk[-1]["prompt"] == "next" and sdk[-1]["opts"].resume == "sdk_1"


# ------------------------------------------------------------------ B3 FTS JSON


BAD = json.dumps(["just a string", 7, {"type": "text", "text": "findable words"}])


def _raw_message(d: DB, sid: str, content: str = BAD) -> None:
    d.insert("messages", {"id": f"msg_{time.time_ns()}", "session_id": sid, "role": "user", "content": content,
                          "meta": "{}", "created_at": now()})


def _session(d: DB) -> str:
    sid = f"ses_{time.time_ns()}"
    d.insert("sessions", {"id": sid, "title": "t", "created_at": now(), "updated_at": now(), "pinned": 0,
                          "model": "m", "effort": "low", "account": "default", "mode": "ask", "harness": "builtin",
                          "location": "local", "settings": "{}"})
    return sid


def _fts_hits(d: DB, q: str) -> int:
    return d.one("SELECT COUNT(*) AS n FROM messages_fts WHERE messages_fts MATCH ?", [q])["n"]


def test_non_object_content_elements_dont_break_the_index(tmp_path):
    d = DB(tmp_path / "f.db")
    _raw_message(d, _session(d))  # the insert trigger used to raise "malformed JSON"
    assert _fts_hits(d, "findable") == 1


def test_backfill_survives_non_object_elements_and_old_triggers_are_replaced(tmp_path):
    p = tmp_path / "old.db"
    d = DB(p)
    sid = _session(d)
    # An older database: no index yet, a message the old backfill choked on.
    for t in db_mod.FTS_TRIGGERS:
        d.execute(f"DROP TRIGGER {t}")
    d.execute("DROP TABLE messages_fts")
    _raw_message(d, sid)
    d.close()
    d = DB(p)
    assert _fts_hits(d, "findable") == 1  # was: index silently never created
    # An index made by the old version keeps the old trigger until the next start replaces it.
    old = ("SELECT group_concat(json_extract(j.value, '$.text'), ' ') AS t FROM json_each(CASE WHEN "
           "json_valid(new.content) THEN new.content ELSE '[]' END) j WHERE json_extract(j.value, '$.type') = 'text'")
    d.execute("DROP TRIGGER messages_fts_ai")
    d.execute("CREATE TRIGGER messages_fts_ai AFTER INSERT ON messages BEGIN INSERT INTO messages_fts(rowid, "
              f"text, session_id, message_id) SELECT new.rowid, t, new.session_id, new.id FROM ({old}) "
              "WHERE t IS NOT NULL; END")
    with pytest.raises(Exception, match="malformed JSON"):
        _raw_message(d, sid)
    d.close()
    d = DB(p)
    _raw_message(d, sid)
    assert _fts_hits(d, "findable") == 2


def test_fts_creation_failure_is_logged(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(db_mod, "MESSAGES_FTS", ["CREATE VIRTUAL TABLE messages_fts USING no_such_module(x)"])
    with caplog.at_level(logging.WARNING, logger="gamedevworkstation.db"):
        DB(tmp_path / "w.db")
    assert any("search index not created" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------- B4 empty trash


def test_empty_trash_skips_a_session_restored_meanwhile(client, monkeypatch):
    c, s = client
    a = c.post("/api/sessions", json={"title": "A"}, headers=H).json()["id"]
    b = c.post("/api/sessions", json={"title": "B"}, headers=H).json()["id"]
    c.delete(f"/api/sessions/{a}", headers=H)
    c.delete(f"/api/sessions/{b}", headers=H)
    real = sessions_mgmt.purge_session
    order: list[str] = []

    async def slow_purge(app_, sid):
        order.append(sid)
        if len(order) == 1:  # the user restores the other one while the first is being purged
            app_.store.restore(b if sid == a else a)
        await real(app_, sid)

    monkeypatch.setattr(sessions_mgmt, "purge_session", slow_purge)
    assert c.post("/api/trash/empty", headers=H).json() == {"purged": 1}
    survivor = b if order[0] == a else a
    assert s.store.get(survivor) and not s.store.get(order[0])
