import asyncio
import json
import re
import sqlite3
import time
from contextlib import asynccontextmanager, closing
from dataclasses import replace
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.config import ModelConfig, data_dir
from gamedevworkstation.core.types import new_id
from gamedevworkstation.features import trace_store, tracing
from gamedevworkstation.features.claude_cli import redact
from gamedevworkstation.features.mcp_feature import masked
from gamedevworkstation.features.status import StatusChecker
from gamedevworkstation.server import create_app

ENDPOINT = "https://collector.example.test/v1/traces"


async def _until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


@asynccontextmanager
async def _recorder(settings, **kwargs):
    recorder = tracing.TraceRecorder(settings, **kwargs)
    await recorder.astart()
    try:
        await _until(lambda: recorder.available)
        yield recorder
    finally:
        await recorder.aclose()


def _rows():
    with closing(sqlite3.connect(data_dir() / "traces.sqlite3")) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM trace_spans ORDER BY start_ns, span_id")]


def _spans(request):
    return json.loads(request.content)["resourceSpans"][0]["scopeSpans"][0]["spans"]


async def test_trace_context_isolated_across_parallel_tasks(monkeypatch, cfg):
    samples = iter((0.1, 0.1, 0.9))
    monkeypatch.setattr(tracing.random, "random", lambda: next(samples))
    async with _recorder({**cfg.tracing, "sample_rate": 0.5}) as recorder:
        async def turn(session_id):
            async def child():
                with recorder.span("execute_tool", category="tool") as span:
                    await asyncio.sleep(0)
                    assert recorder.capture() == span.ref
                    return span.ref

            with recorder.span("session_turn", category="turn", session_id=session_id) as root:
                parent = recorder.capture()
                children = await asyncio.gather(child(), child())
                opened = asyncio.Event()

                async def cancelled_child():
                    with recorder.span("chat", category="model"):
                        opened.set()
                        await asyncio.Future()

                task = asyncio.create_task(cancelled_child())
                await opened.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert recorder.capture() == parent
            assert recorder.capture() is None
            detached = recorder.start("subagent_run", category="subagent", parent=parent)
            await asyncio.create_task(asyncio.to_thread(detached.end, "success"))
            detached.end("error")
            return root.ref, children, detached.ref

        sessions = [new_id("ses_"), new_id("ses_")]
        turns = await asyncio.gather(*(turn(session_id) for session_id in sessions))
        with recorder.span("session_turn", category="turn") as skipped:
            with recorder.span("chat", category="model") as child:
                assert skipped.ref.trace_id is child.ref.trace_id is None
        assert recorder.health()["sampled_out"] == 1
        await _until(lambda: len(_rows()) == 10)
        rows = {row["span_id"]: row for row in _rows()}

        assert len({root.trace_id for root, _, _ in turns}) == 2
        for session_id, (root, children, detached) in zip(sessions, turns):
            assert root.trace_id != "0" * 32 and re.fullmatch(r"[0-9a-f]{32}", root.trace_id)
            assert rows[root.span_id]["parent_span_id"] is None
            siblings = [row for row in rows.values() if row["parent_span_id"] == root.span_id]
            assert len(siblings) == 4
            assert {row["session_id"] for row in siblings} == {session_id}
            assert {row["trace_id"] for row in siblings} == {root.trace_id}
            assert all(ref.span_id != "0" * 16 and re.fullmatch(r"[0-9a-f]{16}", ref.span_id)
                       for ref in (root, detached, *children))
            assert rows[detached.span_id]["status"] == 1
            assert detached.span_id != children[0].span_id != children[1].span_id
            cancelled = next(row for row in siblings if row["name"] == "chat")
            assert json.loads(cancelled["attrs_json"])["gdw.outcome"] == "cancelled"
            assert all(row["end_ns"] >= row["start_ns"] for row in siblings)


