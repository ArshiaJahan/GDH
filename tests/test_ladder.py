"""WP3 quality ladder: observers and parsers, freshness, the story-done and visual gates, manual
checks, critique aggregation and rounds, view_image, REST."""
import asyncio
import json
import os
import shutil
import struct
import time
import zlib
from pathlib import Path

import pytest

from gamedevworkstation.agent.tools import ToolContext, ToolOutput, obj, wrap_untrusted
from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Message, ToolResultBlock
from gamedevworkstation.features import ladder as L
from gamedevworkstation.features.hookbus import HookEvent, TurnState
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response
from gamedevworkstation.skills import builtin_skills_dir

SKILLS = builtin_skills_dir()
PARSE_LOG = SKILLS / "compile-fix-loop/scripts/parse_unity_log.py"
CHECK = SKILLS / "play-verify/scripts/check_criteria.py"

BACKLOG = """# Backlog: Test
Current milestone: M1

## M1 Core loop
Goal: Hit an enemy.
Exit: All M1 criteria pass.
Status: active

### M1-S01 Movement
- Status: doing
- Owner skill: architecture-patterns

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M1-S01-AC1 | Given speed 6, When right is held 1 s, Then the player moves 6 units | EditMode | test:MoveTests.M1_S01_Moves |

### M1-S02 Melee attack
- Status: doing
- Owner skill: architecture-patterns
- Critique: no

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M1-S02-AC1 | Given 3 HP, When hit 3 times, Then it dies once | EditMode | test:HealthTests.M1_S02_DiesAtZero |
| M1-S02-AC2 | Given the play scene, When the player attacks, Then a hit is logged and the enemy flashes | play-verify | log:"[Combat] hit target=Enemy"; screenshot:M1-S02-hit shows the white flash |

### M1-S03 Playtest
- Status: doing
- Owner skill: human

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M1-S03-AC1 | Given the build, When a tester plays one run, Then they finish it in 6 of 6 tries | manual | observe:testers finish unaided |
"""

NUNIT = """<?xml version="1.0" encoding="utf-8"?>
<test-run id="2" testcasecount="{total}" result="{result}" total="{total}" passed="{passed}" failed="{failed}" skipped="0">
  <test-suite type="Assembly" name="Game.Tests">
    {cases}
  </test-suite>
</test-run>
"""


def nunit(path: Path, cases: dict[str, str]) -> Path:
    body = "\n".join(f'<test-case name="{n.rsplit(".", 1)[-1]}" fullname="{n}" result="{r}" />' for n, r in cases.items())
    p = sum(1 for r in cases.values() if r == "Passed")
    f = sum(1 for r in cases.values() if r == "Failed")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NUNIT.format(total=len(cases), passed=p, failed=f, result="Failed" if f else "Passed", cases=body))
    return path


def png(path: Path, w: int = 4, h: int = 4) -> Path:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def age(path: Path, secs: float) -> None:
    t = time.time() - secs
    os.utime(path, (t, t))


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "l.db")
    a.fake = FakeProvider()
    a.providers.override("anthropic", "default", a.fake)
    a.lad = L.install(a)
    return a


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "game"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.0f1\n")
    for rel in ("Assets/Game/Hit.cs", "Assets/Game/Move.cs", "Assets/Scenes/Arena.unity"):
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// code\n")
        age(p, 600)
    (d / "BACKLOG.md").write_text(BACKLOG)
    return d


def session(app, folder, mode="accept_edits"):
    return app.store.create(folder=str(folder), mode=mode)


def ctx_for(app, s, role="main"):
    return ToolContext(app=app, session=s, run_id=f"main:{s['id']}", role=role)


async def observe(app, s, tool, args, text, *, is_error=False, role="main"):
    out = ToolOutput(text, is_error=is_error)
    return await app.lad.observe(HookEvent("post_tool", ctx_for(app, s, role), tool=tool, args=args, output=out))


async def turn(app, sid, text="go"):
    app.store.add_message(sid, Message.user(text))
    await app.runner.start(sid)


def state(app, proj, sid_):
    bl = L.read_backlog(proj)
    return app.lad.story_state(proj, bl.stories[sid_], scan=L.project_scan(proj))


# ------------------------------------------------------------------ evidence makers


async def compile_ok(app, s, proj, errors=False):
    log = proj / "Logs" / "compile.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    entries = [{"type": "error", "message": "Assets/Game/Hit.cs(3,1): error CS1002: ; expected"}] if errors else \
        [{"type": "log", "message": "Compilation finished"}]
    log.write_text(json.dumps(entries))
    return await observe(app, s, "run_command", {"command": f"python3 {PARSE_LOG} Logs/compile.json"},
                         "exit code 0\ncompile errors: 0 | runtime errors: 0\nRESULT: OK")


async def run_tests_ok(app, s, proj, cases):
    xml = nunit(proj / "Logs/harness/editmode.xml", cases)
    return await observe(app, s, "run_command", {"command": "~/skills/headless-ops/scripts/unity.sh test editmode 2>&1"},
                         f"exit code 0\ntests: ...\nRESULT: OK tests editmode tests: total={len(cases)} (xml {xml})")


