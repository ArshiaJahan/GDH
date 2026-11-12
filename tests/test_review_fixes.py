"""Regression tests for issues found in the spec review."""
import asyncio
import json
import os
import subprocess

import httpx
import pytest
import respx

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import FileBlock, Message
from gamedevworkstation.features import subagents as subs_mod
from gamedevworkstation.providers.fake import FakeProvider, text_response

from .conftest import FIXTURES
from .mockhttp import MockAPI, jresp


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "r.db")
    a.providers.override("anthropic", "default", FakeProvider("anthropic"))
    a.providers.override("openai", "default", FakeProvider("openai"))
    from fastapi import APIRouter, FastAPI
    from gamedevworkstation.routes import register_routes

    register_routes(FastAPI(), APIRouter(), a)
    return a


async def test_search_skips_symlinks_out_of_folder(app, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET-123")
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "ok.txt").write_text("TOPSECRET-in-folder")
    os.symlink(secret, folder / "link.txt")
    ctx = ToolContext(app=app, session=app.store.create(folder=str(folder)), run_id="main:x")
    out = await app.tools.run(ctx, "search", {"pattern": "TOPSECRET"})
    assert "ok.txt" in out.text and "link.txt" not in out.text and "123" not in out.text


async def test_subagent_cannot_reach_sibling_worktrees(app, tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    s = app.store.create(folder=str(folder))
    wroot = app.worktrees_root(s["id"])
    (wroot / "sub_a").mkdir(parents=True)
    (wroot / "sub_b").mkdir(parents=True)
    ctx = ToolContext(app=app, session=s, run_id="sub_a", role="subagent", extra_roots=[wroot / "sub_a"],
                      cwd_override=wroot / "sub_a")
    out = await app.tools.run(ctx, "write_file", {"path": str(wroot / "sub_b" / "x.txt"), "content": "no"},
                              allowed=["write_file"])
    assert out.is_error and "outside" in out.text


async def test_data_policy_applies_to_every_request(app, tmp_path):
    f = tmp_path / "medical.pdf"
    f.write_bytes(b"%PDF-1.4 private")
    s = app.store.create(folder=str(tmp_path))
    iid = app.items.add_file(f, source="user", session_id=s["id"], provider="anthropic", model="claude-opus-5-5")
    app.db.update("items", "id", iid, {"meta": json.dumps({"sensitive": True})})
    app.config.data_policy["sensitive_allowed"] = ["anthropic"]
    msgs = [Message.user("summarize", FileBlock.from_path(f, item_id=iid))]
    assert app.policy.filter_messages(msgs, "anthropic") is msgs
    out = app.policy.filter_messages(msgs, "openai")
    assert out[0].content[1].type == "text" and "withheld" in out[0].content[1].text
    ctx = ToolContext(app=app, session=s, run_id="sub_x", role="subagent", provider="openai")
    assert (await app.tools.run(ctx, "read_file", {"path": "medical.pdf"})).is_error
    assert (await app.tools.run(ctx, "get_item", {"id": iid})).is_error


async def test_job_budget_and_spend_checks_for_spawns(app, tmp_path):
    from gamedevworkstation.core.types import Usage

    s = app.store.create()
    app.turn_started[s["id"]] = 0
    app.config.delegation["job_budget_usd"] = 0.05
    app.usage.record(provider="anthropic", model="claude-opus-5-5", usage=Usage(cost_usd=0.06), session_id=s["id"])
    ctx = ToolContext(app=app, session=s, run_id=f"main:{s['id']}")
    out = await app.tools.run(ctx, "spawn_subagent", {"name": "x", "tier": "claude.fast", "instructions": "y"})
    assert out.is_error and "job_budget_usd" in out.text
    app.config.delegation["job_budget_usd"] = 100
    app.config.limits["global_daily_usd"] = 0.01
    out = await app.tools.run(ctx, "spawn_subagent", {"name": "x", "tier": "codex.fast", "instructions": "y"})
    assert out.is_error and "limit" in out.text.lower()


async def test_concurrent_writers_get_worktrees(app, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a").write_text("a")
    for c in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"]):
        subprocess.run(c, cwd=repo, check=True)
    app.providers.chat("anthropic").delay = 0.3
    s = app.store.create(folder=str(repo), mode="accept_edits")
    ctx = ToolContext(app=app, session=s, run_id=f"main:{s['id']}")
    w = {"tier": "claude.fast", "instructions": "edit", "tools": ["read_file", "write_file"]}
    await app.tools.run(ctx, "spawn_subagent", {**w, "name": "first"})
    await app.tools.run(ctx, "spawn_subagent", {**w, "name": "second"})
    mgr = app.extensions["subagents"]
    first, second = sorted(mgr.subs.values(), key=lambda x: x.started)
    assert not first.want_worktree and second.want_worktree  # decided at spawn, created once it gets a slot
    await asyncio.wait_for(asyncio.gather(first.done_event.wait(), second.done_event.wait()), 10)
    assert first.worktree is None and second.worktree is not None


async def test_cancel_on_effort_card_stops_the_turn(app):
    s = app.store.create(effort="max")
    app.store.add_message(s["id"], Message.user("go"))
    task = app.runner.start(s["id"])
    for _ in range(100):
        pend = app.approvals.pending(s["id"])
        if pend:
            break
        await asyncio.sleep(0.01)
    app.approvals.resolve(pend[0]["id"], "deny")
    await task
    assert not app.providers.chat("anthropic").calls
    assert "Cancelled" in app.store.messages(s["id"])[-1].text()


async def test_tts_threshold_counts_characters(app, monkeypatch):
    svc = app.extensions["elevenlabs"]
    app.config.elevenlabs["confirm_over_characters"] = 2000
    asked = {}

    async def fake_ask(sid, kind, payload):
        asked["payload"] = payload
        return {"status": "denied"}

    monkeypatch.setattr(app.approvals, "ask", fake_ask)
    from gamedevworkstation.agent.tools import ToolDenied

    with pytest.raises(ToolDenied):  # 3,000 chars on a cheap model still asks
        await svc._confirm("s", "agent", "tts", credits=1500, preview="x", characters=3000)
    assert asked["payload"]["characters"] == 3000


@respx.mock
async def test_web_fetch_reads_pages_and_blocks_local(app, monkeypatch):
    async def resolve(host, port):  # no real DNS; safe_fetch connects to the address it checked
        return {"example.org": ["93.184.216.34"]}.get(host, ["127.0.0.1"])

    monkeypatch.setattr("gamedevworkstation.safe_fetch._getaddrinfo", resolve)
    respx.get("https://93.184.216.34/post", headers={"Host": "example.org"}).mock(return_value=httpx.Response(
        200, text="<html><title>Hello post</title><body><script>x()</script><p>Body text here.</p></body></html>",
        headers={"content-type": "text/html"}))
    s = app.store.create()
    ctx = ToolContext(app=app, session=s, run_id="main:x")
    out = await app.tools.run(ctx, "web_fetch", {"url": "https://example.org/post"})
    assert "Hello post" in out.text and "Body text here." in out.text and "x()" not in out.text
    link = app.items.list(session_id=s["id"], tab="links")[0]
    assert link["subtype"] == "fetched" and link["title"] == "Hello post"
    bad = await app.tools.run(ctx, "web_fetch", {"url": "http://127.0.0.1:8765/api/sessions"})
    assert bad.is_error and "private" in bad.text


async def test_web_search_returns_cited_findings(app):
    import anthropic

    from gamedevworkstation.providers.anthropic_provider import AnthropicProvider

    body = {"id": "msg_ws", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "stop_reason": "end_turn",
            "stop_sequence": None,
            "content": [{"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "x"}},
                        {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
                            {"type": "web_search_result", "url": "https://a.example/doc", "title": "Doc A",
                             "encrypted_content": "E", "page_age": None}]},
                        {"type": "text", "text": "- Refresh tokens rotate on use.", "citations": [
                            {"type": "web_search_result_location", "url": "https://a.example/doc", "title": "Doc A",
                             "encrypted_index": "I", "cited_text": "rotate"}]}],
            "usage": {"input_tokens": 3000, "output_tokens": 200, "server_tool_use": {"web_search_requests": 2}}}
    api = MockAPI().add("POST", "/v1/messages", jresp(200, body))
    app.providers.override("anthropic", "default", AnthropicProvider(config=app.config, client=anthropic.AsyncAnthropic(
        api_key="k", base_url="https://api.anthropic.com", http_client=api.client(), max_retries=0)))
    s = app.store.create()
    out = await app.tools.run(ToolContext(app=app, session=s, run_id="main:x", provider="openai", model="gpt-6.1-sol"),
                              "web_search", {"query": "refresh token rotation"})
    assert "rotate on use" in out.text and "https://a.example/doc" in out.text
    sent = api.json_body()
    assert sent["tools"][0]["type"] == "web_search_20250305" and sent["model"] == "claude-haiku-5-5"
    cost = app.db.one("SELECT cost_usd FROM usage_records WHERE feature='web_search'")["cost_usd"]
    assert cost == pytest.approx(0.02 + (3000 * 0.10 + 200 * 0.50) / 1e6)
    assert app.items.list(session_id=s["id"], tab="links")[0]["provider"] == "openai"
