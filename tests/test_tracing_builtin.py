import asyncio
import json
import shutil
import sqlite3
from contextlib import asynccontextmanager, closing
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI

from gamedevworkstation.agent.context import compact_messages
from gamedevworkstation.agent.tools import ToolContext, ToolOutput
from gamedevworkstation.app import AppState
from gamedevworkstation.config import data_dir
from gamedevworkstation.core.effort import check_effort
from gamedevworkstation.core.types import ChatRequest, Message, ToolUseBlock, Usage
from gamedevworkstation.features import eval_cli, mcp_feature, review_desk, web_tools
from gamedevworkstation.features.claude_code import ClaudeCode
from gamedevworkstation.features.harnesses import Harnesses
from gamedevworkstation.features.hookbus import HookResult
from gamedevworkstation.features.task_board import TaskBoard
from gamedevworkstation.providers.base import ProviderError
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response


@pytest.fixture
async def app(cfg, tmp_path):
    cfg.tracing.update(enabled=True, sample_rate=1.0, otlp_endpoint="")
    cfg.limits.update(global_daily_usd=0, session_usd=0, task_usd=0)
    state = AppState(cfg, tmp_path / "ledger.db")
    try:
        yield state
    finally:
        if state.mcp:
            await state.mcp.aclose()
        await state.tracing.aclose()
        state.db.close()


async def _spans(app):
    await app.tracing.aclose()
    with closing(sqlite3.connect(data_dir() / "traces.sqlite3")) as conn:
        conn.row_factory = sqlite3.Row
        return [{**row, "attrs": json.loads(row["attrs_json"])}
                for row in conn.execute("SELECT * FROM trace_spans ORDER BY start_ns")]


def _session(app, **kwargs):
    return app.store.create(harness="builtin", model="claude-haiku-5-5", **kwargs)


def _ctx(app, session):
    return ToolContext(app=app, session=session, run_id=f"main:{session['id']}")


def _anthropic_streams(app, fake):
    """Drive the production adapter with FakeProvider's script and a fake SDK stream."""
    class Stream:
        def __init__(self, response):
            self.response = response

        async def __aiter__(self):
            for block in self.response.content:
                if block.type == "text":
                    yield SimpleNamespace(type="content_block_delta", index=0,
                                          delta=SimpleNamespace(type="text_delta", text=block.text))

        async def get_final_message(self):
            r = self.response
            return SimpleNamespace(
                id=r.id, model=r.model, stop_reason=r.stop_reason,
                content=[SimpleNamespace(**block.model_dump()) for block in r.content],
                usage=SimpleNamespace(input_tokens=r.usage.input_tokens, output_tokens=r.usage.output_tokens,
                                      cache_read_input_tokens=r.usage.cache_read_tokens,
                                      cache_creation_input_tokens=r.usage.cache_write_tokens))

    @asynccontextmanager
    async def stream(**params):
        response = await fake.complete(ChatRequest(model=params["model"], messages=[]))
        yield Stream(response)

    app.providers.chat("anthropic")._client = SimpleNamespace(messages=SimpleNamespace(stream=stream))


