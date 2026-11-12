"""WP5 campaigns and chains: templates, the campaign file, plan validation and approval, claims,
phases and done_when, handoff, autopilot, checkpoints, startup and the REST routes."""
import asyncio
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workspace.app import AppState
from workspace.config import data_dir
from workspace.features import campaign_file as cf
from workspace.features import campaigns as C
from workspace.features import chains as ch
from workspace.features.campaigns import CampaignError
from workspace.providers.fake import FakeProvider, text_response, tool_response
from workspace.server import create_app

REQ = ("Add a Boss Rush mode: from the Title screen a Boss Rush button starts a run of five bosses in a row with no "
       "rooms in between, death returns to Title within three seconds and the best time is saved and shown.")

FLOW = """
id = "flow"
title = "Test flow"
summary = "write then check"
kinds = ["chain", "campaign"]

[[phase]]
name = "Write"
type = "build"
retries = 2
done_when = [{ type = "file_exists", path = "out.txt", newer_than = "phase_start" }]

[[phase]]
name = "Check"
type = "verify"
done_when = [{ type = "file_exists", path = "done.txt" }]
"""

HANDOFF = "---HANDOFF---\n- What: wrote out.txt\n- Decisions: none\n- Unresolved: none\n- Reversibility: delete out.txt\n---"


@pytest.fixture
def tpl():
    d = data_dir() / "skills" / "testflow"
    (d / "chains").mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: testflow\ndescription: test workflows\n---\nbody\n")
    (d / "chains" / "flow.toml").write_text(FLOW)
    return d


@pytest.fixture
def app(tmp_path, tpl):
    a = AppState(db_path=tmp_path / "c.db")
    a.fake = FakeProvider()
    a.providers.override("anthropic", "default", a.fake)
    return a


@pytest.fixture
def mgr(app):
    m = C.install(app)
    yield m
    for t in list(m._waiters):
        t.cancel()


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return d


def covered(items=None, **extra):
    async def v(c, mode, payload):
        v.calls.append((mode, payload))
        if mode == "plan":
            return {"items": items if items is not None else [
                {"request_item": "Boss Rush mode", "covered_by": "Write", "status": "covered"}], **extra}
        return {"aligned": True, "verdict": "complete", "items": []}
    v.calls = []
    return v


def chain_session(app, proj, **kw):
    return app.store.create(folder=str(proj), mode="accept_edits", **kw)


def tool_results(app, sid):
    out = []
    for m in app.store.messages(sid):
        for b in m.content:
            if getattr(b, "type", "") == "tool_result":
                out.append(b.content[0].text)
    return out


async def settle(mgr):
    for _ in range(5):
        if mgr._waiters:
            await asyncio.wait(list(mgr._waiters), timeout=0.2)
        await mgr.idle()


# ------------------------------------------------------------------ templates


def test_builtin_templates_are_valid_and_store_types():
    ts, bad = ch.discover()
    assert not [b for b in bad if "unity-router" in b["file"]]
    assert {"new-mechanic", "bugfix", "juice-pass", "content-batch", "perf-pass", "release", "replace-system",
            "milestone"} <= set(ts)
    for t in ts.values():
        for p in t["phases"]:
            assert p["type"] in ch.PHASE_TYPES  # hooks.phase_type reads it
            assert any(c["type"] != "manual" for c in p["done_when"])
    assert ts["milestone"]["kinds"] == ["campaign"]
    assert ts["content-batch"]["phases"][1]["fleet"] is True


def test_template_without_checkable_condition_is_rejected(tpl):
    bad = {"id": "only-manual", "title": "x", "phase": [
        {"name": "Look", "type": "verify", "done_when": [{"type": "manual", "question": "ok?"}]}]}
    with pytest.raises(ch.TemplateError) as e:
        ch.validate_template(bad)
    assert "not only manual" in str(e.value)
    with pytest.raises(ch.TemplateError):
        ch.validate_template({"id": "x", "title": "x", "phase": [
            {"name": "A", "type": "frobnicate", "done_when": [{"type": "gate", "level": "L9"}]}]})
    (tpl / "chains" / "broken.toml").write_text(
        'id = "broken"\ntitle = "B"\n[[phase]]\nname = "A"\ntype = "build"\ndone_when = [{ type = "manual" }]\n')
    ts, errs = ch.discover()
    assert "broken" not in ts and "flow" in ts
    assert any(e["file"].endswith("broken.toml") for e in errs)


