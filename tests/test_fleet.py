"""WP6 Fleet: scope claims and overlap, proportionality, the subagent scope guard, the pre_merge
scope diff, the merge circuit breaker, the post-merge compile gate, the discovery relay, dead
units and close_wave. Units run on a scripted provider in temporary git repositories."""
import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import ChatRequest, Message, Response, TextBlock, ToolResultBlock, ToolUseBlock, Usage, new_id
from gamedevworkstation.features import fleet as F
from gamedevworkstation.features import hooks as H
from gamedevworkstation.features import worktrees
from gamedevworkstation.features.subagents import SubagentManager, _register_tools
from gamedevworkstation.features.unity_bridge import BridgeResult, FakeUnityBridge
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response

from .conftest import untrusted

CS_ERR = "Assets/Game/UI/Hud.cs(1,1): error CS1002: ; expected"


class UnitFake(FakeProvider):
    """A fleet unit: writes each `WRITE: <path>` of its task (content `// <unit task tag> <path>`),
    then replies with a HANDOFF. In the task: `NOHANDOFF` ends without the block, `SLOW` takes
    ten seconds per call, `DISC: <text>.` is its discovery."""

    def __init__(self):
        super().__init__("openai")
        self.briefs: list[str] = []

    @staticmethod
    def task(req: ChatRequest) -> str:
        brief = req.messages[0].text()
        return brief.split("Task:\n", 1)[1].split("\n\nWhen you finish", 1)[0]

    async def complete(self, req: ChatRequest) -> Response:
        if "SLOW" in self.task(req):
            await asyncio.sleep(10)
        return await super().complete(req)

    def _next(self, req: ChatRequest) -> Response:
        if len(req.messages) == 1:
            self.briefs.append(req.messages[0].text())
        task = self.task(req)
        writes = re.findall(r"WRITE: (\S+)", task)
        done = sum(1 for m in req.messages if m.role == "user" and any(isinstance(b, ToolResultBlock) for b in m.content))
        usage = Usage(input_tokens=100, output_tokens=20, cost_usd=0.001)
        if done < len(writes):
            path = writes[done]
            return Response(id=new_id(), provider="openai", model=req.model, stop_reason="tool_use", usage=usage,
                            content=[ToolUseBlock(id=new_id("toolu_"), name="write_file",
                                                  input={"path": path, "content": f"// unit {path}\n"})])
        disc = (re.search(r"DISC: ([^.]+)\.", task) or [None, "none"])[1]
        text = "Finished."
        if "NOHANDOFF" not in task:
            text += ("\n\n---HANDOFF---\nWhat: wrote " + ", ".join(writes) + "\nDecisions: kept it small\n"
                     f"Discoveries: {disc}\nUnresolved: none\nReversibility: revert the branch\n"
                     f"Files: {', '.join(writes)}\n---")
        return Response(id=new_id(), provider="openai", model=req.model, content=[TextBlock(text=text)], usage=usage)


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "Game"
    for sub in ("UI", "Audio", "Enemies", "FX"):
        (d / "Assets/Game" / sub).mkdir(parents=True)
        (d / "Assets/Game" / sub / "README.md").write_text(f"{sub}\n")
    (d / "ProjectSettings").mkdir()
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")
    git(d, "init", "-q", "-b", "main")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "init")
    old = time.time() - 3600
    for p in d.rglob("*"):
        if ".git" not in p.parts:
            os.utime(p, (old, old))
    return d


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "antipatterns_script", lambda: tmp_path / "no-such-audit.py")
    a = AppState(db_path=tmp_path / "f.db")
    a.main = FakeProvider("anthropic")
    a.units = UnitFake()
    a.providers.override("anthropic", "default", a.main)
    a.providers.override("openai", "default", a.units)
    mgr = SubagentManager(a)
    a.extensions["subagents"] = mgr
    _register_tools(a, mgr)
    H.install(a)
    F.install(a)
    a.config.fleet = {**(a.config.fleet or {}), "enabled": True, "max_units": 3}
    return a