async def test_builtin_turn_traces_stream_attempts_and_tool_children(app):
    @app.tools.add("trace_echo", "Echo.", {})
    async def echo(ctx, args):
        return ToolOutput(args["secret"])

    def limit(req):
        raise ProviderError("private provider message", rate_limited=True, retry_after=0)

    tools = tool_response("trace_echo", {"secret": "private tool input"})
    tools.content.append(ToolUseBlock(id="toolu_refused", name="private unregistered tool", input={}))
    final = text_response("private response", usage=Usage(input_tokens=10, cache_read_tokens=100, output_tokens=7))
    fake = FakeProvider(script=[limit, tools, final])
    _anthropic_streams(app, fake)
    sid = _session(app)["id"]
    app.store.add_message(sid, Message.user("private prompt"))
    await app.tracing.astart()
    await app.runner._run(sid)

    root, retry, first, *rest = await _spans(app)
    assert len(fake.calls) == 3
    assert root["name"] == "session_turn" and root["parent_span_id"] is None
    assert root["attrs"]["gdw.harness"] == "builtin" and root["attrs"]["gdw.outcome"] == "ok"
    assert retry["attrs"]["gdw.outcome"] == "error" and retry["attrs"]["error.type"] == "rate_limit"
    assert "gen_ai.usage.input_tokens" not in retry["attrs"]
    assert first["attrs"]["gen_ai.response.finish_reasons"] == ["tool_use"]
    children = [retry, first, *rest]
    assert all(r["parent_span_id"] == root["span_id"] and r["session_id"] == sid for r in children)
    tool_spans = [r["attrs"] for r in rest if r["name"] == "execute_tool"]
    assert {(r["gen_ai.tool.name"], r["gdw.outcome"]) for r in tool_spans} == {
        ("trace_echo", "ok"), ("external", "denied")}
    assert len(tool_spans) == 2
    last, = [r["attrs"] for r in rest if r["name"] == "chat"]
    assert last["gen_ai.usage.input_tokens"] == 110
    assert last["gen_ai.usage.cache_read.input_tokens"] == 100
    assert last["gen_ai.usage.output_tokens"] == 7
    assert all("private" not in r["attrs_json"] for r in [root, *children])
    assert app.db.all("SELECT ok FROM usage_records ORDER BY id") == [{"ok": 0}, {"ok": 1}, {"ok": 1}]


async def test_mcp_refusal_has_no_rpc_span(app, monkeypatch):
    mgr = app.mcp = mcp_feature.MCPManager(app)
    cfg = {"name": "private_server", "transport": "http"}
    name = "mcp__private_server__private_tool"
    mgr._names[name] = ("private_server", "private_tool")
    monkeypatch.setattr(mgr, "server", lambda server: cfg)
    monkeypatch.setattr(mgr, "enabled_for", lambda session: [cfg])

    async def decline(*args):
        return {"status": "declined"}

    async def connect(*args):
        pytest.fail("Refusal must happen before connecting")

    monkeypatch.setattr(app.approvals, "ask", decline)
    monkeypatch.setattr(mgr, "connect", connect)
    await app.tracing.astart()
    out = await app.runner._run_tool(_ctx(app, _session(app, mode="ask")), ToolUseBlock(id="toolu_1", name=name),
                                     {name})
    assert out.is_error
    span, = await _spans(app)
    assert span["name"] == "execute_tool" and span["attrs"]["gdw.outcome"] == "denied"
    assert span["attrs"]["gen_ai.tool.name"] == "external"
    assert "private" not in span["attrs_json"]


async def test_direct_registry_call_emits_tool_span(app):
    @app.tools.add("trace_direct", "Result.", {})
    async def direct(ctx, args):
        return ToolOutput("private tool result", is_error=args["fail"])

    ctx = _ctx(app, _session(app))
    await app.tracing.astart()
    assert not (await app.tools.run(ctx, "trace_direct", {"fail": False})).is_error
    assert (await app.tools.run(ctx, "trace_direct", {"fail": True})).is_error
    rows = await _spans(app)
    assert [(r["name"], r["attrs"]["gdw.outcome"]) for r in rows] == [
        ("execute_tool", "ok"), ("execute_tool", "error")]
    for r in rows:
        assert r["parent_span_id"] is None and r["session_id"] == ctx.session_id
        assert r["attrs"]["gen_ai.tool.name"] == "trace_direct"
        assert "private" not in r["attrs_json"]


async def test_web_search_gates_effort_and_records_failed_attempt(app, monkeypatch):
    web_tools.register(FastAPI(), APIRouter(), app)
    ctx = _ctx(app, _session(app))
    order = []

    def gate(effort, token, run_id):
        order.append("gate")
        assert (effort, token, run_id) == ("low", None, ctx.run_id)
        check_effort(effort, token, run_id)
        if len(order) == 1:
            raise PermissionError("refused by test gate")

    async def create(**params):
        order.append("dispatch")
        assert "private query" in params["messages"][0]["content"]
        raise ProviderError("private SDK failure")

    monkeypatch.setattr(web_tools, "check_effort", gate)
    fake = FakeProvider()
    fake.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    app.providers.override("anthropic", "default", fake)
    await app.tracing.astart()
    assert (await app.tools.run(ctx, "web_search", {"query": "private query"})).is_error
    assert app.db.one("SELECT count(*) AS n FROM usage_records")["n"] == 0
    assert (await app.tools.run(ctx, "web_search", {"query": "private query"})).is_error
    assert order == ["gate", "gate", "dispatch"]
    spans = await _spans(app)
    chat, = [r for r in spans if r["name"] == "chat"]
    tool = next(r for r in spans if r["span_id"] == chat["parent_span_id"])
    assert tool["name"] == "execute_tool" and chat["attrs"]["gdw.outcome"] == "error"
    assert "private" not in chat["attrs_json"]
    assert app.db.all("SELECT feature, role, ok, cost_usd FROM usage_records") == [
        {"feature": "web_search", "role": "tool", "ok": 0, "cost_usd": 0}]


