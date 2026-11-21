import asyncio
import json
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.agent.tools import ToolContext, ToolOutput
from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Message, Usage
from gamedevworkstation.features import claude_code, subagents
from gamedevworkstation.features.sessions_mgmt import Titler
from gamedevworkstation.features.task_board import TaskBoard
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response
from gamedevworkstation.server import create_app
from gamedevworkstation.usage import BudgetExceeded

H = {"Authorization": "Bearer t"}
URL = "/api/usage/attribution"


@pytest.fixture
def app(tmp_path, cfg):
    cfg.tracing["enabled"] = False
    cfg.limits.update(global_daily_usd=0, session_usd=0, task_usd=0)
    state = AppState(config=cfg, db_path=tmp_path / "ledger.db")
    yield state
    state.db.close()


def _record(app, sid, cost, *, provider="anthropic", **kwargs):
    return app.usage.record(provider=provider, model="model", session_id=sid, usage=Usage(cost_usd=cost), **kwargs)


async def test_task_spend_snapshot_survives_relink(app):
    sid = app.store.create()["id"]
    board = TaskBoard(app)
    first = board.create(title="First task")
    second = board.create(title="Second task")
    first_id, second_id = first["id"], second["id"]
    board.attach(first_id, sid)
    launch = asyncio.Event()

    async def unit(captured):
        await launch.wait()
        with app.usage.scope(captured=captured):
            tool = _record(app, sid, 0.5, role="tool")
            explicit_run = _record(app, sid, 0.25, role="tool", run_id="other")
        return tool, explicit_run

    with app.usage.scope(sid) as turn:
        main = _record(app, sid, 1)
        queued = asyncio.create_task(unit(app.usage.capture_scope(sid, run_id="sub-1")))
        board.unlink(first_id, sid)
        board.link(second_id, sid)
    board.archive(first_id)
    board.delete(first_id)
    launch.set()
    tool, explicit_run = await queued
    assert main["task_id"] == tool["task_id"] == explicit_run["task_id"] == first_id
    assert main["task_attribution"] == tool["task_attribution"] == "explicit"
    assert (tool["role"], tool["run_id"], explicit_run["run_id"]) == ("tool", "sub-1", "other")

    with app.usage.scope(sid):
        with app.usage.scope(sid, run_id="sub-1"):
            resumed = _record(app, sid, 3, role="tool")
        late_result = _record(app, sid, 0.25, scope=turn)
        app.config.limits["task_usd"] = 2.5
        with pytest.raises(BudgetExceeded, match=second["code"]):
            app.usage.check(sid)
        app.usage.check(sid, scope=turn)
        assert app.usage.headroom(sid, scope=turn) == 0.5
    assert (resumed["task_id"], resumed["task_attribution"]) == (second_id, "sole_link")
    assert late_result["task_id"] == first_id
    assert app.usage.spent_task(first_id) == 2
    assert app.usage.spent_task(second_id) == 3
    assert app.usage.spent_run("sub-1") == 3.5


@pytest.mark.parametrize("role", ["main", "title"])
async def test_in_flight_request_keeps_its_entry_task(app, role):
    session = app.store.create(model="claude.fast")
    sid = session["id"]
    board = TaskBoard(app)
    first = board.create(title="First task")
    second = board.create(title="Second task")
    board.link(first["id"], sid)
    app.config.limits["task_usd"] = 5
    started, release = asyncio.Event(), asyncio.Event()

    class BlockingProvider(FakeProvider):
        async def complete(self, req):
            response = await super().complete(req)
            started.set()
            await release.wait()
            return response

    fake = BlockingProvider(script=[text_response("done", usage=Usage(cost_usd=1))])
    app.providers.override("anthropic", "default", fake)
    app.store.add_message(sid, Message.user("Do the first task."))
    request = app.runner.start(sid) if role == "main" else asyncio.create_task(Titler(app).generate(sid, force=True))
    try:
        await asyncio.wait_for(started.wait(), 2)
        board.unlink(first["id"], sid)
        board.link(second["id"], sid)
    finally:
        release.set()
        await asyncio.wait_for(request, 2)

    row = app.db.one("SELECT task_id, task_attribution, role FROM usage_records WHERE session_id=?", [sid])
    assert row == {"task_id": first["id"], "task_attribution": "sole_link", "role": role}
    assert app.usage.spent_task(first["id"]) == 1
    assert app.usage.spent_task(second["id"]) == 0
    assert len(fake.calls) == 1


