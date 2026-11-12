"""WP7 integration of campaigns and chains: Fleet (fleet phases, the discovery relay into the
campaign file), template blocking_gates in the hooks engine, the harness lock, task-board links
and the schema (campaign tables from v3 next to the task board's v4)."""
import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from workspace.agent.tools import ToolContext
from workspace.app import AppState
from workspace.config import data_dir
from workspace.core.types import Message
from workspace.db import DB, SCHEMA_VERSION
from workspace.features import campaign_file as cf
from workspace.features import campaigns as C
from workspace.features import fleet as F
from workspace.features import hooks as H
from workspace.features import task_board as TB
from workspace.features.subagents import SubagentManager, _register_tools
from workspace.features.unity_bridge import FakeUnityBridge
from workspace.providers.fake import FakeProvider, text_response, tool_response
from workspace.server import create_app

from .test_fleet import UnitFake, git, start, unit, units_of, wait

REQ = ("Produce the enemy content batch: a grunt prefab under Assets/Game/Enemies and hit sparks under "
       "Assets/Game/FX, both wired into the arena scene, with the asset audit passing at the end of it all.")

FLEETFLOW = """
id = "fleetflow"
title = "Fleet flow"
summary = "plan, then produce in a wave"
kinds = ["chain", "campaign"]

[[phase]]
name = "Plan"
type = "plan"
done_when = [{ type = "file_exists", path = "plan.txt" }]

[[phase]]
name = "Produce"
type = "build"
fleet = true
done_when = [{ type = "file_exists", path = "made.txt" }]
"""

HANDOFF = "---HANDOFF---\n- What: planned\n- Decisions: none\n- Unresolved: none\n- Reversibility: delete plan.txt\n---"


@pytest.fixture
def tpl():
    d = data_dir() / "skills" / "fleetflow"
    (d / "chains").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: fleetflow\ndescription: test workflows\n---\nbody\n")
    (d / "chains" / "fleetflow.toml").write_text(FLEETFLOW)
    return d


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "Game"
    for sub in ("Enemies", "FX"):
        (d / "Assets/Game" / sub).mkdir(parents=True)
        (d / "Assets/Game" / sub / "README.md").write_text(f"{sub}\n")
    git(d, "init", "-q", "-b", "main")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "init")
    return d


@pytest.fixture
def app(tmp_path, tpl, monkeypatch):
    monkeypatch.setattr(H, "antipatterns_script", lambda: tmp_path / "no-such-audit.py")
    a = AppState(db_path=tmp_path / "w.db")
    a.main = FakeProvider("anthropic")
    a.units = UnitFake()
    a.providers.override("anthropic", "default", a.main)
    a.providers.override("openai", "default", a.units)
    subs = SubagentManager(a)
    a.extensions["subagents"] = subs
    _register_tools(a, subs)
    H.install(a)
    F.install(a)
    a.config.fleet = {**(a.config.fleet or {}), "enabled": True, "max_units": 3}
    return a


@pytest.fixture
def mgr(app):
    m = C.install(app)  # after Fleet: install wires the fleet starter
    yield m
    for t in list(m._waiters):
        t.cancel()


async def drain(app, mgr=None):
    fm = F.get_fleet(app)
    for _ in range(50):
        pending = [t for t in fm._tasks if not t.done()]
        if not pending:
            break
        await asyncio.wait(pending, timeout=1)
    if mgr is not None:
        await mgr.idle()


def tool_results(app, sid):
    return [b.content[0].text for m in app.store.messages(sid) for b in m.content if getattr(b, "type", "") == "tool_result"]


# ------------------------------------------------------------------- Fleet


def test_fleet_starter_is_wired_in_either_install_order(tmp_path, tpl):
    a = AppState(db_path=tmp_path / "a.db")
    m = C.install(a)
    assert m.fleet_starter is None
    F.install(a)  # Fleet after campaigns
    assert m.fleet_starter is not None
    b = AppState(db_path=tmp_path / "b.db")
    F.install(b)
    assert C.install(b).fleet_starter is not None  # campaigns after Fleet


async def test_fleet_discoveries_land_in_the_campaign_file(app, mgr, repo):
    c = await mgr.create({"template": "fleetflow", "request": REQ, "folder": str(repo)})
    s = app.store.create(folder=str(repo), mode="accept_edits", campaign_id=c["id"])
    ctx = ToolContext(app=app, session=s, run_id=f"main:{s['id']}")
    wid = await start(app, ctx, [unit("grunt", ["Assets/Game/Enemies"], "WRITE: Assets/Game/Enemies/Grunt.cs DISC: Grunts reuse the Enemy base prefab."),
                                 unit("sparks", ["Assets/Game/FX"], "WRITE: Assets/Game/FX/Sparks.cs DISC: Sparks need the URP particle shader.")])
    await wait(app, ctx, wid)
    await drain(app)
    assert F.get_fleet(app).wave(wid)["campaign_id"] == c["id"]
    disc = cf.read(repo / c["file"]).get("discoveries")
    lines = [ln for ln in disc.splitlines() if ln.startswith("- ")]
    assert len(lines) == 2, disc
    grunt = next(ln for ln in lines if "fleet:grunt" in ln)
    assert "wave 1 · grunt (Assets/Game/Enemies)" in grunt and "Grunts reuse the Enemy base prefab" in grunt
    assert any("fleet:sparks" in ln and "URP particle shader" in ln for ln in lines)
    # and in the campaign's log (campaign_status / the Campaigns page)
    assert [x["kind"] for x in mgr.row(c["id"])["breaker"]["log"]] == ["discovery", "discovery"]


