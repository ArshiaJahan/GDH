"""WP2 Unity gates: unity.compile / unity.tests / unity.antipatterns through the UnityBridge
(a FakeUnityBridge, a fake MCP manager for the editor path, and a fake unity.sh on PATH for
batchmode), the one-time offer, consent, debounce, fail-open skips and run_gate."""
import asyncio
import json
import os
import stat
import time

import pytest

from gamedevworkstation.agent.tools import ToolContext, ToolOutput, wrap_untrusted
from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Message
from gamedevworkstation.features import hooks as H
from gamedevworkstation.features.unity_bridge import (BridgeResult, EditorState, FakeUnityBridge, UnityBridge,
                                             parse_compile_output)
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response

from .conftest import untrusted

CS_ERR = "Assets/Game/Hit.cs(3,5): error CS1002: ; expected"


@pytest.fixture(autouse=True)
def _no_audit_script(tmp_path, monkeypatch):
    """unity.antipatterns calls the Unity pack's script when it exists; these tests use their own."""
    monkeypatch.setattr(H, "antipatterns_script", lambda: tmp_path / "no-such-audit.py")


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "u.db")
    a.fake = FakeProvider()
    a.providers.override("anthropic", "default", a.fake)
    H.install(a)
    return a


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "Game"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")
    (d / "Assets/Game").mkdir(parents=True)
    (d / "Assets/Game/Hit.cs").write_text("class Hit {}\n")
    old = time.time() - 3600
    for p in d.rglob("*"):
        os.utime(p, (old, old))
    return d


def session(app, folder, mode="accept_edits", **settings):
    return app.store.create(folder=str(folder), mode=mode, **settings)


async def turn(app, sid, text="hi"):
    app.store.add_message(sid, Message.user(text))
    await app.runner.start(sid)


def enable(app, proj):
    return H.get_engine(app).enable_preset(proj.resolve())


def fake(app, **kw) -> FakeUnityBridge:
    b = app.extensions["unity_bridge"] = FakeUnityBridge(app, **kw)
    return b


def gate_rows(app, gate="unity.compile"):
    return [(r["status"], r["attempt"], r["level"]) for r in
            app.db.all("SELECT * FROM gate_runs WHERE gate=? ORDER BY started_at, rowid", [gate])]


def edit_cs():
    return tool_response("write_file", {"path": "Assets/Game/Hit.cs", "content": "class Hit { int x }\n"})


# ------------------------------------------------------------ compile gate


async def test_compile_failure_is_injected_untrusted_then_passes(app, proj):
    enable(app, proj)
    b = fake(app, compile=[BridgeResult("fail", "1 compile error (1 root cause)", "mcp", report=CS_ERR, errors=1),
                           BridgeResult("pass", "0 compile errors", "mcp")])
    s = session(app, proj, mode="ask")
    app.fake.script = [edit_cs(), text_response("done"), text_response("fixed")]
    app.config.modes = {**app.config.modes, "allowlist": ["edit:*"]}
    await turn(app, s["id"])
    m = app.store.messages(s["id"])
    gates = [x for x in m if x.meta.get("gate")]
    assert len(gates) == 1 and gates[0].role == "user"
    assert gates[0].meta["gate"] == {"id": "unity.compile", "status": "fail", "attempt": 1, "max": 2,
                                     "hook": "cs-compile", "level": "L1"}
    head, wrapped = gates[0].content[0].text.split("\n\n", 1)
    assert head.startswith("[GameDevWorkstation gate unity.compile] 1 compile error (1 root cause) after this turn's changes (mcp).")
    assert untrusted(wrapped) == ("gate:unity.compile", CS_ERR)
    assert m[-1].role == "assistant" and m[-1].content[0].text == "fixed" and not m[-1].meta.get("notice")
    assert gate_rows(app) == [("fail", 1, "L1"), ("pass", 1, "L1")]
    # The gate ran under the preset's consent: exactly its MCP tools and command lines.
    op, sid, consent = b.calls[0]
    assert op == "compile" and sid == s["id"]
    assert {"unity__refresh_unity", "unity__read_console"} <= consent["mcp"]
    assert any(" compile --project " in c for c in consent["run_command"])


async def test_no_code_change_runs_no_compile(app, proj):
    enable(app, proj)
    b = fake(app)
    s = session(app, proj)
    app.fake.script = [tool_response("write_file", {"path": "README.md", "content": "hi\n"}), text_response("ok")]
    await turn(app, s["id"])
    assert b.calls == [] and gate_rows(app) == []