async def play_ok(app, s, proj, lines=("[Combat] hit target=Enemy", "[VERIFY] player.hp=3 log.errors=0"),
                  extra_args=""):
    run = proj / "Logs/harness/verify/20261112-1400-m1"
    run.mkdir(parents=True, exist_ok=True)
    (run / "console.json").write_text(json.dumps([{"type": "error" if "Exception" in m else "log", "message": m}
                                                  for m in lines]))
    (run / "VERIFY.md").write_text("# report\n")
    cmd = (f"cd {proj} && python3 {CHECK} BACKLOG.md Logs/harness/verify/20261112-1400-m1/console.json "
           f"--only M1-S02 --type play-verify {extra_args}")
    return await observe(app, s, "run_command", {"command": cmd}, "exit code 0\n| ID |...\nRESULT: OK 2/2 PASS")


# ------------------------------------------------------------------------ parsers


def test_backlog_parse_flags_and_signals(proj):
    bl = L.read_backlog(proj)
    s2 = bl.stories["M1-S02"]
    assert s2.critique is False and s2.visual is None and s2.status == "doing" and s2.milestone == "M1"
    assert [a.test for a in s2.acs] == ["EditMode", "play-verify"]
    assert s2.acs[1].signals == [("log", "[Combat] hit target=Enemy"), ("screenshot", "M1-S02-hit shows the white flash")]
    text = BACKLOG.replace("- Critique: no", "- Visual: yes\n- Critique: yes")
    s2 = L.parse_backlog(text).stories["M1-S02"]
    assert s2.visual is True and s2.critique is True
    assert L.done_flips(BACKLOG, BACKLOG.replace("### M1-S01 Movement\n- Status: doing", "### M1-S01 Movement\n- Status: done")) == ["M1-S01"]
    assert L.done_flips(None, BACKLOG.replace("doing", "done")) == []  # a brand-new file flips nothing


def test_parse_unity_log_and_nunit_parsers(tmp_path):
    bad = tmp_path / "Editor.log"
    bad.write_text("Assets/Game/Hit.cs(3,1): error CS1002: ; expected\nNullReferenceException: x\n")
    assert L.compile_errors_in(bad) == (1, 1)
    ok = tmp_path / "console.json"
    ok.write_text(json.dumps({"success": True, "data": [{"type": "warning", "message": "Assets/A.cs(1,1): warning CS0168: x"}]}))
    assert L.compile_errors_in(ok) == (0, 0)
    r = L.parse_nunit(nunit(tmp_path / "r.xml", {"G.MoveTests.M1_S01_Moves": "Passed", "G.HealthTests.M1_S02_DiesAtZero": "Failed"}))
    assert (r["total"], r["passed_n"], r["failed_n"]) == (2, 1, 1) and r["failed"] == ["G.HealthTests.M1_S02_DiesAtZero"]
    assert L.story_ids_from_tests(r["passed"] + r["failed"]) == ["M1-S01", "M1-S02"]


def test_check_criteria_rerun_ignores_agent_evidence_and_keeps_console(proj):
    run = proj / "Logs/harness/verify/r1"
    run.mkdir(parents=True)
    (run / "console.json").write_text(json.dumps([{"type": "log", "message": "[Combat] hit target=Enemy"},
                                                  {"type": "error", "message": "NullReferenceException: boom"}]))
    argv = ["BACKLOG.md", "Logs/harness/verify/r1/console.json", "--only", "M1-S02", "--no-error-gate",
            "--evidence", "M1-S02-AC2=PASS:looked fine"]
    r = L.rerun_check_criteria(argv, proj)
    assert r["results"] == {"M1-S02-AC1": "MANUAL", "M1-S02-AC2": "PASS"}  # test: needs --results
    assert r["console"][0] == "FAIL"  # computed even with --no-error-gate
    assert L.rerun_check_criteria(["BACKLOG.md", "-"], proj) is None  # stdin can't be re-checked
    assert L.rerun_check_criteria(["BACKLOG.md", "missing.json"], proj) is None


def test_mcp_test_json_and_command_split(tmp_path):
    done = {"success": True, "data": {"status": "succeeded", "result": {
        "summary": {"total": 3, "passed": 2, "failed": 1, "skipped": 0},
        "results": [{"fullName": "G.HealthTests.M1_S02_DiesAtZero", "state": "Passed"},
                    {"fullName": "G.MoveTests.M1_S01_Moves", "state": "Failed"}]}}}
    r = L.parse_test_json(done)
    assert (r["total"], r["passed_n"], r["failed_n"]) == (3, 2, 1) and r["failed"] == ["G.MoveTests.M1_S01_Moves"]
    assert L.parse_test_json({"data": {"status": "running", "job_id": "j1"}}) is None  # never partial results
    cmds = L.split_commands("cd sub && python3 x/check_criteria.py B.md log.json --only M1 2>&1 | tail -5; echo hi",
                            tmp_path)
    assert cmds[1] == (["python3", "x/check_criteria.py", "B.md", "log.json", "--only", "M1"], (tmp_path / "sub").resolve())
    assert [c[0][0] for c in cmds] == ["cd", "python3", "tail", "echo"]
    assert L.find_script(cmds[1][0]) == ("check_criteria.py", ["B.md", "log.json", "--only", "M1"])


# ---------------------------------------------------------------- observers


