"""WP0 foundations: the hook bus, the events the loop and subagents fire, Tool.when, and the
shared contracts (migration v3, config sections, generic approval answers)."""
import asyncio
import json
import os
import subprocess
import time

import pytest

from gamedevworkstation.agent import context as cx
from gamedevworkstation.agent.loop import BASE_SYSTEM
from gamedevworkstation.agent.tools import Tool, ToolContext, ToolOutput, ToolRegistry, obj
from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Message, ToolResultBlock, ToolSpec
from gamedevworkstation.db import DB, SCHEMA_VERSION
from gamedevworkstation.features.hookbus import (EVENTS, HookEvent, HookResult, TurnState, changed_files, glob_match,
                                        hook_context)
from gamedevworkstation.features.subagents import SubagentManager, _register_tools
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response
from gamedevworkstation.skills import skills_prompt, system_skill_segments

from .conftest import untrusted
from .test_subagents import SmartFake


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "h.db")
    a.fake = FakeProvider()
    a.providers.override("anthropic", "default", a.fake)
    return a


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "a.txt").write_text("alpha\n")
    return d


def session(app, folder=None, mode="accept_edits", **settings):
    return app.store.create(folder=str(folder) if folder else None, mode=mode, **settings)


async def turn(app, sid, text="hi"):
    app.store.add_message(sid, Message.user(text))
    await app.runner.start(sid)


def msgs(app, sid):
    return app.store.messages(sid)


def events(app, sid, kind):
    return [e for e in app.bus.replay(0, sid) if e["type"] == kind]


# ------------------------------------------------------------------ zero hooks


async def test_zero_hooks_turn_is_unchanged(app, folder):
    s = session(app, folder)
    app.fake.script = [tool_response("read_file", {"path": "a.txt"}), text_response("done")]
    await turn(app, s["id"])
    m = msgs(app, s["id"])
    assert [x.role for x in m] == ["user", "assistant", "user", "assistant"]
    assert not any(x.meta.get("gate") or x.meta.get("notice") for x in m)
    res = m[2].content[0]
    assert isinstance(res, ToolResultBlock) and res.content[0].text == "1\talpha"
    assert app.db.one("SELECT COUNT(*) n FROM gate_runs")["n"] == 0
    assert not events(app, s["id"], "hooks.error") and not events(app, s["id"], "gate.result")
    assert app.hooks.turns == {}  # the turn's state is dropped at turn end


def test_system_segments_match_legacy_layout(app):
    app.config.skills["disclosure"] = "full"  # a legacy session; progressive: tests/test_skill_disclosure.py
    s = session(app)
    seg = app.runner.system_segments(s)
    legacy_skills = "Enabled skills:\n\n" + skills_prompt(s["settings"]["skills"])
    assert seg[0] == BASE_SYSTEM and seg[1] == legacy_skills and len(seg) == 3
    assert system_skill_segments({"skills": []}) == [] and system_skill_segments({}) == []
    # A frozen context pack is the last segment, verbatim.
    s2 = app.store.update(s["id"], settings={"context_pack": {"text": "PACK", "sha": "x"}})
    assert app.runner.system_segments(s2)[-1] == "PACK" and app.runner.system_segments(s2)[:-1] == seg


async def test_fire_without_handlers_returns_empty_without_awaiting(app):
    s = session(app)
    ev = HookEvent("pre_tool", ToolContext(app=app, session=s, run_id="x"), tool="read_file")
    coro = app.hooks.fire(ev)
    with pytest.raises(StopIteration) as done:  # finishes on the first step: nothing awaited
        coro.send(None)
    assert done.value.value == []


# ---------------------------------------------------------- registry semantics