async def test_turn_usage_keeps_its_task_after_relink(app):
    sid = _session(app)["id"]
    second_sid = _session(app)["id"]
    board = TaskBoard(app)
    first = board.create(title="First task")["id"]
    second = board.create(title="Second task")["id"]
    board.link(first, sid)
    board.link(second, second_sid)
    app.usage.record(provider="anthropic", model="claude-haiku-5-5", session_id=second_sid, usage=Usage(cost_usd=1))
    app.config.limits["task_usd"] = 1

    @app.tools.add("trace_bill", "Report usage.", {})
    async def bill(ctx, args):
        app.usage.check(sid)
        app.usage.record(provider="anthropic", model="claude-haiku-5-5", session_id=sid, role="tool", usage=Usage())
        return ToolOutput("ok")

    def relink(req):
        board.unlink(first, sid)
        board.link(second, sid)
        return tool_response("trace_bill", {})

    fake = FakeProvider(script=[relink, text_response("done")])
    app.providers.override("anthropic", "default", fake)
    app.store.add_message(sid, Message.user("do the work"))
    await app.runner._run(sid)
    assert len(fake.calls) == 2
    assert app.db.all("SELECT role, task_id FROM usage_records WHERE session_id=? ORDER BY id", [sid]) == [
        {"role": "main", "task_id": first}, {"role": "tool", "task_id": first}, {"role": "main", "task_id": first}]
    app.store.add_message(sid, Message.user("next request"))
    await app.runner._run(sid)
    assert len(fake.calls) == 2
    assert any(m.meta.get("error_kind") == "budget" for m in app.store.messages(sid))


async def test_mcp_discovery_and_tool_rpc_spans(app, monkeypatch):
    import mcp
    from mcp.client import streamable_http

    mgr = app.mcp = mcp_feature.MCPManager(app)
    server = "privateServer"
    tool = "privateTool"
    name = mcp_feature.tool_name(server, tool)
    await mgr.add({"name": server, "transport": "http", "url": "https://private.example",
                   "enabled_default": True})
    mgr._names[name] = (server, tool)
    monkeypatch.setattr(mgr, "hints", lambda *args: {"readOnlyHint": True})
    observed = []

    class Session:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def initialize(self):
            observed.append(app.tracing.capture().span_id)

        async def list_tools(self):
            observed.append(app.tracing.capture().span_id)
            return SimpleNamespace(tools=[SimpleNamespace(name=tool)])

        async def call_tool(self, called, args):
            observed.append(app.tracing.capture().span_id)
            assert called == tool
            return SimpleNamespace(isError=True, content=[SimpleNamespace(type="text", text="private failure")])

    @asynccontextmanager
    async def transport(*args, **kwargs):
        yield None, None

    monkeypatch.setattr(mcp, "ClientSession", Session)
    monkeypatch.setattr(streamable_http, "create_mcp_http_client", lambda **kwargs: None)
    monkeypatch.setattr(streamable_http, "streamable_http_client", transport)
    await app.tracing.astart()
    out = await mgr.call(_ctx(app, _session(app)), name, {})
    assert out.is_error
    root, *rpcs = await _spans(app)
    assert root["name"] == "execute_tool" and root["attrs"]["gdw.outcome"] == "error"
    assert [r["name"] for r in rpcs] == ["initialize", "tools/list", "tools/call"]
    assert [r["span_id"] for r in rpcs] == observed
    assert all(r["kind"] == 3 for r in rpcs)
    # The shared connection's handshake belongs to no caller: no parent and no session. The call nests under its tool.
    assert all(r["parent_span_id"] is None and r["session_id"] is None for r in rpcs[:2])
    assert rpcs[2]["parent_span_id"] == root["span_id"] and rpcs[2]["session_id"] == root["session_id"]
    assert all(r["attrs"]["gdw.mcp.transport"] == "http" for r in rpcs)
    assert all("gen_ai.tool.name" not in r["attrs"] for r in rpcs[:2])
    assert rpcs[-1]["attrs"]["gen_ai.tool.name"] == "external"
    assert rpcs[-1]["attrs"]["gdw.outcome"] == "error"
    assert all("private" not in r["attrs_json"] for r in [root, *rpcs])