async def test_observers_record_levels(app, proj):
    s = session(app, proj)
    res = await compile_ok(app, s, proj)
    assert res.note.startswith("[Quality ladder] L1 PASS")
    await run_tests_ok(app, s, proj, {"G.MoveTests.M1_S01_Moves": "Passed", "G.HealthTests.M1_S02_DiesAtZero": "Passed"})
    await play_ok(app, s, proj)
    rows = app.lad.evidence(proj)
    by = {(r["level"], r["source"]) for r in rows}
    assert {("L1", "cmd:parse_unity_log.py"), ("L2", "cmd:unity.sh"), ("L3", "cmd:check_criteria.py"),
            ("metric", "cmd:check_criteria.py")} <= by
    assert ("L2", "cmd:check_criteria.py") not in by  # --type play-verify left the EditMode AC out
    l3 = next(r for r in rows if r["level"] == "L3")
    assert l3["subjects"] == ["M1-S02-AC2"] and l3["detail"]["results"] == {"M1-S02-AC2": "PASS"}
    assert l3["path"].endswith("VERIFY.md") and l3["observed"] == "command"
    assert app.lad.metric(proj, "player.hp")[0] == "3"
    ev = [e for e in app.bus.replay(0, s["id"]) if e["type"] == "ladder.updated"]
    assert len(ev) == len(rows)
    # A failing compile is recorded as a failure; a stdin pipe can't be re-checked, so it's nothing.
    await compile_ok(app, s, proj, errors=True)
    assert app.lad.evidence(proj, levels=["L1"])[0]["status"] == "fail"
    n = len(app.lad.evidence(proj))
    await observe(app, s, "run_command", {"command": f"cat Editor.log | python3 {PARSE_LOG} -"}, "exit code 0\nRESULT: OK")
    await observe(app, s, "run_command", {"command": "echo 'RESULT: OK compile 0 errors'"}, "exit code 0\nRESULT: OK")
    assert len(app.lad.evidence(proj)) == n


async def test_mcp_observers_tests_and_screenshot_item(app, proj):
    s = session(app, proj)
    await observe(app, s, "mcp__unity__run_tests", {"mode": "EditMode", "category_names": ["M1"]},
                  wrap_untrusted(json.dumps({"success": True, "data": {"job_id": "job7", "status": "running"}}), "mcp:unity.run_tests"))
    assert app.lad.evidence(proj) == []  # still running: no evidence
    body = {"success": True, "data": {"job_id": "job7", "status": "succeeded", "result": {
        "summary": {"total": 5, "passed": 5, "failed": 0}, "results": []}}}
    await observe(app, s, "mcp__unity__get_test_job", {"job_id": "job7"}, wrap_untrusted(json.dumps(body), "mcp:unity.get_test_job"))
    row = app.lad.evidence(proj, levels=["L2"])[0]
    assert row["status"] == "pass" and row["detail"]["categories"] == ["M1"] and row["detail"]["scope"] == "filtered"
    # failed=0 in a run whose categories include the milestone covers the story's tests.
    assert state(app, proj, "M1-S01")["levels"]["L2"]["state"] == "pass"

    shot = png(proj / "Logs/harness/verify/r2/shots/M1-S02-AC2-hit.png")
    res = await observe(app, s, "mcp__unity__manage_camera",
                        {"action": "screenshot", "screenshot_file_name": "M1-S02-AC2-hit",
                         "output_folder": "Logs/harness/verify/r2/shots"},
                        wrap_untrusted('{"success": true, "message": "saved"}', "mcp:unity.manage_camera"))
    assert "indexed" in res.note
    it = app.db.one("SELECT * FROM items WHERE subtype='screenshot'")
    assert it["path"] == str(shot.resolve()) and json.loads(it["meta"]) == {"ac": "M1-S02-AC2", "story": "M1-S02", "run_id": "r2"}
    ev = app.lad.evidence(proj, levels=["L3"])[0]
    assert ev["item_id"] == it["id"] and ev["detail"]["kind"] == "screenshot" and ev["subjects"] == ["M1-S02-AC2"]
    # Indexed once per session.
    await observe(app, s, "mcp__unity__manage_camera", {"action": "screenshot", "screenshot_file_name": "M1-S02-AC2-hit",
                                                        "output_folder": "Logs/harness/verify/r2/shots"}, "ok")
    assert app.db.one("SELECT COUNT(*) n FROM items WHERE subtype='screenshot'")["n"] == 1


# ---------------------------------------------------------------- freshness


async def test_freshness_invalidated_by_later_cs_change(app, proj):
    s = session(app, proj)
    await compile_ok(app, s, proj)
    await run_tests_ok(app, s, proj, {"G.MoveTests.M1_S01_Moves": "Passed"})
    st = state(app, proj, "M1-S01")
    assert st["ok"] and st["levels"]["L1"]["state"] == "pass" and st["levels"]["L2"]["state"] == "pass"
    future = time.time() + 5
    os.utime(proj / "Assets/Game/Hit.cs", (future, future))
    st = state(app, proj, "M1-S01")
    assert not st["ok"] and st["levels"]["L1"]["state"] == "stale" and st["levels"]["L2"]["state"] == "stale"
    assert any("Assets/Game/Hit.cs" in m for m in st["missing"])
    # A .meta or a screenshot is never a change.
    for rel in ("Assets/Game/Hit.cs", ):
        os.utime(proj / rel, (time.time() - 600,) * 2)
    for rel in ("Assets/Game/Hit.cs.meta", "Assets/Screenshots/x.png"):
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text("x")
    assert state(app, proj, "M1-S01")["ok"]


async def test_old_artifact_is_not_fresh_evidence(app, proj):
    """Re-checking a log written before the change doesn't make fresh evidence: a row's time is the artifact's."""
    s = session(app, proj)
    log = proj / "Logs" / "compile.json"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps([{"type": "log", "message": "Compilation finished"}]))
    age(log, 3600)  # written before Hit.cs / Move.cs changed (600 s ago)
    await observe(app, s, "run_command", {"command": f"python3 {PARSE_LOG} Logs/compile.json"}, "exit code 0\nRESULT: OK")
    row = app.lad.evidence(proj, levels=["L1"])[0]
    assert row["status"] == "pass" and abs(row["ts"] - log.stat().st_mtime) < 1
    st = state(app, proj, "M1-S01")
    assert st["levels"]["L1"]["state"] == "stale" and "compile again" in st["levels"]["L1"]["missing"][0]