async def test_helper_run_ids_are_preserved_under_a_turn(cfg):
    sid = new_id("ses_")
    main_id = f"main:{sid}"
    title_id = f"title:{sid}"
    improver_id = f"pi:{sid}:{new_id('msg_')}"
    async with _recorder(cfg.tracing) as recorder:
        with recorder.span("session_turn", category="turn", session_id=sid, run_id=main_id) as turn:
            with recorder.span("chat", category="model", attrs={"gdw.run.id": title_id}) as title:
                pass
            with recorder.span("chat", category="model", run_id=improver_id) as improver:
                pass
            with recorder.span("chat", category="model", run_id=f"{improver_id}:extra") as invalid:
                pass
        await _until(lambda: len(_rows()) == 4)
        rows = {row["span_id"]: row for row in _rows()}
        for span, run_id in ((title, title_id), (improver, improver_id), (invalid, main_id)):
            row = rows[span.ref.span_id]
            assert row["parent_span_id"] == turn.ref.span_id
            assert row["trace_id"] == turn.ref.trace_id
            assert row["run_id"] == run_id
            assert json.loads(row["attrs_json"])["gdw.run.id"] == run_id


@pytest.mark.parametrize("custom_model", ["gpt-custom-2026", "task-model", "task_model"])
async def test_trace_allowlist_rejects_secrets_before_storage_and_export(respx_mock, monkeypatch, cfg, custom_model):
    receiver = respx_mock.post(ENDPOINT).respond(200, json={})
    env_name, export_secret = "GDW_TEST_TRACE_AUTH", "Bearer collector-only-secret"
    secret = "sk-sensitive-not-for-telemetry"
    diagnostic = redact(f"error at /secret/path posting Bearer {secret}")
    mcp_display = masked({"TOKEN": {"keychain": "mcp:private:env:TOKEN", "hint": "dont"}})["TOKEN"]
    settings = {**cfg.tracing, "otlp_endpoint": ENDPOINT, "otlp_headers_env": {"Authorization": env_name}}
    models = {**cfg.models, custom_model: ModelConfig(provider="openai"), secret: ModelConfig(provider="openai")}
    async with _recorder(settings, tool_names=("read_file",), model_names=models) as recorder:
        monkeypatch.setenv(env_name, export_secret)
        span = recorder.start("private-project-name", category="tool", kind=tracing.SpanKind.CLIENT,
                              session_id=secret, run_id=diagnostic, attrs={
                                  "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "private-mcp-tool",
                                  "gen_ai.request.model": custom_model, "gen_ai.response.model": secret,
                                  "gen_ai.response.finish_reasons": ["end_turn"], "gen_ai.usage.input_tokens": 42,
                                  "gen_ai.usage.output_tokens": True, "gdw.queue_ms": 1.25, "error.type": diagnostic,
                                  "gdw.run.id": "private-run", "gdw.job.id": secret, "prompt": "x" * 10_000,
                                  "authorization": export_secret, "headers": mcp_display, "tool.args": "/secret/path",
                              })
        span.end(secret)
        await _until(lambda: receiver.called)

        row, = _rows()
        assert (row["name"], row["category"], row["session_id"], row["run_id"]) == ("tool", "tool", None, None)
        assert row["dropped_attributes"] == 8
        attrs = json.loads(row["attrs_json"])
        assert attrs == {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "external",
                         "gen_ai.request.model": custom_model, "gen_ai.response.model": "unknown",
                         "gen_ai.response.finish_reasons": ["end_turn"], "gen_ai.usage.input_tokens": 42,
                         "gdw.queue_ms": 1.25, "gdw.outcome": "unknown"}

        request = receiver.calls.last.request
        assert request.headers["content-type"] == "application/json"
        assert request.headers["authorization"] == export_secret
        assert str(request.url) == ENDPOINT
        resource, = json.loads(request.content)["resourceSpans"]
        assert resource["resource"]["attributes"] == [
            {"key": "service.name", "value": {"stringValue": "gamedevworkstation"}}]
        scope, = resource["scopeSpans"]
        assert scope["scope"]["version"]
        wire, = scope["spans"]
        assert wire["traceId"] == row["trace_id"] and wire["spanId"] == row["span_id"]
        assert wire["startTimeUnixNano"] == str(row["start_ns"]) and wire["endTimeUnixNano"] == str(row["end_ns"])
        assert wire["kind"] == 3 and wire["status"] == {"code": 0} and "parentSpanId" not in wire
        assert wire["droppedAttributesCount"] == row["dropped_attributes"]
        values = {attr["key"]: attr["value"] for attr in wire["attributes"]}
        assert values["gen_ai.request.model"] == {"stringValue": custom_model}
        assert values["gen_ai.response.model"] == {"stringValue": "unknown"}
        assert values["gen_ai.usage.input_tokens"] == {"intValue": "42"}
        assert values["gdw.queue_ms"] == {"doubleValue": 1.25}
        assert values["gen_ai.response.finish_reasons"] == {"arrayValue": {"values": [{"stringValue": "end_turn"}]}}
        for excluded in (secret, diagnostic, export_secret, env_name, "[REDACTED]", mcp_display,
                         "private-", "/secret/path", "bearer", "x" * 100):
            assert excluded not in str(row) and excluded not in request.content.decode("utf-8")

        limits = {key: 1 for key in tracing._COUNTERS}
        limits.update({key: sorted(values)[0] for key, values in tracing._ENUMS.items()})
        limits.update({"gen_ai.conversation.id": new_id("ses_"), "gdw.job.id": new_id("job_"),
                       "gdw.run.id": new_id("run_"), "gdw.routing.policy_revision": "1"})
        capped = recorder.start("read_file", category="tool", attrs=limits)
        capped.set_attribute("gen_ai.tool.name", "read_file")
        capped.end()
        await _until(lambda: len(_rows()) == 2)
        row = _rows()[1]
        assert len(json.loads(row["attrs_json"])) == 24
        assert len(row["attrs_json"].encode("utf-8")) <= 2 * 1024
        assert row["dropped_attributes"] > 0
        await _until(lambda: receiver.call_count == 2)
        wire, = _spans(receiver.calls.last.request)
        values = {attr["key"]: attr["value"] for attr in wire["attributes"]}
        assert values["gen_ai.conversation.id"] == {"stringValue": row["session_id"]}
        assert values["gdw.run.id"] == {"stringValue": row["run_id"]}

        for changes in ({"trace_id": secret}, {"trace_id": "0" * 32}, {"trace_id": None},
                        {"span_id": diagnostic}, {"span_id": "0" * 16}, {"span_id": None}):
            rejected = recorder.start("chat", category="model", parent=replace(capped.ref, **changes))
            assert rejected.ref.span_id is None
            rejected.end()
        parent = replace(capped.ref, session_id=secret, run_id=diagnostic)
        child = recorder.start("chat", category="model", parent=parent, attrs={
            "gen_ai.request.model": "claude-opus-5-5", "gen_ai.response.model": "unregistered-model",
        })
        child.end()
        await _until(lambda: receiver.call_count == 3)
        assert len(_rows()) == 3
        row = next(row for row in _rows() if row["span_id"] == child.ref.span_id)
        assert (row["session_id"], row["run_id"], row["parent_span_id"]) == (None, None, capped.ref.span_id)
        wire, = _spans(receiver.calls.last.request)
        assert wire["traceId"] == capped.ref.trace_id and wire["parentSpanId"] == capped.ref.span_id
        values = {attr["key"]: attr["value"] for attr in wire["attributes"]}
        assert values == {"gen_ai.request.model": {"stringValue": "claude-opus-5-5"},
                          "gen_ai.response.model": {"stringValue": "unknown"}, "gdw.outcome": {"stringValue": "ok"}}