async def test_order_fail_open_closed_when_and_replace(app):
    s = session(app)
    ctx = ToolContext(app=app, session=s, run_id="x")
    seen = []

    def mk(name, result=None, exc=None):
        def fn(ev):
            seen.append(name)
            if exc:
                raise exc
            return result
        return fn

    hb = app.hooks
    hb.register("post_tool", "late", mk("late", HookResult(note="L")), order=200)
    hb.register("post_tool", "early", mk("early", HookResult(note="E")), order=10)
    hb.register("post_tool", "quiet", mk("quiet"), order=50)  # None = nothing to say
    hb.register("post_tool", "crash-open", mk("crash-open", exc=RuntimeError("boom")), order=60)

    async def async_hook(ev):
        seen.append("async")
        return [HookResult(note="A1"), HookResult(note="A2")]

    hb.register("post_tool", "async", async_hook, order=70)
    hb.register("post_tool", "skipped", mk("skipped", HookResult(note="S")), when=lambda ev: ev.tool == "other")
    res = await hb.fire(HookEvent("post_tool", ctx, tool="read_file"))
    assert seen == ["early", "quiet", "crash-open", "async", "late"]
    assert [(r.hook, r.note) for r in res if r.note] == [("early", "E"), ("async", "A1"), ("async", "A2"), ("late", "L")]
    err = next(r for r in res if r.hook == "crash-open")
    assert err.action == "allow" and err.status == "error" and "boom" in err.reason
    assert events(app, s["id"], "hooks.error")[0]["data"]["hook"] == "crash-open"  # loudly

    # fail closed: a crashing guard (or a bad return value) blocks; stop_on_block stops there.
    hb.register("pre_tool", "guard", mk("guard", exc=ValueError("bad")), fail="closed", order=1)
    hb.register("pre_tool", "after", mk("after", HookResult(note="never")), order=2)
    seen.clear()
    res = await hb.fire(HookEvent("pre_tool", ctx, tool="write_file"), stop_on_block=True)
    assert seen == ["guard"] and len(res) == 1 and res[0].action == "block" and res[0].status == "error"
    assert "Blocked by guard" in res[0].block_text()
    hb.register("pre_tool", "guard", lambda ev: "not a result", fail="closed", order=1)  # replaces
    assert hb.handlers("pre_tool") == ["guard", "after"]
    res = await hb.fire(HookEvent("pre_tool", ctx, tool="write_file"), stop_on_block=True)
    assert res[0].action == "block"

    # The master switch turns everything off.
    app.config.hooks = {**app.config.hooks, "enabled": False}
    assert await hb.fire(HookEvent("pre_tool", ctx, tool="write_file")) == [] and not hb.has("pre_tool")
    app.config.hooks = {**app.config.hooks, "enabled": True}
    assert hb.unregister(None, "guard") == 1 and hb.handlers("pre_tool") == ["after"]
    with pytest.raises(ValueError):
        hb.register("pre_toool", "typo", lambda ev: None)
    with pytest.raises(ValueError):
        hb.register("pre_tool", "x", lambda ev: None, fail="maybe")
    assert set(EVENTS) == {"session_start", "model_call", "pre_tool", "post_tool", "pre_complete", "pre_compact",
                           "pre_merge", "post_merge", "turn_end"}


# ------------------------------------------------------------- tool hooks, main


async def test_pre_tool_block_main_agent(app, folder):
    s = session(app, folder)
    got = []

    def guard(ev: HookEvent):
        got.append((ev.tool, ev.path_args(), ev.ctx.role, ev.turn is not None, ev.unit))
        if ev.tool == "write_file" and "a.txt" in ev.path_args()[0]:
            return HookResult(action="block", reason="Generated file. Change the source instead.", gate="gen")
        return None

    app.hooks.register("pre_tool", "block-generated", guard, fail="closed")
    app.fake.script = [tool_response("write_file", {"path": "a.txt", "content": "x"}), text_response("ok")]
    await turn(app, s["id"])
    res = msgs(app, s["id"])[2].content[0]
    assert res.is_error and res.content[0].text == "Blocked by gen: Generated file. Change the source instead."
    assert (folder / "a.txt").read_text() == "alpha\n"
    assert got == [("write_file", ["a.txt"], "main", True, None)]
    fin = events(app, s["id"], "tool.finished")[0]["data"]
    assert fin["is_error"] and "Blocked by gen" in fin["output"]


async def test_post_tool_note_appended(app, folder):
    s = session(app, folder)
    outs = []

    def note(ev: HookEvent):
        outs.append(ev.output.text)
        return HookResult(action="note", note="[Project rule PM-007: reset pooled feedback]")

    app.hooks.register("post_tool", "scars", note, when=lambda ev: ev.tool == "read_file")
    app.fake.script = [tool_response("read_file", {"path": "a.txt"}), text_response("ok")]
    await turn(app, s["id"])
    res = msgs(app, s["id"])[2].content[0]
    assert res.content[0].text == "1\talpha\n\n[Project rule PM-007: reset pooled feedback]" and not res.is_error
    assert outs == ["1\talpha"]