# ---------------------------------------------------------------- story-done gate


FLIP_S01 = {"path": "BACKLOG.md", "old": "### M1-S01 Movement\n- Status: doing", "new": "### M1-S01 Movement\n- Status: done"}


async def test_flip_to_done_denied_without_evidence_then_allowed(app, proj):
    s = session(app, proj)
    app.fake.script = [tool_response("edit_file", FLIP_S01), text_response("ok")]
    await turn(app, s["id"])
    res = app.store.messages(s["id"])[2].content[0]
    assert isinstance(res, ToolResultBlock) and res.is_error
    text = res.content[0].text
    assert text.startswith("Blocked by ladder.story_done: Story M1-S01 can't be marked done")
    assert "M1-S01-AC1: no observed test run" in text and "L1: no observed compile result" in text
    assert "- Status: doing" in (proj / "BACKLOG.md").read_text().split("### M1-S02")[0]
    row = app.db.one("SELECT * FROM gate_runs WHERE gate='ladder.story_done'")
    assert row["status"] == "fail" and json.loads(row["subjects"]) == ["M1-S01"]

    # With fresh observed evidence the same edit goes through, and the turn-end check doesn't re-block it.
    await compile_ok(app, s, proj)
    await run_tests_ok(app, s, proj, {"G.MoveTests.M1_S01_Moves": "Passed"})
    app.fake.script = [tool_response("edit_file", FLIP_S01), text_response("done")]
    await turn(app, s["id"], "again")
    m = app.store.messages(s["id"])
    assert not m[-2].content[0].is_error and m[-1].role == "assistant" and not m[-1].meta.get("notice")
    assert "### M1-S01 Movement\n- Status: done" in (proj / "BACKLOG.md").read_text()
    assert [r["status"] for r in app.db.all("SELECT status FROM gate_runs WHERE gate='ladder.story_done' "
                                            "ORDER BY started_at")] == ["fail", "pass"]


async def test_write_file_flip_and_new_done_story_checked(app, proj):
    s = session(app, proj)
    ctx = ctx_for(app, s)
    t = app.hooks.begin_turn(s["id"], time.time(), proj)
    new = BACKLOG.replace("### M1-S03 Playtest\n- Status: doing", "### M1-S03 Playtest\n- Status: done")
    r = await app.lad.story_done_pre_tool(HookEvent("pre_tool", ctx, tool="write_file",
                                                    args={"path": "BACKLOG.md", "content": new}, turn=t))
    assert r.action == "block" and "M1-S03-AC1: needs the user's check" in r.reason
    # A manual answer is the only evidence a manual criterion can have (L1 is always needed too).
    await compile_ok(app, s, proj)
    app.lad.record_evidence(proj, "manual", "pass", source="card:manual_check", observed="human", subjects=["M1-S03-AC1"])
    r = await app.lad.story_done_pre_tool(HookEvent("pre_tool", ctx, tool="write_file",
                                                    args={"path": "BACKLOG.md", "content": new}, turn=t))
    assert r.action == "allow" and r.status == "pass" and "M1-S03" in t.data["ladder"]["allowed"]
    # Unrelated edits pass through without a check.
    assert await app.lad.story_done_pre_tool(HookEvent("pre_tool", ctx, tool="edit_file", args={
        "path": "BACKLOG.md", "old": "Goal: Hit an enemy.", "new": "Goal: Hit two enemies."}, turn=t)) is None


async def test_sed_flip_caught_at_turn_end(app, proj):
    s = session(app, proj)

    @app.tools.add("sim_sed", "Rewrite BACKLOG.md like sed -i would", obj({}))
    async def sim_sed(ctx, a):
        p = ctx.folder / "BACKLOG.md"
        p.write_text(p.read_text().replace("### M1-S01 Movement\n- Status: doing", "### M1-S01 Movement\n- Status: done"))
        return ToolOutput("done")

    app.fake.script = [tool_response("sim_sed", {}), text_response("Marked done."), text_response("It is done."),
                       text_response("Really done.")]
    await turn(app, s["id"])
    m = app.store.messages(s["id"])
    gates = [x for x in m if x.meta.get("gate")]
    assert [g.meta["gate"]["id"] for g in gates] == ["ladder.story_done"] * 2
    assert gates[0].content[0].text.startswith("[GameDevWorkstation gate ladder.story_done] Story M1-S01 were marked done") or \
        "M1-S01" in gates[0].content[0].text
    assert "set the status back to doing" in gates[0].content[0].text
    assert m[-1].meta.get("notice") == "gate_exhausted"

    # The same flip with fresh evidence passes the turn-end check.
    p = proj / "BACKLOG.md"
    p.write_text(BACKLOG)
    await compile_ok(app, s, proj)
    await run_tests_ok(app, s, proj, {"G.MoveTests.M1_S01_Moves": "Passed"})
    app.fake.script = [tool_response("sim_sed", {}), text_response("Marked done.")]
    await turn(app, s["id"], "again")
    m = app.store.messages(s["id"])
    assert m[-1].role == "assistant" and not m[-1].meta.get("notice") and not m[-2].meta.get("gate")
    last = app.db.all("SELECT status FROM gate_runs WHERE gate='ladder.story_done' ORDER BY started_at")[-1]
    assert last["status"] == "pass"