@pytest.mark.parametrize("model_id", [
    "claude-x-sk-ant-FAKE0123456789", "custom-SK_FAKE0123456789", "custom-ghp_FAKE0123456789abcdef",
    "custom-A9b2C8d3E7f4G6h5I0j1K2l3M4n5O6p7", "custom7ghp_FAKEabcdefabcdefabcd", "sk-model", "SK_model",
])
async def test_model_id_with_embedded_credential_is_unknown_in_both_sinks(respx_mock, cfg, model_id):
    receiver = respx_mock.post(ENDPOINT).respond(200, json={})
    model_attrs = {"gen_ai.request.model": model_id, "gen_ai.response.model": model_id}
    async with _recorder({**cfg.tracing, "otlp_endpoint": ENDPOINT}, model_names=(model_id,)) as recorder:
        with recorder.span("chat", category="model", attrs=model_attrs):
            pass
        await _until(lambda: receiver.called)

        row, = _rows()
        request = receiver.calls.last.request
        wire, = _spans(request)
        attrs = json.loads(row["attrs_json"])
        values = {attr["key"]: attr["value"] for attr in wire["attributes"]}
        for key in model_attrs:
            assert attrs[key] == "unknown"
            assert values[key] == {"stringValue": "unknown"}
        assert model_id not in row["attrs_json"]
        assert model_id not in request.content.decode("utf-8")