def test_applies_to(tmp_path):
    t = ch.discover()[0]["new-mechanic"]
    assert not ch.applies(t, tmp_path)
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.1f1\n")
    assert ch.applies(t, tmp_path)


def test_delta_targets_and_handoff_parsing():
    assert C.delta_targets(["Improve the jump feel", "Death returns to Title in < 3 s", "Refactor the save system",
                            "Boss Rush starts from Title"]) == ["Improve the jump feel", "Refactor the save system"]
    h = C.parse_handoff("blah\n" + HANDOFF + "\ntrailing")
    assert h["what"] == "wrote out.txt" and h["reversibility"] == "delete out.txt" and "trailing" not in h["raw"]
    assert C.parse_handoff("no block here") is None


# -------------------------------------------------------------- campaign file


def test_campaign_file_round_trips_and_keeps_user_edits(tmp_path):
    doc = cf.new_doc(slug="boss-rush", template="milestone", title="Boss Rush", request=REQ, budget_usd=15)
    text = cf.render(doc)
    assert cf.render(cf.parse(text)) == text
    # The user edits their sections and adds one of their own.
    text = text.replace("## Constraints\n", "## Constraints\n- Save format unchanged (ADR-004)\n")
    text += "## My notes\nkeep the boss order\n```\n## not a heading\n```\n"
    p = tmp_path / ".workspace" / "campaigns" / "boss-rush.md"
    cf.write_atomic(p, text)
    assert cf.render(cf.read(p)) == text

    async def go():
        locks = cf.FileLocks()

        def harness(d):
            d.front_set("status", "running")
            d.set("phases", cf.table(["#", "Phase"], [[1, "Spec"]]))
            d.set("continuation", "Phase: 1/1 Spec\nNext action: write the spec")
            d.append("decisions", "- D1: five bosses")

        await locks.update("c1", p, harness)

    asyncio.run(go())
    out = p.read_text()
    assert "- Save format unchanged (ADR-004)" in out and "## My notes\nkeep the boss order" in out
    assert "## not a heading" in out and "| 1 | Spec |" in out and "- D1: five bosses" in out
    assert "status: running            # mirror only" in out
    d = cf.parse(out)
    assert d.title == "Boss Rush" and d.front_get("status") == "running"
    assert d.get("constraints") == "- Save format unchanged (ADR-004)"
    assert [s.key for s in d.sections][-1] is None  # the user's section stays where it was
    assert not list(p.parent.glob(".*tmp*"))  # atomic write leaves no temp file


# ---------------------------------------------------------------- create rules


async def test_create_rules(app, mgr, proj):
    with pytest.raises(CampaignError) as e:
        await mgr.create({"template": "flow", "request": REQ, "folder": str(proj), "effort": "max"})
    assert e.value.status == 400 and "high" in str(e.value)
    with pytest.raises(CampaignError) as e:
        await mgr.create({"template": "flow", "request": "make a boss rush", "folder": str(proj)})
    assert "chain" in str(e.value)  # proportionality: offer a chain
    c = await mgr.create({"template": "flow", "request": REQ, "folder": str(proj)})
    assert c["status"] == "draft" and c["phase"] == -1 and c["kind"] == "campaign"
    assert all(p["type"] for p in c["phases"])
    f = proj / c["file"]
    assert f.is_file() and "## Request (verbatim)\n> Add a Boss Rush mode" in f.read_text()
    c2 = await mgr.create({"template": "flow", "request": REQ, "folder": str(proj)})
    assert c2["slug"] != c["slug"]


# --------------------------------------------------------------- plan + approval