# ------------------------------------------------------------------- visual rule


async def test_visual_rule_requires_a_fresh_png(app, proj):
    s = session(app, proj)
    ctx = ctx_for(app, s)
    t = TurnState(s["id"], time.time() - 30, folder=proj)
    (proj / "Assets/Game/Enemy.prefab").write_text("prefab")
    ev = HookEvent("pre_complete", ctx, turn=t)
    r = await app.lad.visual_pre_complete(ev)
    assert r.action == "block" and r.gate == "ladder.visual_evidence" and r.subjects == ["M1-S02"]
    assert "Assets/Game/Enemy.prefab" in r.reason and "M1-S02-hit: no screenshot PNG" in r.reason
    # An old screenshot doesn't count; one newer than the change does.
    shot = png(proj / "Logs/harness/verify/r1/shots/M1-S02-AC2-hit.png")
    age(shot, 120)
    r = await app.lad.visual_pre_complete(ev)
    assert r.action == "block" and "is older than" in r.reason
    os.utime(shot, None)
    r = await app.lad.visual_pre_complete(ev)
    assert r.action == "allow" and r.status == "pass"
    # `- Visual: no` turns the rule off for a story; a turn without visual or code changes needs nothing.
    (proj / "BACKLOG.md").write_text(BACKLOG.replace("- Critique: no", "- Visual: no"))
    os.utime(shot, (time.time() - 120,) * 2)
    assert await app.lad.visual_pre_complete(ev) is None
    (proj / "BACKLOG.md").write_text(BACKLOG)
    age(proj / "Assets/Game/Enemy.prefab", 600)
    assert await app.lad.visual_pre_complete(ev) is None


async def test_story_l3_needs_check_criteria_and_screenshot(app, proj):
    s = session(app, proj)
    await compile_ok(app, s, proj)
    await run_tests_ok(app, s, proj, {"G.HealthTests.M1_S02_DiesAtZero": "Passed"})
    st = state(app, proj, "M1-S02")
    assert st["levels"]["L3"]["state"] == "pending" and not st["ok"]
    await play_ok(app, s, proj)
    st = state(app, proj, "M1-S02")
    assert st["levels"]["L3"]["state"] == "pending" and any("M1-S02-hit: no screenshot" in x for x in st["missing"])
    png(proj / "Logs/harness/verify/20261112-1400-m1/shots/M1-S02-AC2-hit.png")
    st = state(app, proj, "M1-S02")
    assert st["ok"] and st["levels"]["L3"]["state"] == "pass" and st["levels"]["L3"]["shots"]
    assert st["levels"]["L4"]["state"] == "n/a" and st["levels"]["manual"]["state"] == "n/a"
    # Console errors during the run fail L3 even if the agent passes --no-error-gate.
    await play_ok(app, s, proj, lines=("[Combat] hit target=Enemy", "NullReferenceException: x"), extra_args="--no-error-gate")
    st = state(app, proj, "M1-S02")
    assert st["levels"]["L3"]["state"] == "fail"


# --------------------------------------------------------------- manual check


async def test_manual_check_via_card(app, proj):
    s = session(app, proj)
    ctx = ctx_for(app, s)
    assert "record_manual_check" in {t.name for t in app.runner.tool_specs(s)}
    task = asyncio.create_task(app.tools.run(ctx, "record_manual_check",
                                             {"ac_id": "M1-S03-AC1", "question": "Did 6 of 6 testers finish?"}))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if app.approvals.pending(s["id"]):
            break
    card = app.approvals.pending(s["id"])[0]
    assert card["kind"] == "manual_check" and "M1-S03-AC1" in card["payload"]["subject"]
    assert "Given the build" in card["payload"]["markdown"]
    app.approvals.resolve(card["id"], "approve", choice="pass", note="all six finished")
    out = await task
    assert "PASS" in out.text and "all six finished" in out.text
    row = app.lad.evidence(proj, levels=["manual"])[0]
    assert row["observed"] == "human" and row["status"] == "pass" and row["subjects"] == ["M1-S03-AC1"]
    assert state(app, proj, "M1-S03")["levels"]["manual"]["state"] == "pass"

    task = asyncio.create_task(app.tools.run(ctx, "record_manual_check", {"ac_id": "M1-S03-AC1", "question": "Again?"}))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if app.approvals.pending(s["id"]):
            break
    app.approvals.resolve(app.approvals.pending(s["id"])[0]["id"], "deny", choice="fail", note="2 got stuck")
    assert "FAIL" in (await task).text
    st = state(app, proj, "M1-S03")
    assert st["levels"]["manual"]["state"] == "fail" and any("2 got stuck" in m for m in st["missing"])
    bad = await app.tools.run(ctx, "record_manual_check", {"ac_id": "S03", "question": "x"})
    assert bad.is_error


# ---------------------------------------------------------------- critique


def review(score, verdict="pass", blockers=0, persona="r"):
    return {"persona": persona, "verdict": verdict, "score": score, "words": {},
            "issues": [{"severity": "blocker", "evidence": "shot.png", "fix": "x"}] * blockers}