async def test_otlp_json_rejection_leaves_local_spans(respx_mock, cfg):
    receiver = respx_mock.post(ENDPOINT).mock(side_effect=[
        httpx.Response(415, text="unsupported media type"),
        httpx.Response(503, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"partialSuccess": {"rejectedSpans": "1", "errorMessage": "remote detail"}}),
        httpx.Response(307, headers={"Location": "https://redirect.example.test/v1/traces"}),
    ])
    settings = {**cfg.tracing, "otlp_endpoint": ENDPOINT}
    async with _recorder(settings) as recorder:
        for failures in range(1, 4):
            with recorder.span("chat", category="model"):
                pass
            await _until(lambda: recorder.health()["export_failures"] == failures)
        assert receiver.call_count == 4
        requests = [call.request for call in receiver.calls]
        assert _spans(requests[1]) == _spans(requests[2])
        assert {row["span_id"] for row in _rows()} == {_spans(request)[0]["spanId"] for request in requests}
        assert recorder.health()["export_rejected_spans"] == 3
        assert len(respx_mock.calls) == receiver.call_count

    for endpoint in ("http://example.test/v1/traces", "https://user:secret@localhost/v1/traces",
                     f"{ENDPOINT}?", f"{ENDPOINT}#fragment", "http://127.0.0.1:99999/v1/traces"):
        recorder = tracing.TraceRecorder({**cfg.tracing, "otlp_endpoint": endpoint})
        assert recorder.health()["diagnostic"] == "invalid_export_endpoint"
    assert trace_store._endpoint("http://127.0.0.1:4318/v1/traces")
    assert trace_store._endpoint("http://[::1]:4318/v1/traces")


async def test_stalled_trace_sinks_do_not_block_turn(respx_mock, monkeypatch, cfg):
    writer_stalled, release_writer = Event(), Event()
    export_stalled, release_export = Event(), Event()
    persist = trace_store.TraceStore._persist

    def stalled_writer(store, conn, batch):
        if not release_writer.is_set() and export_stalled.is_set():
            writer_stalled.set()
            release_writer.wait(timeout=5)
        persist(store, conn, batch)

    async def stalled_receiver(request):
        export_stalled.set()
        async with asyncio.timeout(5):
            while not release_export.is_set():
                await asyncio.sleep(0.01)
        return httpx.Response(200, json={})

    monkeypatch.setattr(trace_store.TraceStore, "_persist", stalled_writer)
    receiver = respx_mock.post(ENDPOINT).mock(side_effect=stalled_receiver)
    settings = {**cfg.tracing, "otlp_endpoint": ENDPOINT, "otlp_timeout_s": 6.0}
    async with _recorder(settings) as recorder:
        def record_turn():
            with recorder.span("session_turn", category="turn"):
                pass

        try:
            record_turn()
            await _until(export_stalled.is_set)
            record_turn()
            await _until(writer_stalled.is_set)
            started = time.monotonic()
            for _ in range(trace_store.QUEUE_SIZE + 6):
                record_turn()
            assert time.monotonic() - started < 2
            assert recorder.health()["dropped_spans"] == 6
            assert len(_rows()) == 1

            release_writer.set()
            await _until(lambda: recorder.health()["export_dropped_spans"] > 0)
            assert len(_rows()) == 2 + trace_store.QUEUE_SIZE
            assert not release_export.is_set()

            writer_stalled.clear()
            release_writer.clear()
            record_turn()
            await _until(writer_stalled.is_set)
            release_export.set()
            await _until(lambda: receiver.call_count > 1)
            assert len(_rows()) == 2 + trace_store.QUEUE_SIZE
        finally:
            release_writer.set()
            release_export.set()
        await _until(lambda: receiver.called)

    def unavailable_path():
        raise OSError("private filesystem detail")

    monkeypatch.setattr(trace_store, "_path", unavailable_path)
    recorder = tracing.TraceRecorder(cfg.tracing)
    await recorder.astart()
    try:
        await _until(lambda: recorder.health()["diagnostic"] == "trace_store_unavailable")
        with recorder.span("session_turn", category="turn") as span:
            assert span.ref.trace_id is None
        assert recorder.health()["sqlite_errors"] == 1
    finally:
        await recorder.aclose()