async def test_legacy_append_discovery_still_works(app, repo):
    class Old:
        got: list = []

        def append_discovery(self, cid, text):
            self.got.append((cid, text))

    app.extensions["campaigns"] = Old()
    fm = F.get_fleet(app)
    s = app.store.create(folder=str(repo))
    app.db.insert("fleet_waves", {"id": "wave_1", "session_id": s["id"], "campaign_id": "cmp_x", "n": 1,
                                  "status": "running", "strikes": 0, "created_at": time.time()})
    fm._record_discovery("wave_1", {"sub_id": "sub_1", "scope": json.dumps(["Assets/A"]), "read_only": 0},
                         {"built": "a thing", "status": "done"})
    assert Old.got and Old.got[0][0] == "cmp_x" and "built: a thing" in Old.got[0][1]


async def test_fleet_phase_brief_carries_the_wave_guidance(app, mgr, repo, tmp_path):
    c = await mgr.create({"template": "fleetflow", "request": REQ, "folder": str(repo)})
    app.db.execute("UPDATE campaigns SET status='running', phase=1 WHERE id=?", [c["id"]])
    c = mgr.row(c["id"])
    s = await mgr._new_session(c, reason="test", prev=None)
    await mgr._post_brief(mgr.row(c["id"]), s["id"])
    brief = app.store.messages(s["id"])[0].text()
    assert "## Fleet\nFleet: this phase (Produce) can run as a wave" in brief
    assert f'campaign_id="{c["id"]}"' in brief and "at most 3 writing units" in brief and len(brief) <= C.BRIEF_MAX
    assert "run_wave" in {t.name for t in app.runner.tool_specs(app.store.get(s["id"]))}
    # A phase without fleet = true gets nothing; Fleet off or no git repository says so.
    assert await mgr._fleet_note(c, 0, s["id"]) == ""
    app.config.fleet = {**app.config.fleet, "enabled": False}
    assert (await mgr._fleet_note(c, 1, s["id"])).startswith("Fleet is off")
    app.config.fleet = {**app.config.fleet, "enabled": True}
    plain = tmp_path / "plain"
    plain.mkdir()
    s2 = app.store.create(folder=str(plain))
    assert "git repository" in await mgr._fleet_note(c, 1, s2["id"])
    # A broken starter never blocks the phase.
    async def boom(*_a):
        raise RuntimeError("x")

    mgr.fleet_starter = boom
    assert await mgr._fleet_note(c, 1, s["id"]) == ""


async def test_chain_next_step_result_carries_the_fleet_guidance(app, mgr, repo):
    s = app.store.create(folder=str(repo), mode="accept_edits")
    c = await mgr.create({"template": "fleetflow", "kind": "chain", "session_id": s["id"]})
    app.main.script = [tool_response("write_file", {"path": "plan.txt", "content": "x"}),
                       tool_response("chain_step_done", {"handoff": HANDOFF}), text_response("ok")]
    app.store.add_message(s["id"], Message.user("go"))
    await app.runner.start(s["id"])
    await mgr.idle()
    res = tool_results(app, s["id"])[-1]
    assert "Next: step 2/2 Produce (build)" in res and "Fleet: this phase (Produce) can run as a wave" in res
    assert f'campaign_id="{c["id"]}"' in res
    status = await app.tools.run(ToolContext(app=app, session=app.store.get(s["id"]), run_id="main:x"),
                                 "campaign_status", {})
    assert "Fleet-eligible" in status.text


# ------------------------------------------------------------ blocking gates


@pytest.fixture
def unity(tmp_path):
    d = tmp_path / "Unity"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")
    (d / "Assets/Game").mkdir(parents=True)
    (d / "Assets/Game/Hit.cs").write_text("class Hit {}\n")
    return d