async def test_cancelled_stream_keeps_reported_usage(app):
    started = asyncio.Event()

    class Stream:
        async def __aiter__(self):
            yield SimpleNamespace(type="message_start", message=SimpleNamespace(
                usage=SimpleNamespace(input_tokens=9, output_tokens=0)))
            started.set()
            await asyncio.Future()

    @asynccontextmanager
    async def stream(**params):
        yield Stream()

    app.providers.chat("anthropic")._client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
    sid = _session(app)["id"]
    app.store.add_message(sid, Message.user("wait"))
    await app.tracing.astart()
    turn = app.runner.start(sid)
    await asyncio.wait_for(started.wait(), 3)
    turn.cancel()
    await turn
    root, chat = await _spans(app)
    assert root["attrs"]["gdw.outcome"] == chat["attrs"]["gdw.outcome"] == "cancelled"
    assert chat["attrs"]["gen_ai.usage.input_tokens"] == 9
    assert app.db.all("SELECT error_kind, input_tokens, ok FROM usage_records") == [
        {"error_kind": "cancelled", "input_tokens": 9, "ok": 0}]


@pytest.mark.parametrize(("status", "cancel"), [("completed", True), ("incomplete", False)])
async def test_openai_stream_keeps_terminal_usage_when_final_read_fails(app, status, cancel):
    reading_tail = asyncio.Event()
    finish_tail = asyncio.Event()
    model = "gpt-6.1-terra"

    async def events():
        yield SimpleNamespace(type=f"response.{status}", response={
            "status": status, "model": model, "usage": {
                "input_tokens": 19, "input_tokens_details": {"cached_tokens": 4}, "output_tokens": 11,
                "output_tokens_details": {"reasoning_tokens": 8},
            },
        })
        reading_tail.set()
        await finish_tail.wait()
        raise OSError("private stream cleanup error")

    async def create(**params):
        assert params["stream"] is True
        return events()

    app.providers.chat("openai")._client = SimpleNamespace(responses=SimpleNamespace(create=create))
    sid = app.store.create(harness="builtin", model=model)["id"]
    app.store.add_message(sid, Message.user("wait"))
    await app.tracing.astart()
    turn = app.runner.start(sid)
    await asyncio.wait_for(reading_tail.wait(), 3)
    if cancel:
        turn.cancel()
    else:
        finish_tail.set()
    await turn

    root, chat = await _spans(app)
    outcome = "cancelled" if cancel else "error"
    assert root["attrs"]["gdw.outcome"] == chat["attrs"]["gdw.outcome"] == outcome
    assert chat["attrs"]["gen_ai.response.model"] == model
    assert chat["attrs"]["gen_ai.usage.input_tokens"] == 19
    assert chat["attrs"]["gen_ai.usage.cache_read.input_tokens"] == 4
    assert chat["attrs"]["gen_ai.usage.output_tokens"] == 11
    assert chat["attrs"]["gen_ai.usage.reasoning.output_tokens"] == 8
    assert "private" not in chat["attrs_json"]
    row, = app.db.all("SELECT ok, error_kind, input_tokens, cache_read_tokens, output_tokens, cost_usd FROM usage_records")
    assert row["ok"] == 0 and row["error_kind"] == ("cancelled" if cancel else "other")
    assert (row["input_tokens"], row["cache_read_tokens"], row["output_tokens"]) == (15, 4, 11)
    assert row["cost_usd"] > 0