async def test_post_tool_request_stop_ends_turn(app, folder):
    s = session(app, folder)

    def breaker(ev: HookEvent):
        ev.turn.request_stop("Stopped: read_file failed 5 times.", kind="tool_failure_breaker")

    app.hooks.register("post_tool", "breaker", breaker)
    app.fake.script = [tool_response("read_file", {"path": "a.txt"}), text_response("never")]
    await turn(app, s["id"])
    m = msgs(app, s["id"])
    assert m[-1].meta.get("notice") == "tool_failure_breaker" and len(app.fake.calls) == 1
    assert any(x.meta.get("tool_results") for x in m)  # the results were stored before stopping


# ------------------------------------------------------- tool hooks, subagent


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    (d / "README.md").write_text("hi\n")
    for c in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
              ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=d, check=True)
    return d


@pytest.fixture
def subapp(tmp_path):
    a = AppState(db_path=tmp_path / "s.db")
    a.claude = SmartFake("anthropic", delay=0)
    a.providers.override("anthropic", "default", a.claude)
    mgr = SubagentManager(a)
    a.extensions["subagents"] = mgr
    _register_tools(a, mgr)
    return a


async def test_pre_tool_block_in_subagent(subapp, repo):
    s = session(subapp, repo)
    ctx = ToolContext(app=subapp, session=s, run_id=f"main:{s['id']}")
    seen = []

    def scope(ev: HookEvent):
        seen.append((ev.tool, ev.ctx.role, ev.unit))
        if ev.ctx.role == "subagent" and ev.tool == "write_file":
            return HookResult(action="block", reason="outside the unit's scope", gate="fleet.scope")

    subapp.hooks.register("pre_tool", "fleet.scope", scope, fail="closed")
    out = await subapp.tools.run(ctx, "spawn_subagent", {
        "name": "w", "tier": "claude.fast", "instructions": "WRITE: out.py now", "tools": ["write_file"],
        "run_in_background": False})
    sub_id = seen[0][2]
    assert seen == [("write_file", "subagent", sub_id)] and sub_id.startswith("sub_")
    assert not (repo / "out.py").exists() and "done" in out.text
    mgr = subapp.extensions["subagents"]
    sub = mgr.get(sub_id)
    mgr._load_history(sub)  # a finished unit's history lives in its transcript
    tool_result = next(b for m in sub.history if m.role == "user" for b in m.content if isinstance(b, ToolResultBlock))
    assert tool_result.is_error and tool_result.content[0].text == "Blocked by fleet.scope: outside the unit's scope"


async def test_pre_and_post_merge(subapp, repo):
    s = session(subapp, repo)
    ctx = ToolContext(app=subapp, session=s, run_id=f"main:{s['id']}")
    out = await subapp.tools.run(ctx, "spawn_subagent", {
        "name": "w", "tier": "claude.fast", "instructions": "WRITE: new.py now", "tools": ["write_file"],
        "worktree": True, "run_in_background": False})
    sub_id = out.text.split(" · ")[1]
    calls = []

    def hold(ev: HookEvent):
        calls.append(("pre", ev.unit, ev.extra["branch"]))
        return HookResult(action="block", reason="new.py is outside the scope", gate="fleet.merge_scope")

    subapp.hooks.register("pre_merge", "scope", hold)
    r = await subapp.tools.run(ctx, "merge_worktree", {"id": sub_id})
    assert r.is_error and r.text.startswith("Merge held. Blocked by fleet.merge_scope") and not (repo / "new.py").exists()
    subapp.hooks.unregister("pre_merge", "scope")
    subapp.hooks.register("post_merge", "compile",
                          lambda ev: calls.append(("post", ev.unit, ev.extra["changes"])) or HookResult(note="L1: compile ok"))
    r = await subapp.tools.run(ctx, "merge_worktree", {"id": sub_id})
    assert not r.is_error and r.text.startswith("Merged w.") and r.text.endswith("\n\nL1: compile ok")
    assert (repo / "new.py").exists()
    assert calls == [("pre", sub_id, f"gdw/{sub_id}"), ("post", sub_id, True)]


# ---------------------------------------------------------------- pre_complete