async def test_plan_validation_missing_blocks_approval(app, mgr, proj):
    mgr.validator = covered([{"request_item": "best time saved", "covered_by": "", "status": "missing"}])
    c = await mgr.create({"template": "flow", "request": REQ, "folder": str(proj)})
    app.fake.script = [tool_response("campaign_submit_plan", {"design_target": ["Boss Rush starts from Title"]}),
                       text_response("I'll fix it")]
    c = await mgr.start(c["id"])
    sid = c["claim_session"]
    await settle(mgr)
    c = mgr.row(c["id"])
    assert c["status"] == "planning"
    assert "doesn't cover the request" in tool_results(app, sid)[0] and "best time saved: missing" in tool_results(app, sid)[0]
    with pytest.raises(CampaignError) as e:
        await mgr.approve_plan(c["id"])
    assert e.value.status == 409
    assert not [a for a in app.approvals.pending() if a["kind"] == "campaign_plan"]
    doc = cf.read(proj / c["file"])
    assert "| best time saved |  | missing |" in doc.get("coverage")
    brief = app.store.messages(sid)[0]
    assert brief.meta["campaign_brief"]["phase"] == 0 and "[Campaign plan]" in brief.text()
    s = app.store.get(sid)
    assert s["settings"]["campaign_id"] == c["id"] and s["group_id"]


async def test_delta_target_goes_back_even_when_covered(app, mgr, proj):
    mgr.validator = covered()
    c = await mgr.create({"template": "flow", "request": REQ, "folder": str(proj)})
    app.fake.script = [tool_response("campaign_submit_plan", {"design_target": ["Improve the boss fights"]}),
                       text_response("ok")]
    c = await mgr.start(c["id"])
    await settle(mgr)
    assert mgr.row(c["id"])["status"] == "planning"
    assert "delta target" in tool_results(app, c["claim_session"])[0]


async def test_approval_handoff_brief_and_phase_checks(app, mgr, proj):
    mgr.validator = covered()
    c = await mgr.create({"template": "flow", "request": REQ, "folder": str(proj)})
    app.fake.script = [tool_response("campaign_submit_plan", {"design_target": ["Boss Rush starts from Title"],
                                                              "constraints": ["Save format unchanged"]}),
                       text_response("submitted")]
    c = await mgr.start(c["id"])
    plan_sid = c["claim_session"]
    await settle(mgr)
    c = mgr.row(c["id"])
    assert c["status"] == "awaiting_approval"
    card = next(a for a in app.approvals.pending(plan_sid) if a["kind"] == "campaign_plan")
    assert "Boss Rush starts from Title" in card["payload"]["markdown"]
    # Phase 1 session: writes out.txt, then declares the phase done.
    app.fake.script = [tool_response("write_file", {"path": "out.txt", "content": "x"}),
                       tool_response("campaign_phase_done", {"handoff": HANDOFF}), text_response("unused")]
    app.approvals.resolve(card["id"], "approve", choice="approve")
    await settle(mgr)
    c = mgr.row(c["id"])
    sessions = app.db.all("SELECT * FROM campaign_sessions WHERE campaign_id=? ORDER BY started_at", [c["id"]])
    assert [r["end_reason"] for r in sessions] == ["handoff", "handoff", None]
    p1, p2, p3 = (r["session_id"] for r in sessions)
    assert app.store.get(plan_sid)["settings"]["campaign_id"] is None  # ended sessions are normal again
    assert "passed" in tool_results(app, p2)[-1]
    assert c["phase"] == 1 and c["phases"][0]["status"] == "done" and c["phases"][1]["status"] == "running"
    assert c["status"] == "paused"  # autopilot off: phase 2 waits in its new session
    assert c["claim_session"] == p3
    brief = app.store.messages(p3)[0]
    assert brief.meta["campaign_brief"] == {"campaign_id": c["id"], "phase": 2, "title": c["title"]}
    text = brief.text()
    assert "## Design target" in text and "Boss Rush starts from Title" in text
    assert "## Continuation state" in text and "Next action:" in text and "## Constraints" in text
    assert "wrote out.txt" in text  # the handoff reached Active context
    assert len(text) <= C.BRIEF_MAX
    doc = cf.read(proj / c["file"])
    assert "| 1 | Write | build |" in doc.get("phases") and doc.front_get("status") == "paused"
    gates = app.db.all("SELECT * FROM gate_runs WHERE campaign_id=?", [c["id"]])
    assert [g["status"] for g in gates] == ["pass"]
    # Resume starts the waiting session (its brief is the pending message).
    app.fake.script = [text_response("on it")]
    c = await mgr.resume(c["id"])
    await settle(mgr)
    assert mgr.row(c["id"])["status"] == "running"
    assert app.store.messages(p3)[-1].text() == "on it"