async def test_gates_are_off_until_enabled(app, proj):
    b = fake(app)
    s = session(app, proj)
    app.fake.script = [edit_cs(), text_response("ok")]
    await turn(app, s["id"])
    assert b.calls == [] and gate_rows(app) == []
    assert "run_gate" not in {t.name for t in app.runner.tool_specs(app.store.get(s["id"]))}
    enable(app, proj)
    assert "run_gate" in {t.name for t in app.runner.tool_specs(app.store.get(s["id"]))}


async def test_exhausted_gate_hands_over(app, proj):
    enable(app, proj)
    fake(app, compile=[BridgeResult("fail", "2 compile errors", "batchmode", report=CS_ERR, errors=2)])
    s = session(app, proj)
    app.fake.script = [edit_cs(), text_response("done"), text_response("tried"), text_response("tried again")]
    await turn(app, s["id"])
    m = app.store.messages(s["id"])
    assert [x.meta["gate"]["attempt"] for x in m if x.meta.get("gate")] == [1, 2]
    assert m[-1].meta.get("notice") == "gate_exhausted"


async def test_editor_open_but_mcp_unreachable_skips_with_notice(app, proj):
    enable(app, proj)

    async def is_open(p):
        return True

    app.extensions["unity_bridge"] = UnityBridge(app, editor_open=is_open)  # app.mcp is None
    s = session(app, proj)
    app.fake.script = [edit_cs(), text_response("done")]
    await turn(app, s["id"])
    m = app.store.messages(s["id"])
    assert not any(x.meta.get("gate") for x in m) and len(app.fake.calls) == 2  # fail open: no retry
    notice = next(x for x in m if x.meta.get("notice") == "gate_skipped")
    assert "Gate unity.compile skipped" in notice.content[0].text and "MCP bridge isn't reachable" in notice.content[0].text
    assert gate_rows(app) == [("skipped", 0, "L1")]


async def test_skip_notice_can_be_turned_off(app, proj):
    enable(app, proj)
    fake(app, compile=[BridgeResult("skipped", "Unity is busy", "mcp")])
    app.config.hooks = {**app.config.hooks, "fail_open_notice": False}
    s = session(app, proj)
    app.fake.script = [edit_cs(), text_response("done")]
    await turn(app, s["id"])
    assert not any(x.meta.get("notice") for x in app.store.messages(s["id"]))
    assert gate_rows(app) == [("skipped", 0, "L1")]


# ------------------------------------------------------------ MCP path


class FakeConn:
    def __init__(self):
        self.session = object()
        self.tools = [type("T", (), {"name": n})() for n in ("refresh_unity", "read_console", "run_tests",
                                                              "get_test_job")]


class FakeMCP:
    """Just enough of MCPManager for the bridge: the `unity` server on, connected, and scripted."""

    def __init__(self, console_pages, enabled=True):
        self.pages = list(console_pages)
        self.enabled = enabled
        self.conns = {"unity": FakeConn()}
        self.calls = []

    def enabled_for(self, session):
        return [{"name": "unity"}] if self.enabled else []

    async def connect(self, name):
        return self.conns[name]

    def owns(self, name):
        return name.startswith("mcp__unity__")

    async def call(self, ctx, name, args):
        tool = name.split("__")[-1]
        self.calls.append((tool, args, ctx.role, ctx.consented("mcp", f"unity__{tool}")))
        if tool == "read_console" and args.get("action") == "get":
            text = json.dumps(self.pages.pop(0))
        elif tool == "run_tests":
            text = json.dumps({"success": True, "data": {"job_id": "j1"}})
        elif tool == "get_test_job":
            text = json.dumps({"data": {"status": "complete", "result": {
                "summary": {"total": 3, "passed": 2, "failed": 1},
                "failures": [{"fullName": "Combat.HitTests.Flash", "message": "Expected 0 but was 1"}]}}})
        else:
            text = json.dumps({"success": True})
        return ToolOutput(wrap_untrusted(text, f"mcp:unity.{tool}"))  # as finalize_output does


async def editor_is_open(p):
    return True