async def test_queued_api_unit_and_followup_use_their_own_task_snapshots(app):
    session = app.store.create(model="claude.fast")
    sid = session["id"]
    board = TaskBoard(app)
    first = board.create(title="First task")
    second = board.create(title="Second task")
    board.link(first["id"], sid)
    manager = subagents.SubagentManager(app)
    subagents._register_tools(app, manager)
    pool = manager.pools["api"] = asyncio.Semaphore(1)
    ctx = ToolContext(app=app, session=session, run_id=f"main:{sid}")
    fake = FakeProvider(script=[tool_response("test_usage_tool", {}), text_response("done"), text_response("resumed")])
    app.providers.override("anthropic", "default", fake)

    @app.tools.add("test_usage_tool", "Record tool usage", {"type": "object", "properties": {}}, read_only=True)
    async def test_usage_tool(ctx, _args):
        _record(app, ctx.session_id, 0.5, role="tool")
        return ToolOutput("done")

    async with pool:
        unit = await manager.spawn(ctx, {"instructions": "First task", "tools": ["test_usage_tool"]})
        await asyncio.sleep(0)
        assert unit.status == "queued"
        board.unlink(first["id"], sid)
        board.link(second["id"], sid)
    await asyncio.wait_for(unit.task, 2)
    assert unit.status == "done", unit.error

    out = await app.tools.run(ctx, "message_subagent", {"id": unit.id, "message": "Second task"})
    assert not out.is_error
    await asyncio.wait_for(unit.task, 2)
    assert unit.status == "done", unit.error

    rows = app.db.all("SELECT task_id, role, run_id FROM usage_records WHERE session_id=? ORDER BY id", [sid])
    assert [(row["task_id"], row["role"], row["run_id"]) for row in rows] == [
        (first["id"], "subagent", unit.id),
        (first["id"], "tool", unit.id),
        (first["id"], "subagent", unit.id),
        (second["id"], "subagent", unit.id),
    ]


async def test_queued_codex_cli_rechecks_captured_task_at_launch(app, tmp_path, monkeypatch):
    session = app.store.create(folder=str(tmp_path))
    sid = session["id"]
    ctx = ToolContext(app=app, session=session, run_id=f"main:{sid}")
    board = TaskBoard(app)
    first = board.create(title="First task")
    second = board.create(title="Second task")
    board.link(first["id"], sid)
    app.config.limits["task_usd"] = 5
    manager = subagents.SubagentManager(app)
    pool = manager.pools["codex_cli"] = asyncio.Semaphore(1)
    launches = []

    async def is_repo(_folder):
        return True

    async def create_worktree(_folder, _root, _sub_id):
        return tmp_path

    async def launch(*args, **_kwargs):
        launches.append(args)
        raise AssertionError("The capped unit must not dispatch")

    monkeypatch.setattr(subagents.shutil, "which", lambda _name: "/fake/codex")
    monkeypatch.setattr(app.approvals, "allowlisted", lambda *_args: True)
    monkeypatch.setattr(subagents.worktrees, "is_repo", is_repo)
    monkeypatch.setattr(subagents.worktrees, "create", create_worktree)
    monkeypatch.setattr(subagents.asyncio, "create_subprocess_exec", launch)
    async with pool:
        unit = await manager.spawn(ctx, {"tier": "codex.cli", "instructions": "Run once"})
        await asyncio.sleep(0)
        assert unit.status == "queued"
        _record(app, sid, 5)
        board.unlink(first["id"], sid)
        board.link(second["id"], sid)
    await asyncio.wait_for(unit.task, 2)
    assert unit.status == "failed"
    assert unit.error == (f"BudgetExceeded: {first['code']} has reached its $5.00 spend limit. "
                          "Raise `limits.task_usd` to continue.")
    assert not launches