def test_critique_aggregation():
    assert L.aggregate([review(8), review(9), review(7)])["verdict"] == "pass"
    agg = L.aggregate([review(8), review(9), review(6)])
    assert agg["verdict"] == "revise" and agg["score"] == 6  # minimum, under the pass score
    assert L.aggregate([review(9), review(9), review(8, blockers=1)])["verdict"] == "revise"  # a blocker
    assert L.aggregate([review(9), review(9), review(9, verdict="block")])["verdict"] == "revise"
    assert L.aggregate([review(9), review(4), review(8)])["verdict"] == "needs-human"  # disagreement > 3
    assert L.aggregate([review(9), review(6), review(8)])["verdict"] == "revise"  # a spread of 3 is not > 3
    assert L.aggregate([review(9), review(9), review(9)], behavioural_fail=["M1-S02 L2: failed"])["verdict"] == "revise"
    assert L.aggregate([review(9), None, None])["verdict"] == "error"
    assert L.parse_review('Sure:\n```json\n{"persona": "Art Director", "verdict": "pass", "score": 12}\n```')["score"] == 10
    assert L.parse_review("no json here") is None


async def _answer_card(app, sid, kind, decision, choice, note=""):
    for _ in range(200):
        await asyncio.sleep(0.01)
        cards = [c for c in app.approvals.pending(sid) if c["kind"] == kind]
        if cards:
            app.approvals.resolve(cards[0]["id"], decision, choice=choice, note=note)
            return cards[0]
    raise AssertionError("no card")


async def test_critique_rounds_and_escalation(app, proj, monkeypatch):
    s = session(app, proj)
    ctx = ctx_for(app, s)
    calls = []
    plan = []

    async def fake_reviewers(ctx_, folder, bl, ids, notes):
        calls.append(ids)
        return plan.pop(0), 0.12

    monkeypatch.setattr(app.lad, "run_reviewers", fake_reviewers)
    plan[:] = [[review(6, "revise"), review(7), review(7)], [review(6, "revise"), review(6), review(7)]]
    r1 = await app.lad.run_critique(ctx, stories=["M1-S02"])
    assert r1["verdict"] == "revise" and "round 1/2" in r1["text"]
    # Round 2 fails too: the escalation card (Accept / Revise with my notes / Park).
    task = asyncio.create_task(app.lad.run_critique(ctx, stories=["M1-S02"]))
    card = await _answer_card(app, s["id"], "critique_escalation", "deny", "revise", "brighter flash")
    assert [b["id"] for b in card["payload"]["buttons"]] == ["accept", "revise", "park"]
    assert "$0.12" in card["payload"]["markdown"]
    r2 = await task
    assert r2["choice"] == "revise" and "brighter flash" in r2["text"] and len(calls) == 2
    assert app.lad._critique_rounds(proj, "M1-S02") == 0  # the user's answer starts the count over

    # Two failed rounds on record: a third request goes straight to the card, no reviewers spent.
    for n in (1, 2):
        app.lad.record_evidence(proj, "L4", "fail", source="tool:critique", observed="tool", subjects=["M1-S02"],
                                detail={"key": "M1-S02", "round": n, "verdict": "revise"})
    task = asyncio.create_task(app.lad.run_critique(ctx, stories=["M1-S02"]))
    await _answer_card(app, s["id"], "critique_escalation", "approve", "accept")
    r3 = await task
    assert r3["verdict"] == "pass" and len(calls) == 2
    row = app.lad.evidence(proj, levels=["L4"])[0]
    assert row["observed"] == "human" and row["status"] == "pass"
    bl = L.read_backlog(proj)
    st = app.lad.story_state(proj, bl.stories["M1-S02"], require_critique=True)
    assert st["levels"]["L4"]["state"] == "pass"

    # Disagreement goes to the user at once.
    plan[:] = [[review(9), review(4), review(8)]]
    task = asyncio.create_task(app.lad.run_critique(ctx, stories=["M1-S02"]))
    await _answer_card(app, s["id"], "critique_escalation", "deny", "park")
    assert "parked" in (await task)["text"]


async def test_critique_behavioural_override(app, proj, monkeypatch):
    s = session(app, proj)
    called = []

    async def fake_reviewers(*a):
        called.append(1)
        return [review(10)] * 3, 0.0

    monkeypatch.setattr(app.lad, "run_reviewers", fake_reviewers)
    await run_tests_ok(app, s, proj, {"G.HealthTests.M1_S02_DiesAtZero": "Failed"})
    r = await app.lad.run_critique(ctx_for(app, s), stories=["M1-S02"])
    assert r["verdict"] == "revise" and "Critique not run" in r["text"] and not called
    assert app.lad.evidence(proj, levels=["L4"])[0]["detail"]["override"] is True


async def test_critique_spawns_three_cheap_reviewers(app, proj):
    from gamedevworkstation.features.subagents import SubagentManager

    class Reviewer(FakeProvider):
        def _next(self, req):
            brief = req.messages[0].text()
            persona = next(p for p in ("Spec Auditor", "Player Advocate", "Art Director") if p in brief)
            return text_response(json.dumps({"persona": persona, "verdict": "pass", "score": 8, "issues": []}))

    fake = Reviewer()
    app.providers.override("anthropic", "default", fake)
    mgr = SubagentManager(app)
    app.extensions["subagents"] = mgr
    s = session(app, proj)
    r = await app.lad.run_critique(ctx_for(app, s), stories=["M1-S02"], notes="check the flash")
    assert r["verdict"] == "pass" and r["score"] == 8
    subs = list(mgr.subs.values())
    assert len(subs) == 3 and {x.job_type for x in subs} == {"design_critique"}
    assert {x.tier for x in subs} == {"claude.standard"} and {x.effort for x in subs} == {"low"}
    assert all(x.tools == ["read_file", "list_dir", "view_image"] for x in subs)
    assert all("M1-S02-AC2" in c.messages[0].text() and "check the flash" in c.messages[0].text() for c in fake.calls)
    assert app.lad.evidence(proj, levels=["L4"])[0]["status"] == "pass"