def ctx_for(app, folder, mode="accept_edits", **settings):
    s = app.store.create(folder=str(folder), mode=mode, **settings)
    return ToolContext(app=app, session=s, run_id=f"main:{s['id']}")


def unit(name, scope, task, **kw):
    return {"name": name, "tier": "codex.fast", "effort": "low", "scope": scope, "instructions": task, **kw}


async def start(app, ctx, units, name="wave"):
    out = await app.tools.run(ctx, "run_wave", {"name": name, "units": units})
    assert not out.is_error, out.text
    return re.search(r"wave_[0-9a-f]{16}", out.text).group(0)


async def wait(app, ctx, wid):
    out = await app.tools.run(ctx, "wave_status", {"id": wid, "timeout_s": 30})
    assert not out.is_error, out.text
    return out.text


def units_of(app, wid):
    return {u["name"]: u for u in F.get_fleet(app).wave(wid)["units"]}


async def answer(app, sid, kind, choice, decision="approve"):
    for _ in range(1000):
        cards = [c for c in app.approvals.pending(sid) if c["kind"] == kind]
        if cards:
            app.approvals.resolve(cards[0]["id"], decision, choice=choice)
            return cards[0]
        await asyncio.sleep(0.01)
    raise AssertionError(f"no {kind} card")


def two_units(**extra):
    return [unit("hud", ["Assets/Game/UI"], "WRITE: Assets/Game/UI/Hud.cs " + extra.get("hud", "")),
            unit("mixer", ["Assets/Game/Audio"], "WRITE: Assets/Game/Audio/Mixer.cs " + extra.get("mixer", ""))]


def branch_exists(repo, sub_id):
    return subprocess.run(["git", "rev-parse", "--verify", "-q", f"refs/heads/gdw/{sub_id}"], cwd=repo,
                          capture_output=True).returncode == 0


# ------------------------------------------------------------------ scopes


def test_overlap_rules():
    ov = F.overlaps
    # component prefix: UI vs UIKit is not an overlap; a parent folder is
    assert not ov("Assets/Game/UI", "Assets/Game/UIKit")
    assert ov("Assets/Game", "Assets/Game/UI") and ov("Assets/Game/UI/Hud", "Assets/Game/UI")
    # case and slashes
    assert ov("assets/game/ui", "Assets\\Game\\UI\\") and ov("./Assets//Game/UI/", "Assets/Game/UI")
    # globs widen to their fixed prefix
    assert F.scope_prefix("Assets/Game/UI/**/*.cs") == ("Assets/Game/UI", True)
    assert ov("Assets/Game/UI/**/*.cs", "Assets/Game/UI/Menu")
    assert not ov("Assets/Game/UI/*.cs", "Assets/Game/UIKit/*.cs")
    assert ov("Assets/*/UI", "Assets/Game/Audio")  # widened to Assets
    # read-only entries are references, not claims
    assert not ov("Assets/Game (read-only)", "Assets/Game/UI")
    assert F.parse_scope_entry("Assets/Shared (Read-Only)").read_only
    # in_scope follows the same rules and normalizes `..`
    ui = [F.parse_scope_entry("Assets/Game/UI")]
    assert F.in_scope("assets/game/ui/Hud.cs", ui) and not F.in_scope("Assets/Game/UIKit/x.cs", ui)
    assert not F.in_scope("Assets/Game/UI/../Audio/x.cs", ui) and not F.in_scope("../x.cs", ui)


def plans(*units):
    return F.plan_units(list(units))