async def test_persistent_claude_reader_uses_the_dispatched_turn_scope(app, tmp_path, monkeypatch):
    session = app.store.create(model="claude.fast")
    sid = session["id"]
    board = TaskBoard(app)
    first = board.create(title="First task")
    second = board.create(title="Second task")
    board.link(first["id"], sid)
    cc = claude_code.ClaudeCode(app)
    sent = asyncio.Queue()

    @app.tools.add("report_cost", "Record tool usage", {"type": "object", "properties": {}}, read_only=True)
    async def report_cost(ctx, _args):
        _record(app, ctx.session_id, 0.5, billing="subscription", role="tool")
        return ToolOutput("done")

    class FakeProcess:
        pid = 0
        returncode = None
        stdout = asyncio.StreamReader()
        stderr = asyncio.StreamReader()

        async def wait(self):
            self.returncode = 0
            return 0

    raw = FakeProcess()

    async def status():
        return {"installed": True, "logged_in": True, "bills_api": False}

    async def ensure(_session, _model, _effort, _resume):
        if sid not in cc.procs:
            cc.procs[sid] = claude_code.Proc(cc, sid, raw, (), "fake", tmp_path / "mcp.json", False)
        return cc.procs[sid]

    async def send(proc, _obj):
        sent.put_nowait(proc)

    def result(cost, **fields):
        event = {"type": "result", "subtype": "success", "total_cost_usd": cost, **fields}
        raw.stdout.feed_data((json.dumps(event) + "\n").encode("utf-8"))

    monkeypatch.setattr(cc.probe, "status", status)
    monkeypatch.setattr(cc, "_ensure", ensure)
    monkeypatch.setattr(claude_code.Proc, "send", send)
    monkeypatch.setattr(claude_code, "kill_group", lambda *_args: None)
    turns = []
    try:
        app.store.add_message(sid, Message.user("First turn"))
        turns.append(asyncio.create_task(cc.run_turn(session)))
        proc = await asyncio.wait_for(sent.get(), 2)
        board.unlink(first["id"], sid)
        board.link(second["id"], sid)
        assert not (await cc.mcp.call(sid, "report_cost", {}))["isError"]
        result(1)
        await asyncio.wait_for(turns[-1], 2)

        app.store.add_message(sid, Message.user("Second turn"))
        turns.append(asyncio.create_task(cc.run_turn(session)))
        same_proc = await asyncio.wait_for(sent.get(), 2)
        assert same_proc is proc
        result(2, origin={"kind": "background"})
        result(3)
        await asyncio.wait_for(turns[-1], 2)
    finally:
        raw.stdout.feed_eof()
        raw.stderr.feed_eof()
        if proc := cc.procs.get(sid):
            await asyncio.wait_for(proc.reader, 2)
        await asyncio.wait_for(asyncio.gather(*turns, return_exceptions=True), 2)

    rows = app.db.all("SELECT task_id, task_attribution, billing FROM usage_records WHERE session_id=? ORDER BY id", [sid])
    assert [(row["task_id"], row["task_attribution"], row["billing"]) for row in rows] == [
        (first["id"], "sole_link", "subscription"),
        (first["id"], "sole_link", "subscription"),
        (None, "unlinked", "subscription"),
        (second["id"], "sole_link", "subscription"),
    ]


def test_ambiguous_task_blocks_only_when_task_cap_is_enabled(app):
    sid = app.store.create()["id"]
    board = TaskBoard(app)
    first = board.create(title="First task")["id"]
    second = board.create(title="Second task")["id"]
    board.link(first, sid)
    board.link(second, sid)
    app.usage.check(sid)
    assert app.usage.headroom(sid) is None
    row = _record(app, sid, 0.25)
    assert (row["task_id"], row["task_attribution"]) == (None, "ambiguous")

    app.config.limits["task_usd"] = 5
    with pytest.raises(BudgetExceeded, match="Attach the intended task through /task"):
        app.usage.check(sid)
    with pytest.raises(BudgetExceeded, match="/task"):
        app.usage.headroom(sid)
    board.attach(first, sid)
    app.usage.check(sid)
    assert app.usage.headroom(sid) == 5
    assert _record(app, sid, 1)["task_id"] == first

    latest = board.create(title="Latest task")["id"]
    board.attach(latest, sid)
    assert _record(app, sid, 1)["task_id"] == latest
    board.unlink(latest, sid)
    with pytest.raises(BudgetExceeded, match="/task"):
        app.usage.check(sid)