def test_reviewer_briefs_from_skill(tmp_path, monkeypatch):
    assert [p for _k, p, _b in L.reviewer_briefs()] == ["Spec Auditor", "Player Advocate", "Art Director"]
    ref = tmp_path / "skills/design-critique/references"
    ref.mkdir(parents=True)
    (ref / "reviewers.md").write_text("# Reviewers\n## Spec Auditor\nCheck ACs vs VERIFY.md.\n"
                                      "## User Advocate\nThreat readability.\n")
    import gamedevworkstation.skills as sk

    monkeypatch.setattr(sk, "builtin_skills_dir", lambda: tmp_path / "skills")
    b = {p: brief for _k, p, brief in L.reviewer_briefs()}
    assert "Check ACs vs VERIFY.md." in b["Spec Auditor"] and "Threat readability." in b["Player Advocate"]
    assert b["Art Director"] == L.BUILTIN_REVIEWERS[2][2]  # missing section: built-in brief


# ---------------------------------------------------------------- view_image


async def test_view_image_scoped_and_resized(app, proj, tmp_path):
    s = session(app, proj)
    ctx = ctx_for(app, s)
    png(proj / "Logs/small.png", 8, 6)
    out = await app.tools.run(ctx, "view_image", {"path": "Logs/small.png"})
    assert not out.is_error and out.images and out.images[0].media_type == "image/png" and "8×6" in out.text
    outside = png(tmp_path / "elsewhere.png")
    out = await app.tools.run(ctx, "view_image", {"path": str(outside)})
    assert out.is_error and "outside the session folder" in out.text
    out = await app.tools.run(ctx, "view_image", {"path": "BACKLOG.md"})
    assert out.is_error and "not an image" in out.text
    (proj / "Logs/fake.png").write_text("not a png")
    assert (await app.tools.run(ctx, "view_image", {"path": "Logs/fake.png"})).is_error
    big = png(proj / "Logs/big.png", 2048, 1536)
    out = await app.tools.run(ctx, "view_image", {"path": "Logs/big.png"})
    assert not out.is_error
    if shutil.which("sips"):
        from gamedevworkstation.core.media import file_dims

        sent = Path(out.images[0].path)
        assert sent != big and max(file_dims(sent)) <= 1024 and "resized from 2048×1536" in out.text
        assert big.stat().st_size and file_dims(big) == (2048, 1536)  # the original is untouched
    # Read-only, so a reviewer subagent can be granted it; it sees only its own folder.
    assert app.tools.tools["view_image"].spec.read_only
    sub = ToolContext(app=app, session=s, run_id="sub_1", role="subagent")
    assert not (await app.tools.run(sub, "view_image", {"path": "Logs/small.png"}, allowed=["view_image"])).is_error
    assert (await app.tools.run(sub, "view_image", {"path": str(outside)}, allowed=["view_image"])).is_error