async def test_compaction_failure_records_one_attempt(app):
    def fail(req):
        error = ProviderError("private compaction error", rate_limited=True)
        error.usage = Usage(input_tokens=8, cost_usd=0.01)
        raise error

    app.providers.override("anthropic", "default", FakeProvider(script=[fail]))
    sid = _session(app)["id"]
    task = TaskBoard(app).create(title="Summarize", session_id=sid, link_session=True)["id"]
    with pytest.raises(ProviderError, match="private compaction error"):
        await compact_messages(app, sid, [Message.user("old text")], 1)
    assert app.db.all("SELECT role, ok, input_tokens, cost_usd, task_id FROM usage_records") == [
        {"role": "compact", "ok": 0, "input_tokens": 8, "cost_usd": 0.01, "task_id": task}]


async def test_openai_rubric_traces_and_records_each_attempt(app):
    model = "gpt-6.1-terra"
    wire = {"model": model, "usage": {"input_tokens": 19, "output_tokens": 11,
                                     "output_tokens_details": {"reasoning_tokens": 8}}}
    replies = iter([
        {**wire, "status": "failed", "error": {"message": "private rubric failure"}},
        {**wire, "status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": '{"pass": true}'}]}]},
    ])

    async def create(**params):
        return SimpleNamespace(parse=lambda: next(replies), headers={})

    app.providers.chat("openai")._client = SimpleNamespace(
        responses=SimpleNamespace(with_raw_response=SimpleNamespace(create=create)))
    await app.tracing.astart()
    judge = eval_cli.make_rubric(app, model=model)
    assert not (await judge("rubric", "diff"))["pass"]
    assert (await judge("rubric", "diff"))["pass"]
    spans = await _spans(app)
    assert [r["attrs"]["gdw.outcome"] for r in spans] == ["error", "ok"]
    for r in spans:
        attrs = r["attrs"]
        assert r["name"] == "chat" and attrs["gen_ai.response.model"] == model
        assert attrs["gen_ai.usage.output_tokens"] == 11
        assert attrs["gen_ai.usage.reasoning.output_tokens"] == 8
        assert "private" not in r["attrs_json"]
    assert app.db.all("SELECT feature, ok, input_tokens FROM usage_records ORDER BY id") == [
        {"feature": "eval_rubric", "ok": 0, "input_tokens": 19},
        {"feature": "eval_rubric", "ok": 1, "input_tokens": 19}]


async def test_openai_failed_completion_preserves_usage_for_review_desk(app):
    model = "gpt-6.1-terra"
    wire = {"model": model, "status": "failed", "usage": {"input_tokens": 19, "output_tokens": 11}}

    async def create(**params):
        return SimpleNamespace(parse=lambda: wire, headers={})

    app.providers.chat("openai")._client = SimpleNamespace(
        responses=SimpleNamespace(with_raw_response=SimpleNamespace(create=create)))
    await app.tracing.astart()
    review, _ = review_desk.make_prereview(app, model=model)
    result = await review({"steps": [], "grade": {"steps": [], "passed": False}, "prompt": "review", "diff": ""})
    assert result["verdict"] == "reject"
    chat, = await _spans(app)
    assert chat["attrs"]["gdw.outcome"] == "error"
    assert chat["attrs"]["gen_ai.response.finish_reasons"] == ["error"]
    row, = app.db.all("SELECT feature, input_tokens, output_tokens, cost_usd FROM usage_records")
    assert row["feature"] == "review_desk"
    assert (row["input_tokens"], row["output_tokens"]) == (19, 11)
    assert row["cost_usd"] > 0


@pytest.mark.parametrize("harness", ["agent_sdk", "claude_code", "codex_cli"])
async def test_external_harness_effort_decline_ends_turn_span(app, monkeypatch, harness):
    import claude_agent_sdk as sdk

    async def decline(sid, kind, payload):
        assert kind == "effort" and payload["effort"] == "xhigh"
        return {"status": "declined"}

    def query(**kwargs):
        pytest.fail("An effort decline must stop dispatch")

    async def status():
        return {"installed": True, "logged_in": True}

    async def dispatch(*args, **kwargs):
        pytest.fail("An effort decline must stop dispatch")

    if harness == "claude_code":
        cc = app.extensions["claude_code"] = ClaudeCode(app)
        monkeypatch.setattr(cc.probe, "status", status)
        monkeypatch.setattr(cc, "_ensure", dispatch)
    elif harness == "codex_cli":
        monkeypatch.setattr(shutil, "which", lambda name: "/fake/codex")
        monkeypatch.setattr(Harnesses, "_codex_turn", dispatch)
    monkeypatch.setattr(app.approvals, "ask", decline)
    monkeypatch.setattr(sdk, "query", query)
    app.extensions["harnesses"] = Harnesses(app)
    sid = app.store.create(harness=harness, model="claude-sonnet-5-5", effort="xhigh")["id"]
    app.store.add_message(sid, Message.user("private prompt"))
    await app.tracing.astart()
    await app.runner._run(sid)

    root, = await _spans(app)
    assert root["name"] == "session_turn" and root["attrs"]["gdw.outcome"] == "effort_declined"
    reply = app.store.messages(sid)[-1]
    assert "wasn't approved" in reply.text() and not reply.meta.get("error")
    assert not app.db.all("SELECT id FROM usage_records")