async def test_mcp_compile_reads_console_pages_under_consent(app, proj):
    page1 = {"success": True, "data": {"items": [{"type": "Error", "message": CS_ERR}], "nextCursor": "1"}}
    page2 = {"success": True, "data": {"items": [
        {"type": "Error", "message": "Assets/Game/Enemy.cs(9,1): error CS0246: The type or namespace name 'Foo' could not be found"}],
        "nextCursor": None}}
    app.mcp = FakeMCP([page1, page2])
    br = UnityBridge(app, editor_open=editor_is_open)
    s = session(app, proj, mode="ask")
    consent = br.consent_for(proj, [{"op": "compile"}])
    r = await br.compile(s, consent=consent)
    assert r.status == "fail" and r.mode == "mcp" and r.errors == 2 and "CS1002" in r.report and "CS0246" in r.report
    tools = [c[0] for c in app.mcp.calls]
    assert tools == ["read_console", "refresh_unity", "read_console", "read_console"]
    assert app.mcp.calls[1][1] == {"mode": "force", "scope": "all", "compile": "request", "wait_for_ready": True}
    assert all(c[2] == "hook" and c[3] for c in app.mcp.calls)  # hook role, consented tools
    assert app.mcp.calls[3][1]["cursor"] == "1"
    app.mcp.pages = [{"success": True, "data": {"items": [], "nextCursor": None}}]
    assert (await br.compile(s, consent=consent)).status == "pass"


async def test_mcp_tests_report_failures(app, proj):
    app.mcp = FakeMCP([])
    br = UnityBridge(app, editor_open=editor_is_open)
    r = await br.run_tests(session(app, proj), "editmode")
    assert r.status == "fail" and r.errors == 1 and r.evidence["total"] == 3
    assert "Combat.HitTests.Flash" in r.report and r.evidence["failed_names"] == ["Combat.HitTests.Flash"]


async def test_editor_state_modes(app, proj, tmp_path):
    async def closed(p):
        return False

    app.mcp = FakeMCP([], enabled=False)
    s = session(app, proj)
    st = await UnityBridge(app, editor_open=editor_is_open).editor_state(s)
    assert st.mode == "unavailable" and st.editor_open and "connector is off" in st.reason
    st = await UnityBridge(app, editor_open=closed).editor_state(s)
    assert st.mode == "batchmode"  # the built-in headless-ops script
    plain = session(app, tmp_path)
    assert (await UnityBridge(app).editor_state(plain)).reason.startswith("not a Unity project")


# --------------------------------------------------------- batchmode path


@pytest.fixture
def fake_unity_sh(tmp_path, monkeypatch):
    """A fake unity.sh on PATH: fails with one compile error until ok-flag exists."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log, flag = tmp_path / "unity_calls.log", tmp_path / "ok-flag"
    sh = bindir / "unity.sh"
    sh.write_text(f"""#!/bin/bash
echo "$@" >> '{log}'
if [ "$1" = "test" ]; then
  echo "tests: total=4 passed=4 failed=0 skipped=0 inconclusive=0 duration=1.2 result=Passed"
  echo "RESULT: OK tests EditMode total=4 passed=4 failed=0"; exit 0