def test_task_cap_and_headroom_exclude_subscription(app):
    sid = app.store.create()["id"]
    other_sid = app.store.create()["id"]
    board = TaskBoard(app)
    task = board.create(title="A shared task")
    board.link(task["id"], sid)
    board.link(task["id"], other_sid)
    app.config.limits["task_usd"] = 5

    _record(app, sid, 50, billing="subscription")
    first = _record(app, sid, 3)
    app.db.update("usage_records", "id", first["id"], {"ts": 1})
    app.usage.check(other_sid)
    assert app.usage.headroom(other_sid) == 2
    _record(app, other_sid, 2)
    assert app.usage.spent_task(task["id"]) == 5
    assert app.usage.headroom(other_sid) == 0
    with pytest.raises(BudgetExceeded) as error:
        app.usage.check(other_sid)
    assert str(error.value) == f"{task['code']} has reached its $5.00 spend limit. Raise `limits.task_usd` to continue."
    app.config.limits.update(global_daily_usd=1, session_usd=1)
    app.usage.resume_all()
    app.usage.resume_session(other_sid)
    assert app.usage.headroom(other_sid) == 0
    with pytest.raises(BudgetExceeded, match="limits.task_usd"):
        app.usage.check(other_sid)


def test_usage_attribution_totals_match_ledger(app):
    sid = app.store.create(title="First session")["id"]
    other_sid = app.store.create(title="Second session")["id"]
    board = TaskBoard(app)
    task = board.create(title="Attributed task")
    other_task = board.create(title="Other task")
    board.attach(task["id"], sid)
    board.link(other_task["id"], sid)
    board.link(task["id"], other_sid)
    usage = Usage(cost_usd=1.75, input_tokens=4, output_tokens=8, cache_read_tokens=6,
                  cache_write_tokens=2, reasoning_tokens=3, credits=2)
    recorded = [
        app.usage.record(provider="anthropic", model="model", session_id=sid, role="tool", run_id="sub-1", usage=usage),
        _record(app, sid, 3, role="tool", run_id="sub-1", billing="subscription"),
        _record(app, sid, 0.25, role="tool", run_id="sub-1", provider="openai", ok=False),
        _record(app, other_sid, 0.5, role="subagent", run_id="sub-1"),
    ]
    for i, row in enumerate(recorded, start=10):
        app.db.update("usage_records", "id", row["id"], {"ts": i})
    app.db.insert("usage_records", {"ts": 9, "provider": "anthropic", "model": "model", "cost_usd": 7})
    board.link(other_task["id"], other_sid)
    _record(app, other_sid, 1)
    _record(app, None, 0)

    # No startup services are needed for an authenticated ledger read.
    with closing(TestClient(create_app("t", app))) as client:
        def query(**params):
            response = client.get(URL, headers=H, params=params)
            assert response.status_code == 200, response.text
            return response.json()

        assert client.get(URL).status_code == 401
        assert client.get(URL, headers=H, params={"group_by": "ts DESC"}).status_code == 422
        first = query(group_by="model", since=10, until=13, limit=1)
        second = query(group_by="model", since=10, until=13, limit=1, offset=first["next_offset"])
        assert first["rows"][0]["key"] == ["anthropic", "model"]
        assert second["rows"][0]["key"] == ["openai", "model"]
        assert second["next_offset"] is None
        assert first["totals"] == second["totals"] == {
            "ledger_usd": 2.5, "subscription_estimated_usd": 3, "tokens": 20,
            "credits": 2, "attempts": 4, "failures": 1,
        }
        assert query(since=10, until=13, offset=10)["totals"] == first["totals"]
        filtered = query(group_by="run", since=10, until=13, task_id=task["id"], session_id=sid,
                         role="tool", run_id="sub-1", provider="anthropic", model="model")
        assert filtered["totals"]["attempts"] == 2
        assert filtered["rows"][0]["run_id"] == "sub-1"
        assert query(group_by="run", since=10, until=13)["rows"][0]["attempts"] == 4
        assert query(group_by="role", since=10, until=13)["rows"][0]["role"] == "tool"
        assert query(group_by="session", since=10, until=13)["rows"][0]["session_title"] == "First session"
        assert query(task_id="' OR 1=1 --")["totals"]["attempts"] == 0
        task_rows = query()["rows"]
        by_state = {(row["task_id"], row["task_attribution"]): row for row in task_rows}
        assert by_state[(task["id"], None)]["task_code"] == task["code"]
        assert by_state[(task["id"], None)]["ledger_usd"] == 2.5
        assert by_state[(None, None)]["ledger_usd"] == 7
        assert by_state[(None, "ambiguous")]["ledger_usd"] == 1
        assert by_state[(None, "unlinked")]["attempts"] == 1
        board.archive(task["id"])
        board.delete(task["id"])
        (deleted_task,) = query(task_id=task["id"])["rows"]
        assert deleted_task["task_id"] == task["id"]
        assert deleted_task["task_title"] is None
        assert deleted_task["ledger_usd"] == 2.5