async def test_sdk_failure_without_result_text_ends_turn_span(app, monkeypatch):
    import claude_agent_sdk as sdk

    async def query(**kwargs):
        yield sdk.ResultMessage(subtype="error_during_execution", duration_ms=10, duration_api_ms=10,
                                is_error=True, num_turns=1, session_id="sdk_test", total_cost_usd=0.01,
                                usage={"input_tokens": 42}, result=None)

    monkeypatch.setattr(sdk, "query", query)
    app.extensions["harnesses"] = Harnesses(app)
    sid = app.store.create(harness="agent_sdk", model="claude-sonnet-5-5")["id"]
    app.store.add_message(sid, Message.user("private prompt"))
    await app.tracing.astart()
    await app.runner._run(sid)

    root, agent = await _spans(app)  # D5 adds the harness's own invoke_agent span under the turn
    assert root["name"] == "session_turn" and root["attrs"]["gdw.outcome"] == "harness_failure"
    assert agent["name"] == "invoke_agent" and agent["parent_span_id"] == root["span_id"]
    assert agent["attrs"]["gdw.visibility"] == "harness" and agent["attrs"]["gdw.outcome"] == "error"
    assert agent["attrs"]["gen_ai.usage.input_tokens"] == 42
    assert [m.role for m in app.store.messages(sid)] == ["user"]
    assert app.db.all("SELECT ok, input_tokens FROM usage_records") == [{"ok": 0, "input_tokens": 42}]


@pytest.mark.parametrize("outcome", ["effort_declined", "prompt_improver_pause", "gate_exhausted", "harness_failure"])
async def test_session_turn_records_explicit_outcome(app, monkeypatch, outcome):
    if outcome == "harness_failure":
        sid = app.store.create(harness="codex_cli")["id"]

        async def run(session):
            app.store.add_message(sid, Message.assistant("private harness error", meta={"error_kind": "harness"}))

        app.extensions["harnesses"] = SimpleNamespace(run=run)
    else:
        sid = _session(app, mode="ask")["id"]
        app.providers.override("anthropic", "default", FakeProvider())
        if outcome == "effort_declined":
            async def effort(session):
                return "cancel", None

            monkeypatch.setattr(app.runner, "_effective_effort", effort)
        elif outcome == "prompt_improver_pause":
            async def improve(session, message):
                return SimpleNamespace(status="paused", reason="private reason")

            app.extensions["prompt_improver"] = SimpleNamespace(improve=improve)
        else:
            app.hooks.register("pre_complete", "test", lambda ev: HookResult(action="block", max_retries=0))
    app.store.add_message(sid, Message.user("private prompt"))
    await app.tracing.astart()
    await app.runner._run(sid)
    root, = await _spans(app)
    assert root["name"] == "session_turn" and root["attrs"]["gdw.outcome"] == outcome
    assert "private" not in root["attrs_json"]


async def test_trace_enqueue_failure_keeps_provider_and_tool_results(app, monkeypatch):
    @app.tools.add("trace_echo", "Echo.", {})
    async def echo(ctx, args):
        return ToolOutput("tool still ran")

    def broken_sink(row):
        raise RuntimeError("storage failed")

    fake = FakeProvider(script=[tool_response("trace_echo", {}), text_response("model still replied")])
    _anthropic_streams(app, fake)
    sid = _session(app)["id"]
    app.store.add_message(sid, Message.user("test"))
    await app.tracing.astart()
    monkeypatch.setattr(app.tracing._store, "enqueue", broken_sink)
    await app.runner._run(sid)
    assert [m.text() for m in app.store.messages(sid)][-1] == "model still replied"
    assert "tool still ran" in app.store.messages(sid)[-2].content[0].content[0].text
    assert app.tracing.health()["dropped_spans"] == 4