def test_check_wave_rules(tmp_path):
    chk = lambda *u, **kw: F.check_wave(plans(*u), max_units=kw.get("max_units", 3), max_read_only=4,  # noqa: E731
                                        taken=kw.get("taken"))
    ok = chk(unit("a", ["Assets/Game/UI"], "x"), unit("b", ["Assets/Game/UIKit"], "y"))
    assert ok == []
    errs = chk(unit("a", ["Assets/Game"], "x"), unit("b", ["assets/game/UI/**"], "y"))
    assert len(errs) == 1 and "a and b claim overlapping scopes" in errs[0]
    # read-only references may overlap claims
    assert chk(unit("a", ["Assets/Game/UI", "Assets/Game/Audio (read-only)"], "x"),
               unit("b", ["Assets/Game/Audio"], "y")) == []
    # .gamedevworkstation is coordinator-only; a whole-project claim reaches into it
    assert any(".gamedevworkstation/" in e for e in chk(unit("a", [".gamedevworkstation/notes"], "x"), unit("b", ["Assets/B"], "y")))
    assert any("the whole project" in e for e in chk(unit("a", ["**/*.cs"], "x"), unit("b", ["Assets/B"], "y")))
    assert any("leaves the project" in e for e in chk(unit("a", ["../Other"], "x"), unit("b", ["Assets/B"], "y")))
    assert any("relative to the project" in e for e in chk(unit("a", ["/abs/A"], "x"), unit("b", ["Assets/B"], "y")))
    # proportionality: one unit, or all writers in one folder
    assert "use spawn_subagent" in chk(unit("a", ["Assets/A"], "x"))[0]
    errs = chk(unit("a", ["Assets/Game/UI/Hud.cs"], "x"), unit("b", ["Assets/Game/UI/Menu.cs"], "y"))
    assert len(errs) == 1 and "one folder" in errs[0]
    # caps: writers per wave
    many = [unit(n, [f"Assets/{n}"], "x") for n in "abcd"]
    assert any("at most 3" in e for e in chk(*many))
    # claims of the session's other open waves
    taken = [("old-unit", F.parse_scope_entry("Assets/Game/UI"))]
    assert any("still claimed by old-unit" in e for e in chk(unit("a", ["Assets/Game/UI/Hud"], "x"),
                                                               unit("b", ["Assets/B"], "y"), taken=taken))
    # dependency order
    order = [p.name for p in plans(unit("a", ["A"], "x", after=["b"]), unit("b", ["B"], "y"))]
    assert order == ["b", "a"]


def test_parse_handoff():
    text = ("Did it.\n\n---HANDOFF---\n- **What:** built the HUD\nDecisions: UIDocument per screen\n  and one panel\n"
            "Discoveries: none\nUnresolved: tween missing\nReversibility: revert\nFiles: `Assets/A.cs`, Assets/B.cs\n---\n")
    h = F.parse_handoff(text)
    assert h["built"] == "built the HUD" and h["decisions"] == "UIDocument per screen\nand one panel"
    assert h["failures"] == "tween missing" and h["files"] == ["Assets/A.cs", "Assets/B.cs"]
    assert F.parse_handoff("no block here") is None and F.parse_handoff("---HANDOFF---\n---") is None


# --------------------------------------------------------------- the tools