def test_trace_routes_paginate_and_flag_missing_parent(cfg, tmp_path, monkeypatch):
    async def no_network_checks(_checker):
        pass

    monkeypatch.setattr(StatusChecker, "astart", no_network_checks)
    custom_model = "local-catalog-model"
    config = cfg.model_copy(update={"tracing": {**cfg.tracing, "max_spans": 6},
                                    "models": {**cfg.models, custom_model: ModelConfig(provider="openai")}})
    state = AppState(config=config, db_path=tmp_path / "app.db")
    headers = {"Authorization": "Bearer test-token"}
    session_id, other_id = new_id("ses_"), new_id("ses_")
    run_id, other_run_id = new_id("run_"), new_id("run_")
    recorder = state.tracing
    with TestClient(create_app("test-token", state)) as client:
        assert client.get("/api/traces").status_code == 401
        parent = recorder.start("session_turn", category="turn", session_id=session_id, run_id=run_id,
                                attrs={"gen_ai.conversation.id": other_id, "gdw.run.id": other_run_id})
        parent.end()
        child = recorder.start("execute_tool", category="tool", parent=parent.ref)
        child.end()
        grandchild = recorder.start("tools/call", category="mcp", parent=child.ref)
        grandchild.end()
        roots = []
        for sid in (session_id, session_id, session_id, other_id):
            with recorder.span("session_turn", category="turn",
                               attrs={"gen_ai.conversation.id": sid, "gdw.run.id": run_id,
                                      "gen_ai.request.model": custom_model}) as span:
                span.set_attribute("gen_ai.conversation.id", new_id("ses_"))
                span.set_attributes({"gdw.run.id": other_run_id})
                assert recorder.capture() == span.ref
                assert (span.ref.session_id, span.ref.run_id) == (sid, run_id)
                roots.append(span.ref)

        deadline = time.monotonic() + 5
        while True:
            result = client.get("/api/traces", headers=headers).json()
            if result["traces"] and result["traces"][0]["span_id"] == roots[-1].span_id:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert result["health"]["available"] and result["health"]["dropped_spans"] == 0
        assert len(_rows()) == 6
        with closing(sqlite3.connect(data_dir() / "traces.sqlite3")) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert state.db.all("SELECT 1 FROM sqlite_master WHERE name = 'trace_spans'") == []

        params = {"session_id": session_id, "limit": 2}
        page = client.get("/api/traces", params=params, headers=headers).json()
        assert [row["span_id"] for row in page["traces"]] == [root.span_id for root in roots[2:0:-1]]
        for row in page["traces"]:
            assert row["attrs"]["gen_ai.conversation.id"] == row["session_id"] == session_id
            assert row["attrs"]["gdw.run.id"] == row["run_id"] == run_id
            assert row["attrs"]["gen_ai.request.model"] == custom_model
            assert row["dropped_attributes"] == 2
        page = client.get("/api/traces", params={**params, "cursor": page["next_cursor"]}, headers=headers).json()
        assert [row["span_id"] for row in page["traces"]] == [roots[0].span_id] and page["next_cursor"] is None
        assert client.get("/api/traces?cursor=bad", headers=headers).status_code == 422
        assert client.get("/api/traces?limit=201", headers=headers).status_code == 422

        url = f"/api/traces/{parent.ref.trace_id}"
        page = client.get(url, params={"limit": 1}, headers=headers).json()
        row, = page["spans"]
        assert row["span_id"] == child.ref.span_id and row["parent_span_id"] == parent.ref.span_id
        assert row["attrs"]["gen_ai.conversation.id"] == row["session_id"] == session_id
        assert row["attrs"]["gdw.run.id"] == row["run_id"] == run_id
        assert row["missing_parent"] and page["missing_parent"]
        follow = client.get(url, params={"limit": 1, "cursor": page["next_cursor"]}, headers=headers).json()
        row, = follow["spans"]
        assert row["span_id"] == grandchild.ref.span_id and row["parent_span_id"] == child.ref.span_id
        assert not row["missing_parent"] and not follow["missing_parent"] and follow["next_cursor"] is None

        with recorder.span("session_turn", category="turn", session_id=session_id) as pending:
            pass
    assert not recorder.available
    assert pending.ref.span_id in {row["span_id"] for row in _rows()}

    with closing(sqlite3.connect(data_dir() / "traces.sqlite3")) as conn, conn:
        conn.execute("UPDATE trace_spans SET start_ns = 1, end_ns = 1 WHERE span_id = ?", (pending.ref.span_id,))

    async def restart():
        async with _recorder(cfg.tracing):
            assert pending.ref.span_id not in {row["span_id"] for row in _rows()}

    asyncio.run(restart())