def test_tools_offered_only_when_relevant(app, proj, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    names = lambda s: {t.name for t in app.runner.tool_specs(s)}  # noqa: E731
    assert {"record_manual_check", "critique", "view_image"} <= names(session(app, proj))
    got = names(session(app, plain))
    assert "view_image" in got and not ({"record_manual_check", "critique"} & got)


# ------------------------------------------------------------------------- REST


def test_rest_report_evidence_and_override(tmp_path, proj):
    from fastapi.testclient import TestClient

    from gamedevworkstation.server import create_app

    st = AppState(db_path=tmp_path / "t.db")
    h = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", st)) as c:
        s = st.store.create(folder=str(proj), mode="accept_edits")
        r = c.get(f"/api/ladder?session_id={s['id']}", headers=h).json()
        assert r["enabled"] and r["unity"] and r["backlog"] and r["current"] == "M1"
        assert [x["id"] for x in r["stories"]] == ["M1-S01", "M1-S02", "M1-S03"]
        s1 = r["stories"][0]
        assert s1["levels"]["L1"]["state"] == "pending" and s1["levels"]["L2"]["state"] == "pending" and not s1["ok"]
        lad = st.extensions["ladder"]
        eid = lad.record_evidence(proj, "L1", "pass", source="gate:unity.compile", observed="gate", session_id=s["id"],
                                  detail={"summary": "0 errors"})
        assert c.get(f"/api/ladder/evidence/{eid}", headers=h).json()["detail"] == {"summary": "0 errors"}
        assert c.get(f"/api/ladder/evidence?session_id={s['id']}&level=L1", headers=h).json()[0]["id"] == eid
        assert c.post("/api/ladder/override", json={"session_id": s["id"], "story": "M1-S01", "note": "trust me"},
                      headers=h).status_code == 200
        r = c.get(f"/api/ladder?session_id={s['id']}&story=M1-S01", headers=h).json()
        assert r["stories"][0]["ok"] and r["stories"][0]["override"]["status"] == "pass"
        row = st.db.one("SELECT observed, detail FROM ladder_evidence WHERE level='override'")
        assert row["observed"] == "human_override" and "M1-S01-AC1" in row["detail"]
        assert c.post("/api/ladder/override", json={"session_id": s["id"], "story": "M9-S99"}, headers=h).status_code == 400
        plain = st.store.create()
        assert c.get(f"/api/ladder?session_id={plain['id']}", headers=h).json()["enabled"] is False


# ------------------------------------------------------------- more observers / API


async def test_batchmode_compile_and_check_scripts(app, proj):
    s = session(app, proj)
    log = proj / "Logs/harness/compile.log"
    log.parent.mkdir(parents=True)
    log.write_text("Refreshing native plugins\nCompilation finished\n")
    await observe(app, s, "run_command", {"command": "~/skills/headless-ops/scripts/unity.sh compile"},
                  f"exit code 0\nRESULT: OK compile (log {log})")
    row = app.lad.evidence(proj, levels=["L1"])[0]
    assert row["status"] == "pass" and row["source"] == "cmd:unity.sh" and row["path"] == str(log.resolve())
    # A RESULT line the log doesn't back is no evidence.
    log.write_text("Assets/Game/Hit.cs(3,1): error CS1002: ; expected\n")
    n = len(app.lad.evidence(proj))
    await observe(app, s, "run_command", {"command": "unity.sh compile"}, f"exit code 0\nRESULT: OK compile (log {log})")
    assert len(app.lad.evidence(proj)) == n
    # Timeouts / an open editor: no evidence either way.
    await observe(app, s, "run_command", {"command": "unity.sh compile"}, "exit code 1\nRESULT: FAIL editor-open")
    assert len(app.lad.evidence(proj)) == n
    # backlog_lint / perf_report / unity_antipatterns RESULT lines are plain checks, not a level.
    await observe(app, s, "run_command", {"command": "python3 skills/x/backlog_lint.py BACKLOG.md"},
                  "exit code 1\nERROR M1-S02: bad\nRESULT: FAIL 1 error")
    chk = app.lad.evidence(proj, levels=["check"])[0]
    assert chk["status"] == "fail" and chk["detail"]["script"] == "backlog_lint.py"
    # Declined / background commands (no "exit code" header) are ignored.
    assert await observe(app, s, "run_command", {"command": f"python3 {PARSE_LOG} Logs/harness/compile.log"},
                         "Started in the background") is None


async def test_read_console_counts_only_for_gates(app, proj):
    s = session(app, proj)
    body = wrap_untrusted(json.dumps({"success": True, "data": [
        {"type": "error", "message": "Assets/Game/Hit.cs(3,1): error CS1002: ; expected"},
        {"type": "log", "message": "[VERIFY] fps.avg=58"}]}), "mcp:unity.read_console")
    await observe(app, s, "mcp__unity__read_console", {}, body)
    assert app.lad.evidence(proj, levels=["L1"]) == []  # the agent reading the console proves nothing
    assert app.lad.metric(proj, "fps.avg")[0] == "58"
    await observe(app, s, "mcp__unity__read_console", {}, body, role="hook")
    row = app.lad.evidence(proj, levels=["L1"])[0]
    assert row["status"] == "fail" and row["observed"] == "gate" and row["detail"]["compile_errors"] == 1


async def test_evidence_outside_roots_is_ignored(app, proj, tmp_path):
    s = session(app, proj)
    other = tmp_path / "other"
    other.mkdir()
    (other / "c.json").write_text("[]")
    await observe(app, s, "run_command", {"command": f"python3 {PARSE_LOG} {other / 'c.json'}"}, "exit code 0\nRESULT: OK")
    assert app.lad.evidence(proj) == []


async def test_campaign_policy_requires_critique(app, proj):
    s = session(app, proj)
    ctx = ctx_for(app, s)
    await compile_ok(app, s, proj)
    await run_tests_ok(app, s, proj, {"G.MoveTests.M1_S01_Moves": "Passed"})
    ev = HookEvent("pre_tool", ctx, tool="edit_file", args=FLIP_S01, turn=None)
    app.lad.critique_required = lambda sid: sid == s["id"]
    r = await app.lad.story_done_pre_tool(ev)
    assert r.action == "block" and "needs a design critique" in r.reason
    app.lad.critique_required = lambda sid: 1 / 0  # a broken policy fails closed
    assert (await app.lad.story_done_pre_tool(ev)).action == "block"
    app.lad.critique_required = None
    assert (await app.lad.story_done_pre_tool(ev)).status == "pass"


async def test_subagent_flip_is_blocked_too(app, proj):
    s = session(app, proj)
    sub = ctx_for(app, s, role="subagent")
    r = await app.hooks.fire(HookEvent("pre_tool", sub, tool="edit_file", args=FLIP_S01, unit="sub_1"))
    assert any(x.action == "block" and x.gate == "ladder.story_done" for x in r)


def test_report_and_check_stories_api(app, proj):
    ok, missing, states = app.lad.check_stories(proj, ["M1-S01", "M9-S99"])
    assert not ok and "M9-S99: not a story in BACKLOG.md" in missing and [x["id"] for x in states] == ["M1-S01"]
    rep = app.lad.report(proj, all_stories=True)
    assert rep["enabled"] and [x["id"] for x in rep["stories"]] == ["M1-S01", "M1-S02", "M1-S03"]
    assert rep["latest"]["code"]["path"] in ("Assets/Game/Hit.cs", "Assets/Game/Move.cs")
    assert app.lad.report(None)["enabled"] is False
    assert L.install(app) is app.lad  # idempotent


def test_rest_errors(tmp_path, proj):
    from fastapi.testclient import TestClient

    from gamedevworkstation.server import create_app

    st = AppState(db_path=tmp_path / "t.db")
    h = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", st)) as c:
        assert c.get("/api/ladder?session_id=nope", headers=h).status_code == 404
        assert c.get("/api/ladder/evidence/ev_missing", headers=h).status_code == 404
        plain = st.store.create(folder=str(tmp_path))
        assert c.post("/api/ladder/critique", json={"session_id": plain["id"], "stories": []}, headers=h).status_code == 400
        assert c.get("/api/ladder", headers={}).status_code in (401, 403)