async def test_failing_gate_retries_twice_then_exhausts(app, folder):
    s = session(app, folder)
    runs = []

    def gate(ev: HookEvent):
        runs.append(dict(ev.turn.retries))
        return HookResult(action="block", gate="unity.compile", reason="3 compile errors.", level="L1",
                          untrusted="Assets/A.cs(3,1): error CS1002: ; expected")

    app.hooks.register("pre_complete", "unity.compile", gate)
    await turn(app, s["id"])
    m = msgs(app, s["id"])
    gates = [x for x in m if x.meta.get("gate")]
    assert [g.meta["gate"]["attempt"] for g in gates] == [1, 2] and all(g.role == "user" for g in gates)
    assert gates[0].meta["gate"] == {"id": "unity.compile", "status": "fail", "attempt": 1, "max": 2,
                                     "hook": "unity.compile", "level": "L1"}
    head, wrapped = gates[0].content[0].text.split("\n\n", 1)
    assert head == "[GameDevWorkstation gate unity.compile] 3 compile errors."
    assert untrusted(wrapped) == ("gate:unity.compile", "Assets/A.cs(3,1): error CS1002: ; expected")
    assert m[-1].meta.get("notice") == "gate_exhausted" and "Needs you." in m[-1].content[0].text
    assert len(app.fake.calls) == 3 and runs == [{}, {"unity.compile": 1}, {"unity.compile": 2}]
    rows = app.db.all("SELECT gate, status, attempt, level FROM gate_runs ORDER BY started_at")
    assert [(r["status"], r["attempt"]) for r in rows] == [("fail", 1), ("fail", 2), ("fail", 3)]
    assert events(app, s["id"], "gate.exhausted")[0]["data"]["gates"] == ["unity.compile"]
    assert len(events(app, s["id"], "gate.result")) == 3
    # The gate messages reach the model; the notice doesn't.
    assert "[GameDevWorkstation gate unity.compile]" in app.fake.calls[1].messages[-1].text()


async def test_passing_gate_ends_normally_and_is_recorded(app, folder):
    s = session(app, folder)
    app.hooks.register("pre_complete", "unity.compile",
                       lambda ev: HookResult(gate="unity.compile", status="pass", reason="0 errors"))
    app.hooks.register("pre_complete", "skipper", lambda ev: HookResult(gate="unity.tests", status="skipped"))
    await turn(app, s["id"])
    m = msgs(app, s["id"])
    assert [x.role for x in m] == ["user", "assistant"] and len(app.fake.calls) == 1
    rows = {r["gate"]: r["status"] for r in app.db.all("SELECT gate, status FROM gate_runs")}
    assert rows == {"unity.compile": "pass", "unity.tests": "skipped"}
    assert {e["data"]["gate"] for e in events(app, s["id"], "gate.result")} == {"unity.compile", "unity.tests"}


async def test_gate_recovers_after_one_fix(app, folder):
    s = session(app, folder)
    state = {"n": 0}

    def gate(ev):
        state["n"] += 1
        return HookResult(action="block", gate="g", reason="red") if state["n"] == 1 else HookResult(gate="g")

    app.hooks.register("pre_complete", "g", gate)
    await turn(app, s["id"])
    m = msgs(app, s["id"])
    assert [x.role for x in m] == ["user", "assistant", "user", "assistant"] and not m[-1].meta.get("notice")


async def test_plan_mode_and_max_tokens_skip_gates(app, folder):
    s = session(app, folder, mode="plan")
    called = []
    app.hooks.register("pre_complete", "g", lambda ev: called.append(1) or HookResult(action="block", reason="x"))
    await turn(app, s["id"])
    assert called == [] and len(app.fake.calls) == 1
    s2 = session(app, folder)
    app.fake.script = [text_response("cut").model_copy(update={"stop_reason": "max_tokens"})]
    await turn(app, s2["id"])
    assert called == [] and msgs(app, s2["id"])[-1].meta.get("notice") == "max_tokens"


# ------------------------------------------------------- other loop events


async def test_session_start_model_call_turn_end(app, folder):
    s = session(app, folder)
    log = []

    def start(ev: HookEvent):
        log.append("session_start")
        app.store.update(ev.session_id, settings={"context_pack": {"text": "Milestone: M3", "sha": "1"}})

    app.hooks.register("session_start", "context.pack", start)
    app.hooks.register("model_call", "hb", lambda ev: log.append(("model_call", ev.extra["call"])))
    app.hooks.register("turn_end", "driver", lambda ev: log.append(
        ("turn_end", ev.extra["ok"], ev.extra["error_kind"], app.runner.is_running(ev.session_id))))
    await turn(app, s["id"])
    assert log == ["session_start", ("model_call", 1), ("turn_end", True, None, True)]
    assert app.fake.calls[0].system[-1] == "Milestone: M3"  # the pack frozen at session start is in the prompt
    await turn(app, s["id"], "again")  # the session has a reply now: no second session_start
    assert log[3:] == [("model_call", 1), ("turn_end", True, None, True)]