fi
if [ -f '{flag}' ]; then echo "RESULT: OK compile 0 errors, 0 warning lines"; exit 0; fi
echo "{CS_ERR}"
echo "RESULT: FAIL compile-errors 1 (compile, log x.log)"
exit 1
""")
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return {"sh": sh, "log": log, "flag": flag}


async def closed_editor(p):
    return False


async def test_batchmode_compile_with_fake_unity_sh(app, proj, fake_unity_sh):
    enable(app, proj)  # consents to `bash <PATH unity.sh> compile --project <proj>`
    app.extensions["unity_bridge"] = UnityBridge(app, editor_open=closed_editor)
    s = session(app, proj, mode="ask")
    app.config.modes = {**app.config.modes, "allowlist": ["edit:*"]}
    app.fake.script = [edit_cs(), text_response("done"), text_response("fixed")]

    async def fix_after_first_gate():
        while not any(x.meta.get("gate") for x in app.store.messages(s["id"])):
            await asyncio.sleep(0.01)
        fake_unity_sh["flag"].write_text("1")

    helper = asyncio.create_task(fix_after_first_gate())
    await turn(app, s["id"])
    await helper
    assert app.approvals.pending() == []  # consented command: no card
    m = app.store.messages(s["id"])
    g = next(x for x in m if x.meta.get("gate"))
    src, body = untrusted(g.content[0].text.split("\n\n", 1)[1])
    assert src == "gate:unity.compile" and "Assets/Game/Hit.cs(3,5): error CS1002" in body and "ROOT CAUSES" in body
    assert gate_rows(app) == [("fail", 1, "L1"), ("pass", 1, "L1")]
    calls = fake_unity_sh["log"].read_text().splitlines()
    assert calls == [f"compile --project {proj.resolve()}"] * 2


async def test_batchmode_commands_without_consent_ask(app, proj, fake_unity_sh):
    app.extensions["unity_bridge"] = UnityBridge(app, editor_open=closed_editor)
    s = session(app, proj, mode="ask")
    eng = H.get_engine(app)
    task = asyncio.create_task(eng.run_gate(s, "unity.compile"))  # preset off: no consent
    for _ in range(500):
        if app.approvals.pending(s["id"]):
            break
        await asyncio.sleep(0.01)
    (card,) = app.approvals.pending(s["id"])
    assert card["kind"] == "command" and "unity.sh compile --project" in card["payload"]["command"]
    app.approvals.resolve(card["id"], "deny")
    r = await task
    assert r.status == "skipped" and "didn't run" in r.reason
    assert not fake_unity_sh["log"].exists()
    # Plan only mode never runs the command.
    plan = session(app, proj, mode="plan")
    r = await eng.run_gate(plan, "unity.compile")
    assert r.status == "skipped" and r.action == "allow"
    assert not fake_unity_sh["log"].exists()


async def test_batchmode_tests(app, proj, fake_unity_sh):
    br = UnityBridge(app, editor_open=closed_editor)
    s = session(app, proj)
    consent = br.consent_for(proj)
    r = await br.run_tests(s, "editmode", consent=consent)
    assert r.status == "pass" and r.mode == "batchmode" and r.evidence["passed"] == 4
    assert fake_unity_sh["log"].read_text().strip() == f"test editmode --project {proj.resolve()}"


# ----------------------------------------------------------- tests & audit


def campaign(app, phase_type):
    cid = "cmp_t"
    app.db.insert("campaigns", {"id": cid, "slug": "t", "title": "T", "kind": "chain", "template": "new-mechanic",
                                "folder": "/x", "status": "active", "phase": 0,
                                "phases": [{"name": "Verify", "type": phase_type}], "created_at": time.time(),
                                "updated_at": time.time()}, replace=True)
    return cid


async def test_unity_tests_only_in_verify_phases(app, proj):
    enable(app, proj)
    b = fake(app, tests=[BridgeResult("fail", "1 failing test of 3", "mcp", report="FAILED A.B :: boom", errors=1),
                         BridgeResult("pass", "3 tests passed", "mcp")])
    s = session(app, proj, campaign_id=campaign(app, "build"))
    app.fake.script = [edit_cs(), text_response("done")]
    await turn(app, s["id"])
    assert [c[0] for c in b.calls] == ["compile"]
    campaign(app, "verify")
    app.fake.script = [edit_cs(), text_response("done"), text_response("fixed")]
    await turn(app, s["id"], "verify it")
    assert [c[0] for c in b.calls] == ["compile", "compile", "tests", "compile", "tests"]
    g = [x for x in app.store.messages(s["id"]) if x.meta.get("gate")]
    assert g[-1].meta["gate"]["id"] == "unity.tests" and g[-1].meta["gate"]["level"] == "L2"
    assert gate_rows(app, "unity.tests") == [("fail", 1, "L2"), ("pass", 1, "L2")]


async def test_tests_wait_for_a_clean_compile(app, proj):
    enable(app, proj)
    b = fake(app, compile=[BridgeResult("fail", "1 compile error", "mcp", report=CS_ERR, errors=1),
                           BridgeResult("pass", "0 compile errors", "mcp")])
    s = session(app, proj, campaign_id=campaign(app, "verify"))
    app.fake.script = [edit_cs(), text_response("done"), text_response("fixed")]
    await turn(app, s["id"])
    assert [c[0] for c in b.calls] == ["compile", "compile", "tests"]


async def test_antipatterns_advisory_and_missing_script(app, proj, tmp_path, monkeypatch):
    enable(app, proj)
    fake(app)
    s = session(app, proj)
    app.fake.script = [edit_cs(), text_response("done")]
    await turn(app, s["id"])
    assert gate_rows(app, "unity.antipatterns") == []  # no script (autouse fixture): nothing, no notice
    assert (await H.get_engine(app).run_gate(s, "unity.antipatterns")).status == "skipped"  # asked by name
    script = tmp_path / "audit.py"
    script.write_text("import sys\nprint('Assets/Game/Hit.cs:1 HOT_FIND in Update')\nprint(' '.join(sys.argv[1:]))\n"
                      "print('RESULT: FAIL 1 new')\n")
    monkeypatch.setattr(H, "antipatterns_script", lambda: script)
    app.fake.script = [edit_cs(), text_response("done")]
    await turn(app, s["id"], "again")
    rows = app.db.all("SELECT status, summary, detail FROM gate_runs WHERE gate='unity.antipatterns' ORDER BY started_at")
    assert rows[-1]["status"] == "fail" and rows[-1]["summary"].startswith("RESULT: FAIL 1 new")
    assert not any(x.meta.get("gate", {}).get("id") == "unity.antipatterns" for x in app.store.messages(s["id"]))
    # The audit got the changed scripts and the baseline.
    note = json.loads(rows[-1]["detail"])["note"]
    assert "--changed Assets/Game/Hit.cs --baseline" in note and "HOT_FIND" in note


# --------------------------------------------------------- run_gate & offer


async def test_run_gate_tool(app, proj):
    enable(app, proj)
    fake(app, compile=[BridgeResult("fail", "1 compile error", "mcp", report=CS_ERR, errors=1)])
    s = session(app, proj)
    ctx = ToolContext(app=app, session=app.store.get(s["id"]), run_id="main:x")
    out = await app.tools.run(ctx, "run_gate", {"name": "unity.compile"})  # no change needed
    assert out.is_error and out.text.startswith("Gate unity.compile: fail. 1 compile error")
    assert untrusted(out.text.split("\n\n", 1)[1]) == ("gate:unity.compile", CS_ERR)
    assert gate_rows(app) == [("fail", 0, "L1")]
    out = await app.tools.run(ctx, "run_gate", {"name": "nope"})
    assert out.is_error and "Gates: unity.compile" in out.text


async def test_one_time_offer_card(app, proj):
    fake(app)
    s = session(app, proj, skills=["delegation", "compile-fix-loop"])
    await turn(app, s["id"])
    (card,) = app.approvals.pending(s["id"])
    assert card["kind"] == "hook_preset" and card["payload"]["subject"] == "Turn on Unity gates for Game?"
    md = card["payload"]["markdown"]
    assert "unity.compile" in md and "unity.refresh_unity" in md and "unity.sh" in md
    app.approvals.resolve(card["id"], "deny", choice="not_now")
    await asyncio.sleep(0)
    s2 = session(app, proj, skills=["play-verify"])
    await turn(app, s2["id"])
    assert app.approvals.pending() == []  # once per project, whatever the answer
    assert H.get_engine(app).gate_names(s2) == []
    # A non-Unity skill in a Unity folder never offers.
    other = proj.parent / "Other"
    (other / "ProjectSettings").mkdir(parents=True)
    (other / "ProjectSettings/ProjectVersion.txt").write_text("x")
    s3 = session(app, other, skills=["grill-me"])
    await turn(app, s3["id"])
    assert app.approvals.pending() == []


async def test_offer_accepted_enables_gates(app, proj):
    fake(app)
    s = session(app, proj, skills=["unity-router"])
    await turn(app, s["id"])
    (card,) = app.approvals.pending(s["id"])
    app.approvals.resolve(card["id"], "approve", choice="enable")
    for _ in range(20):
        await asyncio.sleep(0)
    assert "unity.compile" in H.get_engine(app).gate_names(app.store.get(s["id"]))
    row = app.db.one("SELECT detail FROM hook_trust WHERE kind='preset'")
    assert "unity__run_tests" in json.loads(row["detail"])["tools"]


async def test_post_merge_compile_note(app, proj):
    enable(app, proj)
    fake(app, compile=[BridgeResult("fail", "1 compile error", "mcp", report=CS_ERR, errors=1)])
    s = session(app, proj)
    from gamedevworkstation.features.hookbus import HookEvent, TurnState

    (proj / "Assets/Game/New.cs").write_text("class N {}\n")
    ctx = ToolContext(app=app, session=s, run_id="main:x")
    ev = HookEvent("post_merge", ctx, turn=TurnState(s["id"], time.time() - 5, folder=proj.resolve()), unit="sub_1",
                   extra={"branch": "gdw/sub_1", "worktree": "/w", "name": "w", "stat": "", "changes": True})
    res = await app.hooks.fire(ev)
    (r,) = [x for x in res if x.gate == "unity.compile"]
    assert r.action == "note" and r.note.startswith("[unity.compile] 1 compile error")
    assert untrusted(r.note.split("\n", 1)[1])[1] == CS_ERR
    assert gate_rows(app) == [("fail", 0, "L1")]


def test_parse_compile_output_uses_parse_unity_log():
    log = "\n".join([CS_ERR, CS_ERR, "Assets/Game/Enemy.cs(9,1): error CS0246: The type or namespace name 'Foo' "
                     "could not be found", "Assets/x.cs(1,1): warning CS0618: obsolete"])
    p = parse_compile_output(log)
    assert p["errors"] == 2 and p["warnings"] == 1 and p["report"].startswith("ROOT CAUSES")
    assert parse_compile_output("all good")["errors"] == 0


def test_fake_bridge_state_default(app):
    assert FakeUnityBridge(app).state == EditorState("mcp", True, True, True)