async def test_failing_done_when_decrements_retries_then_parks(app, mgr, proj):
    s = chain_session(app, proj)
    c = await mgr.create({"template": "flow", "kind": "chain", "session_id": s["id"]})
    assert c["status"] == "running" and c["phase"] == 0
    app.fake.script = [tool_response("chain_step_done", {"handoff": HANDOFF}),
                       tool_response("chain_step_done", {"handoff": HANDOFF}), text_response("unused")]
    await run_turn(app, mgr, s["id"])
    res = tool_results(app, s["id"])
    assert "isn't done yet" in res[0] and "Retries left: 1" in res[0] and "no file matches out.txt" in res[0]
    assert "No retries left" in res[1]
    c = mgr.row(c["id"])
    assert c["status"] == "parked" and c["phases"][0]["retries"] == 0
    assert "done_when failed 2 times" in c["breaker"]["reason"]
    assert [g["status"] for g in app.db.all("SELECT status FROM gate_runs WHERE campaign_id=?", [c["id"]])] == \
        ["fail", "fail"]


async def test_chain_steps_advance_in_one_session_and_complete(app, mgr, proj):
    s = chain_session(app, proj)
    c = await mgr.create({"template": "flow", "kind": "chain", "session_id": s["id"]})
    from workspace.features.hooks import install as hooks_install

    assert hooks_install(app).phase_type(app.store.get(s["id"])) == "build"
    app.fake.script = [tool_response("write_file", {"path": "out.txt", "content": "x"}),
                       tool_response("chain_step_done", {"handoff": HANDOFF}),
                       tool_response("write_file", {"path": "done.txt", "content": "y"}),
                       tool_response("chain_step_done", {"handoff": HANDOFF}), text_response("all done")]
    from workspace.core.types import Message

    app.store.add_message(s["id"], Message.user("go"))
    await app.runner.start(s["id"])
    await settle(mgr)
    res = tool_results(app, s["id"])
    assert "Next: step 2/2 Check (verify)" in res[1] and "chain is complete" in res[3]
    c = mgr.row(c["id"])
    assert c["status"] == "done" and [p["status"] for p in c["phases"]] == ["done", "done"]
    assert any(m.meta.get("notice") == "campaign_done" for m in app.store.messages(s["id"]))


# ------------------------------------------------------------------ autopilot


async def chain_with_autopilot(app, mgr, proj, **body):
    s = chain_session(app, proj)
    c = await mgr.create({"template": "flow", "kind": "chain", "session_id": s["id"], "autopilot": True, **body})
    return s, c


async def run_turn(app, mgr, sid, text="go"):
    from workspace.core.types import Message

    app.store.add_message(sid, Message.user(text))
    await app.runner.start(sid)
    await settle(mgr)


async def test_autopilot_continues_on_progress_then_pauses_when_stalled(app, mgr, proj):
    s, c = await chain_with_autopilot(app, mgr, proj)
    app.fake.script = [tool_response("write_file", {"path": "notes.txt", "content": "x"}), text_response("working"),
                       text_response("still thinking"), text_response("hmm")]
    await run_turn(app, mgr, s["id"])
    conts = [m for m in app.store.messages(s["id"]) if m.meta.get("campaign_continue")]
    assert len(conts) == 2 and "Continue phase 1 (Write)" in conts[0].text()
    c = mgr.row(c["id"])
    assert c["status"] == "paused" and c["breaker"]["reason"].startswith("stalled: 2 turns")
    assert c["auto_turns"] == 2


async def test_autopilot_waits_on_pending_approval(app, mgr, proj):
    s, c = await chain_with_autopilot(app, mgr, proj)

    def final(req):
        app.approvals.request(s["id"], "command", {"subject": "rm -rf build"})
        return text_response("waiting")

    app.fake.script = [tool_response("write_file", {"path": "notes.txt", "content": "x"}), final]
    await run_turn(app, mgr, s["id"])
    c = mgr.row(c["id"])
    assert c["status"] == "waiting_user" and "approval" in c["breaker"]["reason"]
    assert not [m for m in app.store.messages(s["id"]) if m.meta.get("campaign_continue")]


