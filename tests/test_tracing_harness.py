"""D5: one harness span per Claude Code / Agent SDK turn, one SERVER span per inbound GDW MCP tools/call.

Claude Code runs against the fake CLI of tests/test_claude_code.py; nothing here uses the real `claude`, the
network, the Keychain or the real data dir (conftest isolates GDW_HOME and the tests set HOME)."""
import asyncio
import json
import sqlite3
import stat
import sys
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from gamedevworkstation.app import AppState
from gamedevworkstation.config import data_dir
from gamedevworkstation.core.types import Message
from gamedevworkstation.features import claude_code as ccm
from gamedevworkstation.features.gdw_mcp import mount
from gamedevworkstation.features.harnesses import Harnesses
from gamedevworkstation.features.task_board import TaskBoard
from tests.test_claude_code import FAKE, STREAM, _project


@pytest.fixture
async def rig(cfg, tmp_path, monkeypatch):
    home = tmp_path / "cli-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "state").mkdir()
    (home / "fake_claude.json").write_text(json.dumps(
        {"log": str(tmp_path / "fake.log"), "state": str(tmp_path / "state"), "fixtures": str(STREAM)}),
        encoding="utf-8")
    exe = tmp_path / "fake-claude"
    exe.write_text(f"#!{sys.executable}\n" + FAKE.read_text(encoding="utf-8"), encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    cfg.tracing.update(enabled=True, sample_rate=1.0, otlp_endpoint="")
    cfg.limits.update(global_daily_usd=0, session_usd=0, task_usd=0)
    cfg.claude_code["cli_path"] = str(exe)
    app = AppState(cfg, tmp_path / "ledger.db")
    app.listen_port = 8765
    cc = ccm.ClaudeCode(app)
    app.extensions["claude_code"] = cc
    await app.tracing.astart()
    sid = app.store.create(folder=str(_project(tmp_path)), model="claude-sonnet-5-5", skills=[], effort="low")["id"]

    async def send(text="hello"):
        app.store.add_message(sid, Message.user(text))
        await asyncio.wait_for(cc.run_turn(app.store.get(sid)), 10)

    yield SimpleNamespace(app=app, cc=cc, sid=sid, send=send)
    await cc.aclose()
    if app.mcp:
        await app.mcp.aclose()
    await app.tracing.aclose()
    app.db.close()


async def _spans(app):
    await app.tracing.aclose()
    with closing(sqlite3.connect(data_dir() / "traces.sqlite3")) as conn:
        conn.row_factory = sqlite3.Row
        return [{**row, "attrs": json.loads(row["attrs_json"])}
                for row in conn.execute("SELECT * FROM trace_spans ORDER BY start_ns")]


async def _until(predicate):
    async def wait():
        while not (value := predicate()):
            await asyncio.sleep(0.01)
        return value

    return await asyncio.wait_for(wait(), 5)


async def test_persistent_claude_reader_attributes_two_turns(rig):
    await rig.send("hello")
    proc = rig.cc.procs[rig.sid]
    await rig.send("hello")
    assert rig.cc.procs[rig.sid] is proc  # the same reader served both turns
    spans = await _spans(rig.app)
    agents = [s for s in spans if s["name"] == "invoke_agent"]
    assert len(agents) == 2 and agents[0]["span_id"] != agents[1]["span_id"]
    for agent in agents:
        a = agent["attrs"]
        assert a["gdw.visibility"] == "harness" and a["gdw.harness"] == "claude_code"
        assert a["gdw.outcome"] == "ok" and a["gen_ai.usage.input_tokens"] == 1000
        assert a["gen_ai.usage.output_tokens"] == 800 and a["gdw.run.id"] == f"main:{rig.sid}"
    rows = rig.app.db.all("SELECT run_id, ok FROM usage_records WHERE session_id=?", [rig.sid])
    assert len(rows) == 2 and all(r["ok"] == 1 for r in rows)  # one row per turn, one span per row


async def test_injected_cli_result_does_not_end_newer_turn(rig):
    await rig.send("hello")
    proc = rig.cc.procs[rig.sid]
    rig.app.store.add_message(rig.sid, Message.user("slow"))
    task = asyncio.create_task(rig.cc.run_turn(rig.app.store.get(rig.sid)))
    turn = await _until(lambda: proc.turn if proc.turn is not None and proc.turn.span is not None else None)
    span = turn.span
    before = len(rig.app.db.all("SELECT id FROM usage_records"))
    proc._on_event({"type": "result", "subtype": "success", "is_error": False, "result": "bg", "uuid": "bg-1",
                    "session_id": proc.cc_session, "num_turns": 9, "total_cost_usd": 0.0,
                    "usage": {"input_tokens": 5, "output_tokens": 1}, "origin": {"kind": "task-notification"}})
    assert proc.turn is turn and turn.span is span and not turn.done.done()  # the newer turn goes on
    assert len(rig.app.db.all("SELECT id FROM usage_records")) == before + 1  # its usage still counts
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await _until(lambda: turn.done.done())
    agents = [s for s in await _spans(rig.app) if s["name"] == "invoke_agent"]
    assert len(agents) == 2 and agents[1]["attrs"]["gdw.outcome"] in ("cancelled", "interrupted")
    assert "gen_ai.usage.input_tokens" not in agents[1]["attrs"] or agents[1]["attrs"]["gen_ai.usage.input_tokens"] == 0


async def test_claude_turn_usage_uses_dispatch_time_task(rig):
    board = TaskBoard(rig.app)
    first, second = board.create(title="First task"), board.create(title="Second task")
    board.link(first["id"], rig.sid)
    await rig.send("hello")  # starts the persistent reader
    rig.app.store.add_message(rig.sid, Message.user("slow"))
    task = asyncio.create_task(rig.cc.run_turn(rig.app.store.get(rig.sid)))
    proc = rig.cc.procs[rig.sid]
    turn = await _until(lambda: proc.turn if proc.turn is not None and proc.turn.usage_scope is not None else None)
    assert turn.usage_scope.task_id == first["id"]
    board.unlink(first["id"], rig.sid)
    board.link(second["id"], rig.sid)  # the task changes while the turn runs
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await _until(lambda: turn.done.done())
    rows = rig.app.db.all("SELECT task_id FROM usage_records WHERE session_id=? ORDER BY id", [rig.sid])
    assert [r["task_id"] for r in rows][-1] == first["id"]


async def test_harness_usage_is_aggregate(rig, monkeypatch):
    import claude_agent_sdk as sdk

    async def query(**kwargs):
        for _ in range(2):  # several model calls inside one turn
            yield sdk.AssistantMessage(content=[sdk.TextBlock(text="step")], model="claude-sonnet-5-5")
        yield sdk.ResultMessage(subtype="success", duration_ms=10, duration_api_ms=10, is_error=False, num_turns=2,
                                session_id="sdk_test", total_cost_usd=0.05, result="done",
                                usage={"input_tokens": 300, "output_tokens": 70})

    monkeypatch.setattr(sdk, "query", query)
    rig.app.extensions["harnesses"] = Harnesses(rig.app)
    sid = rig.app.store.create(harness="agent_sdk", model="claude-sonnet-5-5")["id"]
    rig.app.store.add_message(sid, Message.user("go"))
    await rig.app.runner._run(sid)
    rows = rig.app.db.all("SELECT input_tokens, output_tokens, cost_usd FROM usage_records WHERE session_id=?", [sid])
    assert rows == [{"input_tokens": 300, "output_tokens": 70, "cost_usd": 0.05}]
    agents = [s for s in await _spans(rig.app) if s["name"] == "invoke_agent"]
    assert len(agents) == 1  # one span per turn, not per model call
    a = agents[0]["attrs"]
    assert a["gen_ai.usage.input_tokens"] == 300 and a["gen_ai.usage.output_tokens"] == 70
    assert a["gdw.harness"] == "agent_sdk" and a["gdw.outcome"] == "ok"


async def test_gdw_mcp_bridge_traces_without_auth_metadata(rig):
    mcp = rig.cc.mcp
    token = mcp.issue(rig.sid)
    web = FastAPI()
    mount(web, mcp)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "task_boards", "arguments": {}}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web), base_url="http://127.0.0.1") as client:
        refused = await client.post("/mcp/gdw", json=body, headers={"Authorization": "Bearer wrong"})
        assert refused.status_code == 401
        ok = await client.post("/mcp/gdw", json=body, headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200 and "error" not in ok.json()
    spans = await _spans(rig.app)
    assert [s["name"] for s in spans] == ["tools/call"]  # none for the refused, unauthenticated call
    (span,) = spans
    assert span["kind"] == 2 and span["parent_span_id"] is None  # SERVER, no guessed parent
    assert span["attrs"]["gdw.mcp.direction"] == "inbound" and span["attrs"]["gen_ai.tool.name"] in ("task_boards", "external")  # the recorder maps names it doesn't know
    blob = json.dumps(span, default=str).lower()
    assert token.lower() not in blob and "bearer" not in blob and "authorization" not in blob
