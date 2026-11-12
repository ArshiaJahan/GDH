"""Regression tests for the spend-limit, Stop, rate-limit and estimate audit findings."""
import asyncio
import os
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from workspace import usage as usage_mod
from workspace.agent.tools import ToolContext
from workspace.app import AppState
from workspace.core.types import ChatRequest, Message, Response, Usage
from workspace.providers import base as pb
from workspace.providers.base import ProviderError, backoff_wait, retry_after_from
from workspace.providers.fake import FakeProvider, text_response
from workspace.server import create_app
from workspace.usage import BudgetExceeded

H = {"Authorization": "Bearer t"}


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "l.db")
    a.providers.override("anthropic", "default", FakeProvider("anthropic"))
    a.providers.override("openai", "default", FakeProvider("openai"))
    from fastapi import APIRouter, FastAPI
    from workspace.routes import register_routes

    register_routes(FastAPI(), APIRouter(), a)
    return a


def _spend(app, usd, sid=None):
    app.usage.record(provider="anthropic", model="claude-haiku-5-5", usage=Usage(cost_usd=usd), session_id=sid)


def _events(app, type_, since=0):
    return [e for e in app.bus.replay(since) if e["type"] == type_]


async def _until(cond, timeout=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return
        await asyncio.sleep(0.02)
    raise TimeoutError


# ------------------------------------------------------------------ 1. daily limit


def test_daily_pause_lifts_when_the_day_changes(app, monkeypatch):
    app.config.limits["global_daily_usd"] = 0.01
    _spend(app, 0.02)
    with pytest.raises(BudgetExceeded):
        app.usage.check()
    assert app.usage.paused_all
    paused = _events(app, "limits.paused")
    assert paused and paused[-1]["data"]["scope"] == "global" and paused[-1]["data"]["spent_usd"] == 0.02
    seq = app.bus.last_seq()
    tomorrow = usage_mod._day_start() + 86400
    monkeypatch.setattr(usage_mod, "_day_start", lambda: tomorrow)
    app.usage.check()  # no restart needed: the next check sees the new day
    assert not app.usage.paused_all
    resumed = _events(app, "limits.resumed", seq)
    assert [e["data"]["reason"] for e in resumed] == ["new_day"]


def test_resume_anyway_allows_another_limit_then_pauses_again(app):
    app.config.limits["global_daily_usd"] = 0.01
    _spend(app, 0.02)
    with pytest.raises(BudgetExceeded):
        app.usage.check()
    app.usage.resume_all()
    app.usage.check()  # used to re-pause at once because today's spend was still over the limit
    assert not app.usage.paused_all and app.usage.status()["global"] is None
    _spend(app, 0.011)  # another limit's worth
    with pytest.raises(BudgetExceeded):
        app.usage.check()


def test_raising_the_limit_lifts_the_pause(app):
    app.config.limits["global_daily_usd"] = 0.01
    _spend(app, 0.02)
    assert app.usage.status()["global"]["limit_usd"] == 0.01
    app.config.limits["global_daily_usd"] = 5
    assert app.usage.status()["global"] is None
    assert _events(app, "limits.resumed")[-1]["data"]["reason"] == "limit_raised"


def test_session_pause_is_scoped_and_resumable(app):
    app.config.limits["session_usd"] = 0.05
    a, b = app.store.create()["id"], app.store.create()["id"]
    _spend(app, 0.06, a)
    _spend(app, 0.06, a)  # published once, not on every record
    paused = _events(app, "limits.paused")
    assert len(paused) == 1 and paused[0]["session_id"] == a and paused[0]["data"]["scope"] == "session"
    with pytest.raises(BudgetExceeded):
        app.usage.check(a)
    app.usage.check(b)
    assert set(app.usage.status()["sessions"]) == {a}
    app.usage.resume_session(a)
    app.usage.check(a)
    assert app.usage.status()["sessions"] == {}


def test_limits_api_status_and_resume(tmp_path):
    state = AppState(db_path=tmp_path / "s.db")
    state.config.limits["global_daily_usd"] = 0.01
    state.config.limits["session_usd"] = 0.01
    sid = state.store.create()["id"]
    _spend(state, 0.02, sid)
    with TestClient(create_app("t", state)) as c:
        st = c.get("/api/limits", headers=H).json()
        assert st["global"]["spent_usd"] == 0.02 and sid in st["sessions"]
        st = c.post("/api/limits/resume", json={"session_id": sid}, headers=H).json()
        assert st["sessions"] == {} and st["global"] is not None
        st = c.post("/api/limits/resume", headers=H).json()
        assert st["global"] is None


# ------------------------------------------------------------- 2. Stop stops everything


async def test_stop_cancels_the_sessions_subagents_commands_cli_and_approvals(app, tmp_path):
    slow = FakeProvider("anthropic", delay=30)
    app.providers.override("anthropic", "default", slow)
    app.config.modes["allowlist"] = ["run_command:*"]
    folder = tmp_path / "f"
    folder.mkdir()
    a = app.store.create(folder=str(folder), mode="accept_edits")
    b = app.store.create(folder=str(folder), mode="accept_edits")
    ctx_a = ToolContext(app=app, session=a, run_id=f"main:{a['id']}")
    ctx_b = ToolContext(app=app, session=b, run_id=f"main:{b['id']}")
    mgr = app.extensions["subagents"]
    for i in range(2):
        await app.tools.run(ctx_a, "spawn_subagent", {"name": f"a{i}", "tier": "claude.fast", "instructions": "x"})
    await app.tools.run(ctx_b, "spawn_subagent", {"name": "b0", "tier": "claude.fast", "instructions": "x"})
    out = await app.tools.run(ctx_a, "run_command", {"command": "sleep 30", "background": True})
    assert "background" in out.text
    # A Codex CLI process (stand-in) with a child in its process group.
    cli_job = app.jobs.start(a["id"], "codex_cli", "Codex CLI turn")
    cli = await asyncio.create_subprocess_exec("sh", "-c", "sleep 30 & sleep 30", start_new_session=True)
    app.jobs.procs[cli_job] = cli
    waiter = asyncio.create_task(app.approvals.ask(a["id"], "command", {"command": "rm -rf build"}))
    await _until(lambda: all(s.status == "running" for s in mgr.subs.values()) and app.approvals.pending(a["id"]))
    cmd_job = next(j for j in app.jobs.list(a["id"]) if j["kind"] == "command")
    cmd_proc = app.jobs.procs[cmd_job["id"]]

    assert await app.runner.stop(a["id"])

    await _until(lambda: all(s.status == "cancelled" for s in mgr.subs.values() if s.session_id == a["id"]))
    assert (await asyncio.wait_for(waiter, 2))["status"] == "denied"
    assert app.approvals.pending(a["id"]) == []
    await asyncio.wait_for(cli.wait(), 3)
    await asyncio.wait_for(cmd_proc.wait(), 3)
    with pytest.raises(ProcessLookupError):  # the whole group, not just the shell
        for _ in range(100):
            os.killpg(cli.pid, 0)
            await asyncio.sleep(0.03)
    jobs = {j["id"]: j for j in app.jobs.list(a["id"])}
    assert jobs[cmd_job["id"]]["status"] == "cancelled" and jobs[cli_job]["status"] == "cancelled"
    assert all(j["status"] == "cancelled" for j in jobs.values() if j["kind"] == "subagent")
    ev = _events(app, "session.stopped")[-1]
    assert ev["session_id"] == a["id"] and ev["data"]["subagents"] == 2 and ev["data"]["jobs"] == 2
    # The other session is left alone.
    other = next(s for s in mgr.subs.values() if s.session_id == b["id"])
    assert other.status == "running"
    await app.runner.stop(b["id"])
    await _until(lambda: other.status == "cancelled")


async def test_stop_closes_a_subagent_cancelled_before_it_started(app):
    s = app.store.create()
    ctx = ToolContext(app=app, session=s, run_id=f"main:{s['id']}")
    mgr = app.extensions["subagents"]
    await app.tools.run(ctx, "spawn_subagent", {"name": "early", "tier": "claude.fast", "instructions": "x"})
    sub = next(iter(mgr.subs.values()))
    await app.runner.stop(s["id"])  # before the task ever ran
    await asyncio.wait_for(sub.done_event.wait(), 2)
    assert sub.status == "cancelled"


# ------------------------------------------------------------------ 3. rate limits


class Flaky(FakeProvider):
    def __init__(self, failures, retry_after=None):
        super().__init__("anthropic")
        self.failures, self.retry_after = failures, retry_after

    async def complete(self, req: ChatRequest) -> Response:
        if self.failures:
            self.failures -= 1
            raise ProviderError("429 rate limited", status=429, rate_limited=True, retry_after=self.retry_after)
        return await super().complete(req)


async def test_main_agent_backs_off_on_rate_limits(app, monkeypatch):
    monkeypatch.setattr(pb, "BACKOFF_START_S", 0.01)
    app.providers.override("anthropic", "default", Flaky(2))
    s = app.store.create()
    app.store.add_message(s["id"], Message.user("hello"))
    await app.runner.start(s["id"])
    assert app.store.messages(s["id"])[-1].text() == "echo: hello"
    status = [e["data"] for e in _events(app, "agent.status")]
    assert [d["kind"] for d in status] == ["rate_limit", None, "rate_limit", None]
    assert status[0]["text"].startswith("Rate limited, retrying in")
    errs = app.db.all("SELECT error_kind FROM usage_records WHERE session_id=? AND ok=0", [s["id"]])
    assert [r["error_kind"] for r in errs] == ["rate_limit", "rate_limit"]


async def test_main_agent_gives_up_after_bounded_retries(app, monkeypatch):
    monkeypatch.setattr(pb, "BACKOFF_START_S", 0.001)
    app.providers.override("anthropic", "default", Flaky(100))
    s = app.store.create()
    app.store.add_message(s["id"], Message.user("hello"))
    await app.runner.start(s["id"])
    assert "rate limited" in app.store.messages(s["id"])[-1].text()
    assert len(_events(app, "agent.status")) == 2 * pb.MAX_RATE_RETRIES


async def test_stop_cancels_the_rate_limit_wait(app):
    app.providers.override("anthropic", "default", Flaky(100, retry_after=30))
    s = app.store.create()
    app.store.add_message(s["id"], Message.user("hello"))
    task = app.runner.start(s["id"])
    await _until(lambda: _events(app, "agent.status"))
    assert "retrying in 30s" in _events(app, "agent.status")[0]["data"]["text"]  # retry-after honoured
    t0 = time.monotonic()
    await app.runner.stop(s["id"])
    await asyncio.wait_for(task, 2)
    assert time.monotonic() - t0 < 2
    assert _events(app, "agent.status")[-1]["data"]["kind"] is None
    assert _events(app, "agent.stopped")


def test_retry_after_parsing_and_cap():
    req = httpx.Request("POST", "https://x")
    e = type("E", (Exception,), {})()
    e.response = httpx.Response(429, headers={"retry-after": "7"}, request=req)
    assert retry_after_from(e) == 7
    e.response = httpx.Response(429, headers={"retry-after-ms": "1500"}, request=req)
    assert retry_after_from(e) == 1.5
    assert retry_after_from(ValueError()) is None
    assert backoff_wait(ProviderError("x", rate_limited=True, retry_after=9), 2) == 9
    assert backoff_wait(ProviderError("x", rate_limited=True, retry_after=9999), 2) == pb.RETRY_AFTER_MAX_S
    assert backoff_wait(ProviderError("x", rate_limited=True), 500) == pb.BACKOFF_MAX_S


# --------------------------------------------------------------- 4. ElevenLabs 402


def test_elevenlabs_endpoints_return_402_on_spend_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    state = AppState(db_path=tmp_path / "e.db")
    state.config.limits["global_daily_usd"] = 0.01
    _spend(state, 0.02)
    with TestClient(create_app("t", state), raise_server_exceptions=False) as c:
        for path, body in [("/api/elevenlabs/tts", {"text": "hi"}), ("/api/elevenlabs/sfx", {"text": "boom"}),
                           ("/api/elevenlabs/music", {"prompt": "jazz"}),
                           ("/api/elevenlabs/voice-changer", {"path": str(tmp_path / "a.mp3"), "voice_id": "v"}),
                           ("/api/elevenlabs/stt", {"path": str(tmp_path / "a.mp3")})]:
            r = c.post(path, json=body, headers=H)
            assert r.status_code == 402, (path, r.status_code, r.text)
            assert "spend limit" in r.json()["detail"]


# ------------------------------------------------------------ 5. above-high estimate


def test_above_high_estimate_uses_session_history(app):
    s = app.store.create(effort="max")
    price = app.config.model(app.config.resolve(s["model"])).output
    est = app.runner.estimate_above_high(s, "xhigh")  # no history: the documented default
    assert est["est_extra_cost_usd"] == round(2000 * 1.0 * price / 1e6, 4) and est["est_extra_time_s"] == 30
    for eff, out, ms in [("high", 1000, 10000), ("medium", 700, 7000)]:  # both normalise to 1,000 / 10 s at high
        app.usage.record(provider="anthropic", model=s["model"], usage=Usage(output_tokens=out), session_id=s["id"],
                         role="main", effort=eff, latency_ms=ms)
    est = app.runner.estimate_above_high(s, "max")
    assert est["est_extra_cost_usd"] == round(1000 * 3.0 * price / 1e6, 4)
    assert est["est_extra_time_s"] == 30 and "last 2" in est["est_basis"]


async def test_main_effort_card_carries_the_estimate(app):
    s = app.store.create(effort="max")
    app.store.add_message(s["id"], Message.user("go"))
    task = app.runner.start(s["id"])
    await _until(lambda: app.approvals.pending(s["id"]))
    p = app.approvals.pending(s["id"])[0]["payload"]
    assert p["est_extra_cost_usd"] > 0 and p["est_extra_time_s"] > 0
    app.approvals.resolve(app.approvals.pending(s["id"])[0]["id"], "deny")
    await task