def test_record_fails_open_when_the_scope_read_raises(app, monkeypatch):
    sid = app.store.create()["id"]

    def boom(*_a, **_k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(app.usage, "capture_scope", boom)
    row = _record(app, sid, 0.25, run_id="r1")
    rows = app.db.all("SELECT id, session_id, run_id, task_id, task_attribution FROM usage_records")
    assert len(rows) == 1 and rows[0]["id"] == row["id"]
    assert (rows[0]["task_id"], rows[0]["task_attribution"]) == (None, "unlinked")


def test_record_without_a_session_does_not_inherit_the_bound_tasks_attribution(app):
    sid = app.store.create()["id"]
    board = TaskBoard(app)
    task = board.create(title="T")
    board.attach(task["id"], sid)
    with app.usage.scope(sid):
        assert _record(app, sid, 1)["task_id"] == task["id"]
        orphan = app.usage.record(provider="anthropic", model="m", usage=Usage(cost_usd=0.5), session_id=None)
    assert (orphan["task_id"], orphan["task_attribution"]) == (None, "unlinked")


async def test_injected_result_flushes_results_and_uses_live_turn_model_without_ending_it(app, tmp_path, monkeypatch):
    session = app.store.create(model="claude.fast")
    sid = session["id"]
    cc = claude_code.ClaudeCode(app)
    sent = asyncio.Queue()

    class FakeProcess:
        pid = 0
        returncode = None
        stdout = asyncio.StreamReader()
        stderr = asyncio.StreamReader()

        async def wait(self):
            self.returncode = 0
            return 0

    raw = FakeProcess()

    async def status():
        return {"installed": True, "logged_in": True, "bills_api": False}

    async def ensure(_session, _model, _effort, _resume):
        if sid not in cc.procs:
            cc.procs[sid] = claude_code.Proc(cc, sid, raw, (), "fake", tmp_path / "mcp.json", False)
        return cc.procs[sid]

    async def send(proc, _obj):
        sent.put_nowait(proc)

    def feed(event):
        raw.stdout.feed_data((json.dumps(event) + "\n").encode("utf-8"))

    monkeypatch.setattr(cc.probe, "status", status)
    monkeypatch.setattr(cc, "_ensure", ensure)
    monkeypatch.setattr(claude_code.Proc, "send", send)
    monkeypatch.setattr(claude_code, "kill_group", lambda *_args: None)
    app.store.add_message(sid, Message.user("go"))
    task = asyncio.create_task(cc.run_turn(session))
    try:
        proc = await asyncio.wait_for(sent.get(), 2)
        turn = proc.turn
        feed({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "out"}]}})
        feed({"type": "result", "subtype": "success", "total_cost_usd": 1, "origin": {"kind": "background"}})
        for _ in range(100):
            if app.db.all("SELECT 1 FROM usage_records WHERE session_id=?", [sid]):
                break
            await asyncio.sleep(0.01)
        row, = app.db.all("SELECT model, effort, task_attribution FROM usage_records WHERE session_id=?", [sid])
        assert (row["model"], row["effort"]) == (turn.model, turn.effort) and row["task_attribution"] == "unlinked"
        flushed = [m for m in app.store.messages(sid) if m.meta.get("tool_results")]
        assert len(flushed) == 1 and not turn.pending_results  # results were flushed
        assert proc.turn is turn and not turn.done.done()
        feed({"type": "result", "subtype": "success", "total_cost_usd": 2})
        await asyncio.wait_for(task, 2)
        assert proc.turn is None
    finally:
        raw.stdout.feed_eof()
        raw.stderr.feed_eof()
        if proc := cc.procs.get(sid):
            await asyncio.wait_for(proc.reader, 2)
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