async def test_turn_end_reports_errors(app, folder):
    s = session(app, folder)
    got = []
    app.hooks.register("turn_end", "t", lambda ev: got.append((ev.extra["ok"], ev.extra["error_kind"])))

    async def boom(req):
        raise RuntimeError("provider exploded")

    app.fake.complete = boom
    await turn(app, s["id"])
    assert got == [(False, "error")]


async def test_pre_compact_fires(app, folder):
    s = session(app, folder)
    seen = []
    app.hooks.register("pre_compact", "campaign", lambda ev: seen.append(ev.extra))
    for i in range(4):
        app.store.add_message(s["id"], Message.user(f"q{i}"))
        app.store.add_message(s["id"], Message.assistant(f"a{i}"))
    h = app.runner.model_history(s["id"])
    await cx.compact_messages(app, s["id"], h, 4)
    assert seen == [{"auto": False, "cut": 4, "messages": 8}]


# ---------------------------------------------------------------- Tool.when


async def test_tool_when_hides_tools(app, folder):
    reg = app.tools

    async def status(ctx, a):
        return ToolOutput("phase 1/3")

    reg.register(Tool(ToolSpec(name="campaign_status", description="d", input_schema=obj({})), status, main_only=True,
                      when=lambda s: bool(s["settings"].get("campaign_id"))))
    reg.add("broken_when", "d", obj({}), when=lambda s: 1 / 0)(status)
    plain = session(app, folder)
    camp = session(app, folder, campaign_id="cmp_1")
    names = lambda s: {t.name for t in app.runner.tool_specs(s)}  # noqa: E731
    assert "campaign_status" not in names(plain) and "campaign_status" in names(camp)
    assert "broken_when" not in names(camp)
    assert "campaign_status" not in {t.name for t in reg.specs()}  # no session: conditional tools stay out
    out = await reg.run(ToolContext(app=app, session=plain, run_id="x"), "campaign_status", {})
    assert out.is_error and "not available" in out.text
    out = await reg.run(ToolContext(app=app, session=camp, run_id="x"), "campaign_status", {})
    assert out.text == "phase 1/3"
    # Without any `when`, specs are exactly what they were.
    r2 = ToolRegistry()
    r2.add("t", "d", obj({}))(status)
    assert [t.name for t in r2.specs(session=None)] == ["t"]


# ----------------------------------------------------------- utilities


def test_glob_match():
    assert glob_match("Assets/Game/Hit.cs", "*.cs") and glob_match("BACKLOG.md", "BACKLOG.md")
    assert glob_match("Assets/a.cs", "Assets/**/*.cs") and glob_match("Assets/x/y/a.cs", "Assets/**/*.cs")
    assert not glob_match("Packages/a.cs", "Assets/**/*.cs") and not glob_match("Assets/a.csx", "*.cs")
    assert glob_match("Assets/Game/UI/hud.png", "Assets/**/UI/**") and not glob_match("Assets/Game/UIKit/a", "Assets/**/UI/**")
    assert glob_match("Packages/manifest.json", "Packages/manifest.json")
    assert not glob_match("Assets/x/a.cs", "Assets/*.cs") and glob_match("Assets/a.cs", "Assets/*.cs")
    assert glob_match("Library/x", "Library/**") and glob_match("a.csproj", "*.csproj")


