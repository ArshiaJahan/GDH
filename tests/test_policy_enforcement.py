"""The tool policy at the two chokepoints: ToolRegistry._run and MCPManager._call."""
import asyncio
import sys

import pytest
from fastapi import APIRouter, FastAPI

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.config import data_dir
from gamedevworkstation.features import mcp_feature

from .conftest import FIXTURES, untrusted


def write_policy(text: str) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / "tool_policy.toml").write_text(text, encoding="utf-8")


async def _pending(app, sid, n=300):
    for _ in range(n):
        if pend := app.approvals.pending(sid):
            return pend
        await asyncio.sleep(0.01)
    return []


@pytest.fixture
def app(tmp_path):
    return AppState(db_path=tmp_path / "p.db")


@pytest.fixture
async def mcp_app(tmp_path):
    s = AppState(db_path=tmp_path / "m.db")
    mcp_feature.register(FastAPI(), APIRouter(), s)
    s.db.insert("mcp_servers", {"name": "hints", "transport": "stdio", "command": sys.executable,
                                "args": [str(FIXTURES / "mcp" / "hints_server.py")], "env": {}, "headers": {},
                                "enabled_default": 1, "shared": 0})
    yield s
    s.config.modes["allowlist"] = []
    await s.mcp.aclose()


def text(out):
    u = untrusted(out.text)
    return u[1] if u else out.text


async def mcp_call(s, sess, tool, args=None, *, mode="ask", role="main", answer=None):
    se = s.store.update(sess["id"], mode=mode)
    ctx = ToolContext(app=s, session=se, run_id="main:x", role=role)
    task = asyncio.create_task(s.mcp.call(ctx, f"mcp__hints__{tool}", args or {"text": "t"}))
    card = None
    if answer:
        pend = await _pending(s, sess["id"])
        assert pend
        card = pend[0]
        s.approvals.resolve(card["id"], answer)
    out = await asyncio.wait_for(task, 30)
    assert not s.approvals.pending(sess["id"])
    return out, card


async def test_registry_denies_mcp_for_subagent_not_main(app):
    sess = app.store.create()
    app.tools.register(__import__("gamedevworkstation.agent.tools", fromlist=["Tool"]).Tool(
        spec=app.tools.tools["read_file"].spec.__class__(name="mcp__x__y", description="d", input_schema={"type": "object"}),
        handler=_ok))
    sub = ToolContext(app=app, session=sess, run_id="r", role="subagent")
    out = await app.tools.run(sub, "mcp__x__y", {})
    assert out.is_error and out.denied and "tool policy" in out.text
    main = ToolContext(app=app, session=sess, run_id="r")
    assert (await app.tools.run(main, "mcp__x__y", {})).text == "ok"


async def _ok(ctx, args):
    from gamedevworkstation.agent.tools import ToolOutput
    return ToolOutput("ok")


async def test_user_policy_denies_run_command_without_prompt(app):
    write_policy('version = 1\n[agents.main]\ndeny = ["run_command"]\n')
    sess = app.store.create()
    ctx = ToolContext(app=app, session=sess, run_id="r")
    out = await app.tools.run(ctx, "run_command", {"command": "echo hi"})
    assert out.is_error and out.denied and "tool policy" in out.text
    assert not app.approvals.pending(sess["id"])
    specs = app.tools.specs(policy=app.current_tool_policy())
    assert "run_command" not in [s.name for s in specs] and "read_file" in [s.name for s in specs]


async def test_malformed_policy_fails_closed_and_publishes_once(app):
    write_policy("version = [[[")
    sess = app.store.create()
    ctx = ToolContext(app=app, session=sess, run_id="r")
    out = await app.tools.run(ctx, "run_command", {"command": "echo hi"})
    assert out.denied and "malformed" in out.text
    out = await app.tools.run(ctx, "read_file", {"path": "nope.txt"})
    assert "malformed" not in out.text and "not allowed" not in out.text
    errors = [e for e in app.db.all("SELECT type FROM events") if e["type"] == "tool_policy.error"]
    assert len(errors) == 1


async def test_readonly_hint_asks_by_default_then_allowlist_runs(mcp_app):
    s = mcp_app
    sess = s.store.create(mode="ask")
    await s.mcp.warm(sess)
    out, card = await mcp_call(s, sess, "look", answer="deny")
    assert out.is_error and out.denied and card["kind"] == "mcp_tool"
    assert "marked read-only by the server (not trusted)" in card["payload"]["hints"]
    out, _ = await mcp_call(s, sess, "look", answer="approve")
    assert text(out) == "look:t"
    s.config.modes["allowlist"] = ["mcp:hints__look"]
    out, card = await mcp_call(s, sess, "look")
    assert text(out) == "look:t" and card is None


async def test_readonly_hint_trusted_when_policy_opts_in(mcp_app):
    s = mcp_app
    write_policy("version = 1\n[mcp.servers.hints]\ntrust_read_only_hint = true\n")
    sess = s.store.create(mode="ask")
    await s.mcp.warm(sess)
    out, card = await mcp_call(s, sess, "look")
    assert text(out) == "look:t" and card is None


async def test_plan_mode_readonly_asks_and_unannotated_refused(mcp_app):
    s = mcp_app
    sess = s.store.create(mode="plan")
    await s.mcp.warm(sess)
    out, card = await mcp_call(s, sess, "look", mode="plan", answer="deny")
    assert out.denied and card is not None
    out, _ = await mcp_call(s, sess, "plain", mode="plan")
    assert out.is_error and "Plan only mode" in out.text


async def test_mcp_args_with_secret_refused_before_connection(mcp_app):
    s = mcp_app
    sess = s.store.create(mode="ask")
    await s.mcp.warm(sess)
    called = []

    async def boom(name):
        called.append(name)
        raise AssertionError("connected")

    s.mcp.connect = boom
    key = "sk-ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    out, card = await mcp_call(s, sess, "look", {"text": key})
    assert out.is_error and out.denied and "egress" in out.text and card is None and not called


async def test_mcp_ordinary_args_pass(mcp_app):
    s = mcp_app
    s.config.modes["allowlist"] = ["mcp:hints__*"]
    sess = s.store.create(mode="ask")
    await s.mcp.warm(sess)
    out, _ = await mcp_call(s, sess, "plain", {"text": "hello world"})
    assert text(out) == "plain:hello world"


async def test_policy_deny_beats_allowlist_and_subagent_default(mcp_app):
    s = mcp_app
    write_policy('version = 1\n[agents.main]\ndeny = ["mcp__hints__plain"]\n')
    s.config.modes["allowlist"] = ["mcp:hints__plain"]
    sess = s.store.create(mode="ask")
    await s.mcp.warm(sess)
    out, _ = await mcp_call(s, sess, "plain")
    assert out.denied and "tool policy" in out.text
    out, _ = await mcp_call(s, sess, "note", role="subagent")
    assert out.denied and "tool policy" in out.text
    names = [t.name for t in s.mcp.tool_specs(sess, "main")]
    assert "mcp__hints__plain" not in names and "mcp__hints__look" in names
    assert not s.mcp.tool_specs(sess, "subagent")