async def test_template_blocking_gates_block_in_campaign_sessions(app, mgr, unity, tmp_path, monkeypatch):
    eng = H.get_engine(app)
    eng.enable_preset(unity.resolve())
    app.extensions["unity_bridge"] = FakeUnityBridge(app)
    # The audit fails on its first run and passes after the fix.
    script = tmp_path / "audit.py"
    script.write_text("import pathlib, sys\nf = pathlib.Path(sys.argv[0]).with_suffix('.n')\n"
                      "n = int(f.read_text()) if f.exists() else 0\nf.write_text(str(n + 1))\n"
                      "print('Assets/Game/Hit.cs:1 HOT_FIND in Update')\n"
                      "print('RESULT: FAIL 1 new' if n == 0 else 'RESULT: OK 0 new')\n")
    monkeypatch.setattr(H, "antipatterns_script", lambda: script)
    plain = app.store.create(folder=str(unity), mode="accept_edits")
    s = app.store.create(folder=str(unity), mode="accept_edits")
    c = await mgr.create({"template": "perf-pass", "kind": "chain", "session_id": s["id"]})
    assert c["breaker"]["blocking_gates"] == ["unity.antipatterns"]
    assert eng.blocking_gates(app.store.get(s["id"])) == {"unity.antipatterns"}
    assert eng.blocking_gates(plain) == set()
    edit = lambda: tool_response("write_file", {"path": "Assets/Game/Hit.cs", "content": "class Hit { void Update() {} }\n"})  # noqa: E731
    app.main.script = [edit(), text_response("done"), text_response("fixed it")]
    app.store.add_message(s["id"], Message.user("go"))
    await app.runner.start(s["id"])
    await mgr.idle()
    gates = [m for m in app.store.messages(s["id"]) if m.meta.get("gate")]
    assert len(gates) == 1 and gates[0].meta["gate"]["id"] == "unity.antipatterns"
    assert gates[0].meta["gate"]["status"] == "fail" and "RESULT: FAIL 1 new" in gates[0].text()
    assert app.store.messages(s["id"])[-1].text() == "fixed it"
    rows = app.db.all("SELECT status, campaign_id FROM gate_runs WHERE gate='unity.antipatterns' AND session_id=? "
                      "ORDER BY started_at, rowid", [s["id"]])
    assert [r["status"] for r in rows] == ["fail", "pass"] and rows[0]["campaign_id"] == c["id"]
    # Outside the campaign (and once it's abandoned) the same audit stays advisory.
    (tmp_path / "audit.n").unlink()
    app.main.script = [edit(), text_response("done")]
    app.store.add_message(plain["id"], Message.user("go"))
    await app.runner.start(plain["id"])
    await mgr.idle()
    assert not [m for m in app.store.messages(plain["id"]) if m.meta.get("gate")]
    await mgr.abandon(c["id"])
    assert eng.blocking_gates(app.store.get(s["id"])) == set()


# -------------------------------------------------- harness lock, task links


def test_harness_locked_for_campaign_sessions(tmp_path, tpl, repo):
    st = AppState(db_path=tmp_path / "r.db")
    st.providers.override("anthropic", "default", FakeProvider())
    h = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", st)) as cl:
        sdk = cl.post("/api/sessions", json={"folder": str(repo)}, headers=h).json()
        assert cl.patch(f"/api/sessions/{sdk['id']}", json={"harness": "agent_sdk"}, headers=h).status_code == 200
        r = cl.post("/api/campaigns", json={"template": "fleetflow", "kind": "chain", "session_id": sdk["id"]}, headers=h)
        assert r.status_code == 400 and "built-in loop" in r.json()["detail"]
        ses = cl.post("/api/sessions", json={"folder": str(repo)}, headers=h).json()
        c = cl.post("/api/campaigns", json={"template": "fleetflow", "kind": "chain", "session_id": ses["id"]},
                    headers=h).json()
        r = cl.patch(f"/api/sessions/{ses['id']}", json={"harness": "agent_sdk"}, headers=h)
        assert r.status_code == 400 and "built-in loop" in r.json()["detail"]
        assert cl.patch(f"/api/sessions/{ses['id']}", json={"harness": "builtin", "title": "x"}, headers=h).status_code == 200
        assert cl.post(f"/api/campaigns/{c['id']}/abandon", headers=h).status_code == 200
        assert cl.patch(f"/api/sessions/{ses['id']}", json={"harness": "agent_sdk"}, headers=h).status_code == 200


async def test_campaign_sessions_link_the_tasks_their_request_mentions(app, mgr, repo):
    tb = TB.install(app)
    t1 = tb.create(title="Grunt prefab")
    t2 = tb.create(title="Hit sparks")
    s = app.store.create(folder=str(repo), mode="accept_edits")
    await mgr.create({"template": "fleetflow", "kind": "chain", "session_id": s["id"],
                      "request": f"Do {t1['code']} and {t2['code'].lower()}; ignore Task99999."})
    assert {t["code"] for t in tb.by_session(s["id"])} == {t1["code"], t2["code"]}
    c = await mgr.create({"template": "fleetflow", "request": REQ + f" Tracks {t2['code']}.", "folder": str(repo)})
    s2 = await mgr._new_session(c, reason="plan", prev=None)
    assert [t["code"] for t in tb.by_session(s2["id"])] == [t2["code"]]


# ------------------------------------------------------------------- schema


def test_schema_has_campaign_and_task_board_tables(tmp_path):
    db = DB(tmp_path / "s.db")
    assert db.user_version() == SCHEMA_VERSION == 4
    names = {r["name"] for r in db.all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"campaigns", "campaign_sessions", "fleet_waves", "fleet_units", "gate_runs", "task_boards",
            "board_tasks", "task_sessions"} <= names