async def test_autopilot_stops_on_budget_and_question(app, mgr, proj):
    s, c = await chain_with_autopilot(app, mgr, proj, budget_usd=1e-9)
    app.fake.script = [tool_response("write_file", {"path": "notes.txt", "content": "x"}), text_response("done")]
    await run_turn(app, mgr, s["id"])
    c = mgr.row(c["id"])
    assert c["status"] == "parked" and "budget" in c["breaker"]["reason"]
    s2, c2 = await chain_with_autopilot(app, mgr, proj)
    app.fake.script = [tool_response("write_file", {"path": "q.txt", "content": "x"}),
                       text_response("I made the arena.\n\nShould the bosses heal between fights?")]
    await run_turn(app, mgr, s2["id"])
    assert mgr.row(c2["id"])["status"] == "waiting_user"


# --------------------------------------------------------------------- claims


async def test_claim_exclusive_and_stale_recovery(app, mgr, proj):
    c = await mgr.create({"template": "flow", "request": REQ, "folder": str(proj)})
    a = app.store.create(folder=str(proj))
    b = app.store.create(folder=str(proj))
    assert mgr.claim(c["id"], a["id"])
    busy = asyncio.get_running_loop().create_future()
    app.runner.running[a["id"]] = busy  # session A is mid-turn
    try:
        assert not mgr.claim(c["id"], b["id"])
        assert mgr.claim(c["id"], a["id"])  # the holder refreshes its heartbeat
        app.db.execute("UPDATE campaigns SET claim_heartbeat=? WHERE id=?",
                       [time.time() - mgr.cfg("claim_stale_s") - 5, c["id"]])
        assert mgr.claim(c["id"], b["id"])  # stale: taken over even though A still runs
        assert mgr.row(c["id"])["claim_session"] == b["id"]
    finally:
        busy.cancel()
        app.runner.running.pop(a["id"], None)
    assert mgr.claim(c["id"], a["id"])  # B isn't running: claimable


async def test_startup_marks_running_campaigns_interrupted(app, mgr, proj):
    c = await mgr.create({"template": "flow", "request": REQ, "folder": str(proj)})
    s = app.store.create(folder=str(proj))
    app.db.execute("UPDATE campaigns SET status='running', phase=0, claim_session=? WHERE id=?", [s["id"], c["id"]])
    await mgr.astart()
    c = mgr.row(c["id"])
    assert c["status"] == "interrupted" and c["breaker"]["interrupted_from"] == "running"
    assert cf.read(proj / c["file"]).front_get("status") == "interrupted"