def test_changed_files(tmp_path, app):
    root = tmp_path / "unity"
    for rel in ("Assets/Game/Hit.cs", "Assets/Game/Logs/keep.cs", "Library/cache.bin", "Temp/x.cs", "README.md",
                ".git/HEAD", "Assets/old.cs", ".gamedevworkstation/tmp/t.json", "Packages/manifest.json"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    since = time.time() - 100
    old = since - 1000
    os.utime(root / "Assets/old.cs", (old, old))
    got = changed_files(root, since)
    assert got == ["Assets/Game/Hit.cs", "Assets/Game/Logs/keep.cs", "Packages/manifest.json", "README.md"]
    assert changed_files(root, since, ["Assets/**/*.cs"]) == ["Assets/Game/Hit.cs", "Assets/Game/Logs/keep.cs"]
    assert app.hooks.changed_files(root, since, ["*.json"]) == ["Packages/manifest.json"]
    assert TurnState("s", since, folder=root).changed_files(["*.md"]) == ["README.md"]
    assert changed_files(None, since) == [] and changed_files(root / "missing", since) == []


async def test_hook_context_consent(app, folder):
    s = session(app, folder, mode="ask")
    ctx = hook_context(app, s, consent={"run_command": {"echo gate-ok"}})
    assert ctx.role == "hook" and ctx.roots == [folder.resolve()]
    out = await app.tools.run(ctx, "run_command", {"command": "echo gate-ok"})  # consented: no card
    assert "gate-ok" in out.text and not app.approvals.pending()
    await ctx.approve("run_command", "echo gate-ok", {})  # exact subject passes approve() too
    plan = hook_context(app, {**s, "mode": "plan"}, consent={"run_command": {"echo gate-ok"}})
    out = await app.tools.run(plan, "run_command", {"command": "echo gate-ok"})
    assert out.is_error and "Plan only" in out.text  # Plan only still refuses first
    # Agents' contexts carry no consent.
    assert ToolContext(app=app, session=s, run_id="x").consented("run_command", "echo gate-ok") is False


# ------------------------------------------------------ shared contracts


def test_migration_v3_tables(tmp_path):
    db = DB(tmp_path / "m.db")
    assert db.user_version() == SCHEMA_VERSION and SCHEMA_VERSION >= 3  # v4+: later features' tables
    names = {r["name"] for r in db.all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"hook_trust", "gate_runs", "ladder_evidence", "campaigns", "campaign_sessions", "fleet_waves",
            "fleet_units"} <= names
    cols = {r["name"] for r in db.all("PRAGMA table_info(campaigns)")}
    assert {"claim_session", "claim_heartbeat", "breaker", "phases", "autopilot"} <= cols
    db.close()
    assert DB(tmp_path / "m.db").user_version() == SCHEMA_VERSION  # reopening is a no-op


def test_config_sections(app, cfg):
    assert cfg.hooks["enabled"] is True and cfg.hooks["gate_max_retries"] == 2 and app.hooks.max_retries() == 2
    assert cfg.skills["disclosure"] == "progressive" and cfg.skills["max_loaded"] == 3
    assert cfg.skills["mcp_on_invoke"]["unity-router"] == ["unity"]
    assert "*.unity" in cfg.ladder["visual_globs"] and cfg.campaigns["handoff"] == "per_phase"
    assert cfg.fleet["unit_timeout_min"] == {"build": 30, "research": 15}
    from gamedevworkstation.config import invalid_settings

    assert invalid_settings({"hooks": {"gate_max_retries": "lots"}}) == ["hooks.gate_max_retries"]
    assert invalid_settings({"skills": {"mcp_on_invoke": {"x": "unity"}, "max_loaded": 2}}) == []
    assert app.hooks.max_retries(HookResult(max_retries=5)) == 5


def test_settings_patch_new_sections(tmp_path):
    from fastapi.testclient import TestClient

    from gamedevworkstation.server import create_app

    st = AppState(db_path=tmp_path / "t.db")
    h = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", st)) as c:
        r = c.patch("/api/settings", json={"hooks": {"gate_max_retries": 1}}, headers=h)
        assert r.status_code == 200 and r.json()["hooks"]["gate_max_retries"] == 1
        assert st.hooks.max_retries() == 1
        assert c.patch("/api/settings", json={"skills": {"disclosure": "sometimes"}}, headers=h).status_code == 400
        assert c.patch("/api/settings", json={"campaigns": {"handoff": "never"}}, headers=h).status_code == 400


async def test_generic_approval_choice_and_note(app):
    s = session(app)
    payload = {"subject": "Gate still red", "markdown": "**3 errors**",
               "buttons": [{"id": "accept", "label": "Accept as is", "decision": "approve"},
                           {"id": "park", "label": "Park", "decision": "deny"}], "note": {"label": "Notes"}}
    task = asyncio.create_task(app.approvals.ask(s["id"], "gate_escalation", payload))
    await asyncio.sleep(0)
    aid = app.approvals.pending(s["id"])[0]["id"]
    with pytest.raises(ValueError):
        app.approvals.resolve(aid, "approve", choice="nope")
    app.approvals.resolve(aid, "deny", choice="park", note="later")
    assert await task == {"status": "denied", "choice": "park", "note": "later"}
    row = app.db.one("SELECT payload FROM approvals WHERE id=?", [aid])
    assert json.loads(row["payload"])["answer"] == {"choice": "park", "note": "later"}