async def test_tools_offered_only_when_relevant(app, repo, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    names = lambda s: {t.name for t in app.runner.tool_specs(s)}  # noqa: E731
    s = app.store.create(folder=str(repo), mode="accept_edits")
    assert {"run_wave", "wave_status", "merge_wave", "close_wave"} <= names(s)
    assert "run_wave" not in names(app.store.create(folder=str(plain)))                      # not a git repo
    # Delegation is always pinned in progressive sessions; only a legacy (full) session can have it off.
    app.config.skills = {**app.config.skills, "disclosure": "full"}
    assert "run_wave" not in names(app.store.create(folder=str(repo), skills=[]))            # delegation not on
    app.config.fleet = {**app.config.fleet, "enabled": False}
    assert "run_wave" not in names(s) and "merge_wave" not in names(s)


async def test_wave_over_max_units_is_refused(app, repo):
    app.config.fleet = {**app.config.fleet, "max_units": 2}
    ctx = ctx_for(app, repo)
    out = await app.tools.run(ctx, "run_wave", {"name": "w", "units": [
        unit(n, [f"Assets/Game/{n}"], "x") for n in ("UI", "Audio", "Enemies")]})
    assert out.is_error and "3 writing units; a wave allows at most 2" in out.text
    out = await app.tools.run(ctx, "run_wave", {"name": "w", "units": [unit("a", ["Assets/Game/UI"], "x")]})
    assert out.is_error and "use spawn_subagent" in out.text
    assert app.extensions["subagents"].subs == {} and app.db.all("SELECT * FROM fleet_waves") == []


async def test_subagent_write_outside_scope_is_denied(app, repo):
    ctx = ctx_for(app, repo)
    wid = await start(app, ctx, two_units(hud="WRITE: Assets/Game/Audio/Steal.cs WRITE: .gamedevworkstation/notes.md"))
    await wait(app, ctx, wid)
    u = units_of(app, wid)
    assert u["hud"]["status"] == "done" and u["mixer"]["status"] == "done"
    wt = Path(u["hud"]["worktree"])
    assert (wt / "Assets/Game/UI/Hud.cs").exists()
    assert not (wt / "Assets/Game/Audio/Steal.cs").exists() and not (wt / ".gamedevworkstation/notes.md").exists()
    mgr = app.extensions["subagents"]
    sub = mgr.get(u["hud"]["sub_id"])
    mgr._load_history(sub)
    results = [b for m in sub.history if m.role == "user" for b in m.content if isinstance(b, ToolResultBlock)]
    assert [r.is_error for r in results] == [False, True, True]
    assert results[1].content[0].text.startswith("Blocked by fleet.scope: Assets/Game/Audio/Steal.cs is outside "
                                                  "this unit's scope (Assets/Game/UI)")
    # the brief carried the scope rules and the HANDOFF contract
    brief = next(b for b in app.units.briefs if '"hud"' in b)
    assert "Change files only under: `Assets/Game/UI`" in brief and "Other units own: mixer: Assets/Game/Audio" in brief
    assert "---HANDOFF---" in brief


async def test_out_of_scope_merge_diff_holds_the_unit(app, repo):
    ctx = ctx_for(app, repo)
    sid = ctx.session_id
    wid = await start(app, ctx, two_units())
    await wait(app, ctx, wid)
    hud = units_of(app, wid)["hud"]
    # a command (which no hook can intercept) changed a file outside the unit's scope
    (Path(hud["worktree"]) / "ProjectSettings/TagManager.asset").write_text("tags\n")
    task = asyncio.create_task(app.tools.run(ctx, "merge_wave", {"id": wid}))
    card = await answer(app, sid, "fleet_scope", "leave", "deny")
    out = await task
    assert "ProjectSettings/TagManager.asset" in card["payload"]["markdown"]
    assert "hud: held" in out.text and "Merged mixer." in out.text
    assert (repo / "Assets/Game/Audio/Mixer.cs").exists() and not (repo / "Assets/Game/UI/Hud.cs").exists()
    assert units_of(app, wid)["hud"]["status"] == "held" and branch_exists(repo, hud["sub_id"])
    # a direct merge_worktree is held by the pre_merge hook too
    r = await app.tools.run(ctx, "merge_worktree", {"id": hud["sub_id"]})
    assert r.is_error and r.text.startswith("Merge held. Blocked by fleet.merge_scope: hud changed files outside")
    # Merge anyway
    task = asyncio.create_task(app.tools.run(ctx, "merge_wave", {"id": wid}))
    await answer(app, sid, "fleet_scope", "merge")
    out = await task
    assert not out.is_error and "Merged hud." in out.text and "All units are merged" in out.text
    assert (repo / "ProjectSettings/TagManager.asset").exists() and (repo / "Assets/Game/UI/Hud.cs").exists()
    out = await app.tools.run(ctx, "close_wave", {"id": wid})
    assert not out.is_error and F.get_fleet(app).wave(wid)["status"] == "closed"


async def test_breaker_first_conflict_pauses_second_stops(app, repo):
    ctx = ctx_for(app, repo)
    sid = ctx.session_id
    wid = await start(app, ctx, two_units())
    await wait(app, ctx, wid)
    # the session branch moved on: the same new file with other content
    (repo / "Assets/Game/UI/Hud.cs").write_text("// main\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "main hud")
    task = asyncio.create_task(app.tools.run(ctx, "merge_wave", {"id": wid}))
    card = await answer(app, sid, "fleet_conflict", "resolve")
    out = await task
    assert "Assets/Game/UI/Hud.cs" in card["payload"]["markdown"]
    w = F.get_fleet(app).wave(wid)
    assert out.is_error and "the wave is paused and the remaining merges wait" in out.text
    assert "Resolve with a unit" in out.text
    assert w["status"] == "paused" and w["strikes"] == 1
    u = units_of(app, wid)
    assert u["hud"]["status"] == "conflict" and u["mixer"]["status"] == "done" and not u["mixer"]["merged"]
    assert not (repo / "Assets/Game/Audio/Mixer.cs").exists()  # the rest is held
    # still conflicting: the second conflict stops the wave and Fleet for the session, without a card
    out = await app.tools.run(ctx, "merge_wave", {"id": wid})
    assert out.is_error and "Second merge conflict" in out.text and "Fleet is off for this session" in out.text
    w = F.get_fleet(app).wave(wid)
    assert w["status"] == "stopped" and w["strikes"] == 2 and app.approvals.pending(sid) == []
    assert branch_exists(repo, u["hud"]["sub_id"]) and branch_exists(repo, u["mixer"]["sub_id"])
    out = await app.tools.run(ctx, "run_wave", {"name": "again", "units": [
        unit("a", ["Assets/Game/Enemies"], "x"), unit("b", ["Assets/Game/FX"], "y")]})
    assert out.is_error and "Fleet is stopped for this session" in out.text


async def test_conflict_skip_merges_the_rest_and_close_refuses_unmerged(app, repo):
    ctx = ctx_for(app, repo)
    sid = ctx.session_id
    wid = await start(app, ctx, two_units())
    await wait(app, ctx, wid)
    out = await app.tools.run(ctx, "close_wave", {"id": wid})
    assert out.is_error and "close_wave refused: unmerged work" in out.text and "hud" in out.text and "mixer" in out.text
    (repo / "Assets/Game/UI/Hud.cs").write_text("// main\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "main hud")
    task = asyncio.create_task(app.tools.run(ctx, "merge_wave", {"id": wid}))
    await answer(app, sid, "fleet_conflict", "skip")
    out = await task
    assert "hud: merge conflict in Assets/Game/UI/Hud.cs; skipped" in out.text and "Merged mixer." in out.text
    assert units_of(app, wid)["hud"]["status"] == "skipped" and F.get_fleet(app).wave(wid)["strikes"] == 1
    out = await app.tools.run(ctx, "close_wave", {"id": wid})
    assert out.is_error and "hud (gdw/" in out.text and "mixer" not in out.text.split("\n", 1)[1]
    # an explicit discard (what discard_worktree does after the user confirms) lets it close
    hud = units_of(app, wid)["hud"]["sub_id"]
    await worktrees.discard(app, sid, hud, force=True)
    out = await app.tools.run(ctx, "close_wave", {"id": wid})
    assert not out.is_error, out.text
    assert units_of(app, wid)["hud"]["status"] == "discarded" and not branch_exists(repo, hud)


async def test_compile_failure_after_merge_goes_through_gate_retries(app, repo):
    H.get_engine(app).enable_preset(repo.resolve())
    bridge = app.extensions["unity_bridge"] = FakeUnityBridge(app, compile=[
        BridgeResult("fail", "1 compile error", "mcp", report=CS_ERR, errors=1),     # post_merge, after hud
        BridgeResult("fail", "1 compile error", "mcp", report=CS_ERR, errors=1),     # turn end: fix requested
        BridgeResult("pass", "0 compile errors", "mcp")])
    ctx = ctx_for(app, repo)
    sid = ctx.session_id
    wid = await start(app, ctx, two_units())
    await wait(app, ctx, wid)
    app.main.script = [tool_response("merge_wave", {"id": wid}), text_response("merged"), text_response("fixed it")]
    app.store.add_message(sid, Message.user("merge the wave"))
    await app.runner.start(sid)
    m = app.store.messages(sid)
    res = next(b for x in m if x.role == "user" for b in x.content if isinstance(b, ToolResultBlock))
    text = res.content[0].text
    assert "Merged hud." in text and "[unity.compile] 1 compile error" in text
    assert "failed after merging hud; the remaining merges wait" in text
    assert (repo / "Assets/Game/UI/Hud.cs").exists() and not (repo / "Assets/Game/Audio/Mixer.cs").exists()
    gates = [x.meta["gate"] for x in m if x.meta.get("gate")]
    assert gates == [{"id": "unity.compile", "status": "fail", "attempt": 1, "max": 2, "hook": "cs-compile",
                      "level": "L1"}]
    assert m[-1].role == "assistant" and m[-1].content[0].text == "fixed it"
    rows = [(r["status"], r["attempt"]) for r in
            app.db.all("SELECT * FROM gate_runs WHERE gate='unity.compile' ORDER BY started_at, rowid")]
    assert rows == [("fail", 0), ("fail", 1), ("pass", 1)]
    assert [c[0] for c in bridge.calls] == ["compile"] * 3
    assert F.get_fleet(app).wave(wid)["status"] == "ready"  # mixer still queued for the next merge_wave


async def test_discoveries_relayed_into_next_wave_and_jsonl(app, repo):
    ctx = ctx_for(app, repo)
    wid = await start(app, ctx, two_units(hud="DISC: HUD panels share one UIDocument.",
                                          mixer="DISC: Mixer groups live under Audio/Mixer."), name="first")
    await wait(app, ctx, wid)
    rec = json.loads(app.db.one("SELECT discoveries FROM fleet_units WHERE sub_id=?",
                                [units_of(app, wid)["hud"]["sub_id"]])["discoveries"])
    assert rec["discoveries"] == "HUD panels share one UIDocument" and rec["status"] == "done"
    assert not (await app.tools.run(ctx, "merge_wave", {"id": wid})).is_error
    assert not (await app.tools.run(ctx, "close_wave", {"id": wid})).is_error
    wid2 = await start(app, ctx, [unit("grunt", ["Assets/Game/Enemies"], "WRITE: Assets/Game/Enemies/Grunt.cs"),
                                  unit("sparks", ["Assets/Game/FX"], "WRITE: Assets/Game/FX/Sparks.cs")], name="second")
    await wait(app, ctx, wid2)
    brief = next(b for b in app.units.briefs if '"grunt"' in b)
    relay = brief.split("Discoveries from earlier waves", 1)[1].split("\n", 1)[1].split("\n\nTask:", 1)[0]
    src, body = untrusted(relay)
    assert src == "fleet:discoveries"
    assert "wave 1 · hud (Assets/Game/UI)" in body and "HUD panels share one UIDocument" in body
    assert "Mixer groups live under Audio/Mixer" in body
    files = list((repo / ".gamedevworkstation/discoveries").glob("*.jsonl"))
    assert len(files) == 1
    lines = [json.loads(x) for x in files[0].read_text().splitlines()]
    assert len(lines) == 4 and {x["schema"] for x in lines} == {1}
    first = next(x for x in lines if x["unit"] == "hud")
    assert first["wave"] == 1 and first["session"] == ctx.session_id and first["scope"] == ["Assets/Game/UI"]
    assert first["status"] == "done" and first["files"] == ["Assets/Game/UI/Hud.cs"] and first["campaign"] is None
    assert {"ts", "decisions", "failures"} <= set(first)


async def test_dead_unit_is_requeued_and_its_branch_kept(app, repo):
    ctx = ctx_for(app, repo)
    wid = await start(app, ctx, two_units(hud="NOHANDOFF"))
    status = await wait(app, ctx, wid)
    u = units_of(app, wid)
    assert u["hud"]["status"] == "dead" and u["hud"]["reason"] == "finished without a HANDOFF block"
    assert "Requeue (dead units; claims released, branches kept): hud: Assets/Game/UI" in status
    hud = u["hud"]["sub_id"]
    assert branch_exists(repo, hud) and (Path(u["hud"]["worktree"]) / "Assets/Game/UI/Hud.cs").exists()
    out = await app.tools.run(ctx, "merge_wave", {"id": wid})
    assert "Merged mixer." in out.text and "hud" not in out.text.split("\n\n")[0]
    assert not (repo / "Assets/Game/UI/Hud.cs").exists()
    # its claim is released: a new wave may claim the scope again
    assert F.get_fleet(app)._taken(ctx.session_id) == []
    out = await app.tools.run(ctx, "close_wave", {"id": wid})
    assert out.is_error and "hud" in out.text and "uncommitted changes" in out.text  # merge before cleanup
    assert branch_exists(repo, hud)


async def test_unit_past_its_timeout_is_stopped_and_dead(app, repo):
    app.config.fleet = {**app.config.fleet, "unit_timeout_min": {"build": 0.01, "research": 0.01}}
    ctx = ctx_for(app, repo)
    wid = await start(app, ctx, two_units(hud="SLOW"))
    t0 = time.monotonic()
    status = await wait(app, ctx, wid)
    assert time.monotonic() - t0 < 8
    u = units_of(app, wid)
    assert u["hud"]["status"] == "dead" and "min limit" in u["hud"]["reason"] and u["mixer"]["status"] == "done"
    assert app.extensions["subagents"].get(u["hud"]["sub_id"]).status == "cancelled"
    assert "hud: Assets/Game/UI" in status


async def test_read_only_units_and_events(app, repo):
    ctx = ctx_for(app, repo)
    wid = await start(app, ctx, [unit("survey", ["Assets/Game"], "look around", read_only=True),
                                 unit("review", ["Assets/Game/UI"], "review the UI", read_only=True)])
    await wait(app, ctx, wid)
    w = F.get_fleet(app).wave(wid)
    assert [u["status"] for u in w["units"]] == ["done", "done"] and all(u["worktree"] is None for u in w["units"])
    assert w["units"][0]["scope"] == ["Assets/Game (read-only)"] and w["merge_queue"] == []
    evs = [e for e in app.bus.replay(0, ctx.session_id) if e["type"] == "wave.updated"]
    assert evs and evs[-1]["data"]["id"] == wid
    out = await app.tools.run(ctx, "close_wave", {"id": wid})
    assert not out.is_error
    bad = await app.tools.run(ctx, "run_wave", {"name": "x", "units": [
        unit("a", [], "x", read_only=True, tools=["write_file"]), unit("b", [], "y", read_only=True)]})
    assert bad.is_error and "read_only but was given write tools" in bad.text


def test_waves_route(tmp_path, repo):
    from fastapi.testclient import TestClient

    from gamedevworkstation.server import create_app

    st = AppState(db_path=tmp_path / "r.db")
    h = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", st)) as c:
        s = st.store.create(folder=str(repo))
        st.db.insert("fleet_waves", {"id": "wave_0123456789abcdef", "session_id": s["id"], "n": 1, "status": "ready",
                                     "strikes": 0, "created_at": time.time()})
        st.db.insert("fleet_units", {"wave_id": "wave_0123456789abcdef", "sub_id": "sub_1", "status": "done",
                                     "scope": ["Assets/Game/UI"], "read_only": 0, "merged": 0,
                                     "discoveries": json.dumps({"built": "hud", "status": "done"})})
        r = c.get("/api/waves", params={"session_id": s["id"]}, headers=h).json()
        assert len(r) == 1 and r[0]["units"][0]["scope"] == ["Assets/Game/UI"]
        assert r[0]["units"][0]["discoveries"] == "built: hud" and r[0]["merge_queue"] == ["sub_1"]
        assert c.get("/api/waves/wave_0123456789abcdef", headers=h).json()["n"] == 1
        assert c.get("/api/waves/nope", headers=h).status_code == 404
        assert "run_wave" in st.tools.tools and "fleet.scope" in st.hooks.handlers("pre_tool")