# ------------------------------------------------------------------ checkpoints


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.mark.skipif(not shutil.which("git"), reason="git missing")
async def test_checkpoint_ref_created_and_tree_untouched(app, mgr, proj):
    git(proj, "init", "-q")
    (proj / "a.txt").write_text("one\n")
    git(proj, "add", ".")
    git(proj, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    (proj / "a.txt").write_text("two\n")  # uncommitted work
    (proj / "new.txt").write_text("untracked\n")
    before = git(proj, "status", "--porcelain")
    s = chain_session(app, proj)
    c = await mgr.create({"template": "flow", "kind": "chain", "session_id": s["id"]})
    cp = c["phases"][0]["checkpoint"]
    assert cp["ref"] == f"refs/workspace/checkpoints/{c['slug']}/p1" and cp["kind"] == "stash"
    assert git(proj, "rev-parse", cp["ref"]).strip() == cp["sha"]
    assert "two" in git(proj, "show", f"{cp['sha']}:a.txt")
    assert git(proj, "status", "--porcelain") == before  # nothing changed
    assert (proj / "a.txt").read_text() == "two\n" and git(proj, "stash", "list") == ""
    assert cp["restore"].startswith("git restore --source=")


# ------------------------------------------------------------ ladder conditions


async def test_gate_conditions_read_ladder_evidence(app, mgr, proj):
    from workspace.features import ladder as L

    lad = L.install(app)
    C.get(app)  # already installed: the critique hook is chained on install only
    (proj / "Assets").mkdir()
    (proj / "Assets" / "A.cs").write_text("class A {}")
    s = chain_session(app, proj)
    c = await mgr.create({"template": "flow", "kind": "chain", "session_id": s["id"]})
    p = c["phases"][0]
    st, detail, _ = await mgr._check(c, p, {"type": "gate", "level": "L1"}, p["started_at"], s)
    assert st == "fail" and "no observed L1" in detail
    lad.record_evidence(proj, "L1", "pass", source="cmd:parse_unity_log.py", observed="command",
                        detail={"compile_errors": 0, "summary": "0 compile errors"})
    st, detail, _ = await mgr._check(c, p, {"type": "gate", "level": "L1"}, p["started_at"], s)
    assert st == "pass", detail
    lad.record_evidence(proj, "check", "pass", source="cmd:asset_audit.py", observed="command",
                        detail={"script": "asset_audit.py", "summary": "RESULT: OK"})
    st, _, _ = await mgr._check(c, p, {"type": "command_passes", "observe": "asset_audit"}, p["started_at"], s)
    assert st == "pass"
    st, _, _ = await mgr._check(c, p, {"type": "command_passes", "observe": "perf_report"}, p["started_at"], s)
    assert st == "fail"


async def test_critique_required_follows_template(app, proj):
    from workspace.features import ladder as L

    lad = L.install(app)
    mgr = C.install(app)
    s = chain_session(app, proj)
    c = await mgr.create({"template": "flow", "kind": "chain", "session_id": s["id"]})
    assert lad._require_critique(s["id"]) is False
    mgr._state(c, template_critique=True)
    assert lad._require_critique(s["id"]) is True


# ------------------------------------------------------------------------ REST


def test_rest_routes_and_purge(tmp_path, tpl, proj):
    s = AppState(db_path=tmp_path / "r.db")
    s.providers.override("anthropic", "default", FakeProvider())
    H = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", s)) as cl:
        r = cl.get("/api/chains", params={"folder": str(proj)}, headers=H).json()
        ids = {t["id"] for t in r["templates"]}
        assert "flow" in ids and "new-mechanic" not in ids  # not a Unity folder
        bad = cl.post("/api/campaigns", json={"template": "flow", "request": REQ, "folder": str(proj),
                                              "effort": "xhigh"}, headers=H)
        assert bad.status_code == 400
        c = cl.post("/api/campaigns", json={"template": "flow", "request": REQ, "folder": str(proj)}, headers=H).json()
        assert c["status"] == "draft"
        assert cl.patch(f"/api/campaigns/{c['id']}", json={"effort": "max"}, headers=H).status_code == 400
        upd = cl.patch(f"/api/campaigns/{c['id']}", json={"budget_usd": 3, "autopilot": True}, headers=H).json()
        assert upd["budget_usd"] == 3 and upd["autopilot"] is True
        lst = cl.get("/api/campaigns", headers=H).json()
        assert lst["campaigns"][0]["id"] == c["id"] and "first_pass_gate_rate" in lst["metrics"]
        d = cl.get(f"/api/campaigns/{c['id']}", headers=H).json()
        assert d["doc"]["design_target"] == [] and d["next_action"].startswith("Start")
        assert cl.post(f"/api/campaigns/{c['id']}/approve_plan", headers=H).status_code == 409
        assert cl.post(f"/api/campaigns/{c['id']}/frobnicate", headers=H).status_code == 404
        # A chain on a session; purging the session keeps the campaign history.
        ses = cl.post("/api/sessions", json={"folder": str(proj)}, headers=H).json()
        ch_ = cl.post("/api/campaigns", json={"template": "flow", "kind": "chain", "session_id": ses["id"]},
                      headers=H).json()
        assert ch_["status"] == "running"
        s.db.insert("gate_runs", {"id": "gate_x", "session_id": ses["id"], "campaign_id": ch_["id"], "gate": "g",
                                  "status": "pass", "started_at": time.time()})
        assert cl.delete(f"/api/sessions/{ses['id']}?purge=1", headers=H).status_code == 200
        assert s.db.one("SELECT COUNT(*) n FROM gate_runs WHERE session_id=?", [ses["id"]])["n"] == 0
        row = s.db.one("SELECT * FROM campaign_sessions WHERE session_id=?", [ses["id"]])
        assert row["end_reason"] == "deleted"
        assert s.db.one("SELECT claim_session FROM campaigns WHERE id=?", [ch_["id"]])["claim_session"] is None