def _openai_replies(app, *replies):
    queue = iter(replies)

    async def create(**params):
        return SimpleNamespace(parse=lambda: next(queue), headers={})

    app.providers.chat("openai")._client = SimpleNamespace(
        responses=SimpleNamespace(with_raw_response=SimpleNamespace(create=create)))


async def test_eval_cli_starts_and_drains_the_trace_recorder(app, monkeypatch):
    model = "gpt-6.1-terra"
    _openai_replies(app, {"model": model, "status": "completed", "usage": {"input_tokens": 5, "output_tokens": 3},
                          "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"pass": true}'}]}]})
    monkeypatch.setattr("gamedevworkstation.app.AppState", lambda: app)
    monkeypatch.setattr(eval_cli.eval_task, "load", lambda path: SimpleNamespace(task=SimpleNamespace(id="t")))

    async def grade_patch(task, patch, *, repo=None, rubric=None):
        assert (await rubric("rubric", "diff"))["pass"]
        return SimpleNamespace(passed=True, steps=[], tampered=[], to_dict=lambda: {})

    monkeypatch.setattr(eval_cli.eval_grade, "grade_patch", grade_patch)
    patch = data_dir() / "candidate.patch"
    patch.write_text("diff", encoding="utf-8")
    code = await asyncio.to_thread(eval_cli.cli, ["grade", "task", "--patch", str(patch), "--rubric-model", model])
    assert code == 0
    # The recorder was started by the CLI and drained at exit: the span is already on disk.
    with closing(sqlite3.connect(data_dir() / "traces.sqlite3")) as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM trace_spans")]
    assert names == ["chat"]
    assert not app.tracing._store.accepting


async def test_empty_provider_reply_still_grades_as_failure(app):
    model = "gpt-6.1-terra"
    failed = {"model": model, "status": "failed", "usage": {"input_tokens": 7, "output_tokens": 0}}
    _openai_replies(app, failed, failed)
    await app.tracing.astart()
    verdict = await eval_cli.make_rubric(app, model=model)("rubric", "diff")
    assert verdict["pass"] is False
    rewrite, _ = eval_cli.make_rewrite(app, model=model)
    assert await rewrite("text") == ""
    assert app.db.all("SELECT feature, ok, input_tokens FROM usage_records ORDER BY id") == [
        {"feature": "eval_rubric", "ok": 0, "input_tokens": 7},
        {"feature": "eval_forge", "ok": 0, "input_tokens": 7}]


@pytest.mark.parametrize("code,kind", [("unavailable", "other"), ("too_many_requests", "rate_limit")])
async def test_web_search_error_blocks_record_a_failed_attempt(app, code, kind):
    web_tools.register(FastAPI(), APIRouter(), app)
    ctx = _ctx(app, _session(app))
    block = SimpleNamespace(type="web_search_tool_result",
                            content=SimpleNamespace(type="web_search_tool_result_error", error_code=code))
    usage = SimpleNamespace(input_tokens=10, output_tokens=4, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                            server_tool_use=SimpleNamespace(web_search_requests=1))

    async def create(**params):
        return SimpleNamespace(content=[block, SimpleNamespace(type="text", text="sorry", citations=None)],
                               usage=usage, model="claude-haiku-5-5", stop_reason="end_turn")

    fake = FakeProvider()
    fake.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    app.providers.override("anthropic", "default", fake)
    await app.tracing.astart()
    out = await app.tools.run(ctx, "web_search", {"query": "q"})
    assert out.is_error and code in out.text
    row, = app.db.all("SELECT feature, ok, error_kind, input_tokens FROM usage_records")
    assert (row["feature"], row["ok"], row["error_kind"], row["input_tokens"]) == ("web_search", 0, kind, 10)
    chat, = [r for r in await _spans(app) if r["name"] == "chat"]
    assert chat["attrs"]["gdw.outcome"] == "error"
