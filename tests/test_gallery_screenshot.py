"""Gallery screenshots: the side agent (request_screenshot) on each route with a scripted model and a fake bridge,
failures, tool scoping, the batch argv (never -nographics, real unity.sh with a fake editor), the MCP and live
capture paths of the real bridge, the scene-file reader and the harness version 3 template. Unity, the real
Unity CLI and the user's projects are never touched."""
import asyncio
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from gamedevworkstation.agent.tools import ToolContext, ToolOutput
from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import ImageBlock, Response, TextBlock, ToolResultBlock, ToolUseBlock, Usage, new_id
from gamedevworkstation.db import now
from gamedevworkstation.features import gallery as G
from gamedevworkstation.features import unity_cli as uc
from gamedevworkstation.features import unity_harness as uh
from gamedevworkstation.features import unity_scene as us
from gamedevworkstation.features.subagents import SubagentManager, _register_tools
from gamedevworkstation.features.unity_bridge import (BridgeResult, EditorState, FakeUnityBridge,
                                                      live_shot_code)
from gamedevworkstation.providers.fake import FakeProvider

from .test_unity_cli import bridge, fake_cli, session  # noqa: F401 (fixtures)

FIX = Path(__file__).parent / "fixtures" / "unity_scene"
UNITY_SH = Path(__file__).parents[1] / "skills/headless-ops/scripts/unity.sh"


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "Cave Game"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")
    shutil.copy(FIX / "EditorBuildSettings.asset", d / "ProjectSettings/EditorBuildSettings.asset")
    (d / "Assets/Scenes").mkdir(parents=True)
    shutil.copy(FIX / "Cave.unity", d / "Assets/Scenes/Cave.unity")
    (d / "Assets/Scenes/Menu.unity").write_text("%YAML 1.1\n")
    (d / "Assets/Props").mkdir()
    (d / "Assets/Props/Torch.prefab").write_text("%YAML 1.1\n")
    (d / "Assets/Props/Torch.prefab.meta").write_text("fileFormatVersion: 2\nguid: 0123456789abcdef0123456789abcdef\n")
    (d / "Packages").mkdir()
    (d / "Packages/manifest.json").write_text(json.dumps({"dependencies": {}}))
    return d.resolve()


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "g.db")
    from gamedevworkstation.features import hooks as H
    from gamedevworkstation.features import ladder as L
    from gamedevworkstation.features import unity_tool as UT

    H.install(a)
    L.install(a)
    UT.install(a)
    G.install(a)
    G._hook_item_events(a)
    mgr = SubagentManager(a)
    a.extensions["subagents"] = mgr
    _register_tools(a, mgr)
    return a


def model(app, steps):
    """A scripted side agent: each step is a (tool, input) call or a final text; inputs may be callables of the
    previous tool results' text."""
    seen: list[str] = []

    def make(step):
        def respond(req):
            last = req.messages[-1]
            seen.extend(b.as_text() for b in last.content if isinstance(b, ToolResultBlock))
            if isinstance(step, str):
                return Response(id=new_id(), provider="anthropic", model=req.model, content=[TextBlock(text=step)],
                                usage=Usage(input_tokens=50, output_tokens=10, cost_usd=0.001))
            name, inp = step
            return Response(id=new_id(), provider="anthropic", model=req.model, stop_reason="tool_use",
                            content=[ToolUseBlock(id=new_id("toolu_"), name=name, input=inp(seen) if callable(inp) else inp)],
                            usage=Usage(input_tokens=50, output_tokens=10, cost_usd=0.001))
        return respond

    fake = FakeProvider("anthropic", script=[make(s) for s in steps])
    app.providers.override("anthropic", "default", fake)
    return fake, seen


def pending(app, s, prompt):
    eid = new_id("shot_")
    entries = G._load(app, s["id"])
    entries[eid] = {"id": eid, "status": "pending", "prompt": prompt, "created_at": now(), "item_id": None, "path": None}
    G._save(app, s["id"], entries)
    return eid


def entry(app, s, eid):
    return next(e for e in G.list_gallery(app, s["id"]) if e["id"] == eid)


def fake_bridge(app, mode, **kw):
    st = EditorState(mode, True, editor_open=mode in ("mcp", "cli_live"), mcp_connected=mode == "mcp", **kw)
    b = app.extensions["unity_bridge"] = FakeUnityBridge(app, state=st)
    return b


GOOD = [("gallery_scene", {}),
        ("gallery_scene", {"scene": "Assets/Scenes/Cave.unity", "query": "Player"}),
        ("gallery_unity", {"op": "capture", "cam_pos": [16, 0.3, -3], "look_at": "Player", "time_of_day": "night"}),
        ("screenshot_plan", {"status": "captured", "capture": 1, "notes": "low angle from the cave mouth"}),
        "Captured 1."]


# ------------------------------------------------------------------ request_screenshot, per route


@pytest.mark.parametrize("route", ["mcp", "cli_live", "cli_batch", "raw_batch"])
async def test_request_screenshot_done_with_a_file_on_each_route(app, proj, route):
    if route in ("cli_batch", "raw_batch"):
        uh.install_harness(proj, exclude_from_git=False)
    b = fake_bridge(app, route)
    fake, seen = model(app, GOOD)
    s = session(app, proj)
    eid = pending(app, s, "player at the cave entrance, night, low angle")
    await G.request_screenshot(app, s, "player at the cave entrance, night, low angle", eid)
    e = entry(app, s, eid)
    assert e["status"] == "done", e
    p = Path(e["path"])
    assert p.is_file() and p.parent == proj / "Logs/harness/screenshots" and p.name == f"{eid}-1.png"
    assert e["prompt"] == "player at the cave entrance, night, low angle" and e["url"]
    meta = e["meta"]
    assert meta["route"] == route and meta["notes"] == "low angle from the cave mouth" and meta["stage"] == "done"
    assert meta["agent"]["model"] == "claude-sonnet-5-5"
    call = b.shot_calls[0]
    assert call["out"] == str(p) and call["width"] == 1920 and call["height"] == 1080
    if route in ("mcp", "cli_live"):
        # Live routes aim at the named object themselves (MCP view_target / a LookAt in the live snippet).
        assert call["view_target"] == "Player" and call["cam_rot"] is None
    else:
        # Batch: the camera rotation comes from the scene file (Player is at 16, 1, 0).
        assert call["view_target"] is None and call["cam_rot"] == us.look_rotation([16, 0.3, -3], [16, 1, 0])
        assert meta["camera"]["cam_rot"] == call["cam_rot"] and meta["camera"]["look_at"] == "Player"
    assert meta["camera"]["cam_pos"] == [16.0, 0.3, -3.0]
    assert call["allow_clone"] is False and call["time_of_day"] == "night"
    # The agent got the scene list and the Player's world position from the YAML.
    assert '"default":"Assets/Scenes/Cave.unity"' in seen[0] and '"path":"World/Player","pos":[16.0,1.0,0.0]' in seen[1]
    # Its tools: read-only file tools plus the three gallery tools; effort low, a small turn budget.
    req = fake.calls[0]
    names = {t.name for t in req.tools}
    assert names >= {"read_file", "list_dir", "search", "gallery_scene", "gallery_unity", "screenshot_plan"}
    assert not names & {"unity", "write_file", "edit_file", "delete_file", "run_command", "spawn_subagent"}
    assert not any(n.startswith("mcp__") for n in names)
    assert req.effort == "low"
    brief = req.messages[0].text()
    assert "never save a scene" in brief and "temporary camera" in brief and str(proj) in brief
    assert ("stop it again" in brief) == (route in ("mcp", "cli_live"))
    sub = next(iter(app.extensions["subagents"].subs.values()))
    assert sub.max_turns == 12 and sub.tier == "claude.standard" and sub.job_type == "gallery_screenshot"
    item = app.items.get(e["item_id"])
    assert item["source"] == "screenshot" and item["meta"]["capture"]["route"] == route


async def test_agent_reports_failure_reason(app, proj):
    fake_bridge(app, "mcp")
    model(app, [("gallery_scene", {"scene": "Assets/Scenes/Cave.unity", "query": "boss"}),
                ("screenshot_plan", {"status": "failed", "reason": "There is no boss in any scene."}), "No boss."])
    s = session(app, proj)
    eid = pending(app, s, "the boss fight")
    await G.request_screenshot(app, s, "the boss fight", eid)
    e = entry(app, s, eid)
    assert e["status"] == "failed" and e["reason"] == "There is no boss in any scene."
    assert not (proj / "Logs/harness/screenshots").exists() or not list((proj / "Logs/harness/screenshots").iterdir())


async def test_declined_capture_fails_with_the_bridge_reason(app, proj):
    b = fake_bridge(app, "cli_live")
    b._shots = [BridgeResult("skipped", "User declined Unity screenshot.", "cli_live")]
    model(app, [("gallery_unity", {"op": "capture"}), "Declined."])
    s = session(app, proj)
    eid = pending(app, s, "main menu")
    await G.request_screenshot(app, s, "main menu", eid)
    e = entry(app, s, eid)
    assert e["status"] == "failed" and "User declined Unity screenshot" in e["reason"]


async def test_unavailable_route_fails_with_actions_before_any_model_call(app, proj):
    fake_bridge(app, "unavailable", reason="Unity has this project open but the live Editor can't run it",
                actions=["install_pipeline", "close_editor"])
    fake, _ = model(app, ["unused"])
    s = session(app, proj)
    eid = pending(app, s, "anything")
    await G.request_screenshot(app, s, "anything", eid)
    e = entry(app, s, eid)
    assert e["status"] == "failed" and "live Editor can't run it" in e["reason"]
    assert "install the Pipeline package" in e["reason"] and "close the Unity Editor" in e["reason"]
    assert e["actions"] == ["install_pipeline", "close_editor"] and fake.calls == []


async def test_batch_without_harness_v3_says_needs_harness(app, proj):
    fake_bridge(app, "cli_batch")
    fake, _ = model(app, ["unused"])
    s = session(app, proj)
    eid = pending(app, s, "cave")
    await G.request_screenshot(app, s, "cave", eid)
    e = entry(app, s, eid)
    assert e["status"] == "failed" and "needs_harness" in e["reason"] and e["actions"] == ["install_harness"]
    # An installed version 2 harness isn't enough either (no Screenshot entry point).
    uh.install_harness(proj, exclude_from_git=False)
    old = b"// harness-version: 2\nclass HarnessCli {}\n"
    (proj / uh.HARNESS_DIR / "HarnessCli.cs").write_bytes(old)
    eid = pending(app, s, "cave")
    await G.request_screenshot(app, s, "cave", eid)
    assert "version 3 or newer" in entry(app, s, eid)["reason"] and fake.calls == []


async def test_plan_mode_and_non_unity_folders_fail_fast(app, proj, tmp_path):
    fake_bridge(app, "mcp")
    fake, _ = model(app, ["unused"])
    s = session(app, proj, mode="plan")
    eid = pending(app, s, "x")
    await G.request_screenshot(app, s, "x", eid)
    assert "Plan only mode" in entry(app, s, eid)["reason"]
    s2 = session(app, tmp_path)
    eid = pending(app, s2, "x")
    await G.request_screenshot(app, s2, "x", eid)
    assert "isn't a Unity project" in entry(app, s2, eid)["reason"] and fake.calls == []


async def test_capture_without_plan_still_counts_and_cap_limits(app, proj):
    fake_bridge(app, "mcp")
    model(app, [("gallery_unity", {"op": "capture", "camera": "Main Camera"}),
                ("gallery_unity", {"op": "capture", "camera": "Main Camera", "fov": 40}),
                ("gallery_unity", {"op": "capture"}),
                ("gallery_unity", {"op": "capture"}),
                "done"])
    s = session(app, proj)
    eid = pending(app, s, "menu")
    await G.request_screenshot(app, s, "menu", eid)
    e = entry(app, s, eid)
    assert e["status"] == "done" and e["path"].endswith(f"{eid}-3.png")  # the last capture; a 4th is refused
    assert len(list((proj / "Logs/harness/screenshots").glob(f"{eid}-*.png"))) == 3


async def test_parallel_captures_serialize_and_enforce_limit(app, proj, monkeypatch):
    b = fake_bridge(app, "mcp")
    s = session(app, proj)
    eid = pending(app, s, "menu")
    run = G.ShotRun(eid, s, "menu", proj, "mcp", False, proj / G.SHOT_DIR)
    ctx = ToolContext(app=app, session=s, run_id="parallel", role="subagent")
    original = b.screenshot

    async def delayed(*args, **kw):
        await asyncio.sleep(0.01)  # the bridge waits for approval / Unity in production
        return await original(*args, **kw)

    monkeypatch.setattr(b, "screenshot", delayed)
    results = await asyncio.gather(*(G.capture(app, ctx, run, {}) for _ in range(G.MAX_CAPTURES + 2)))
    assert [c["n"] for c in run.captures] == [1, 2, 3]
    assert len({c["path"] for c in run.captures}) == 3
    assert len(b.shot_calls) == G.MAX_CAPTURES
    assert sum(r.is_error for r in results) == 2


@pytest.mark.parametrize("entrypoint", [G.request_screenshot, G._run])
async def test_cancelled_request_stops_subagent_and_fails_entry(app, proj, monkeypatch, entrypoint):
    fake_bridge(app, "cli_live")
    s = session(app, proj)
    eid = pending(app, s, "menu")
    spawned = asyncio.Event()
    stopped = []
    sub = SimpleNamespace(id="sub_cancelled_gallery", done_event=asyncio.Event())

    async def spawn(*args):
        spawned.set()
        return sub

    async def stop(sub_id):
        stopped.append(sub_id)

    monkeypatch.setitem(app.extensions, "subagents", SimpleNamespace(spawn=spawn, stop=stop))
    task = asyncio.create_task(entrypoint(app, s, "menu", eid))
    await asyncio.wait_for(spawned.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped == [sub.id]
    assert entry(app, s, eid)["status"] == "failed"
    assert entry(app, s, eid)["reason"] == "cancelled"
    assert sub.id not in G._runs


def scoped_run(app, proj, monkeypatch, route="cli_live"):
    s = session(app, proj)
    eid = pending(app, s, "menu")
    run = G.ShotRun(eid, s, "menu", proj, route, False, proj / G.SHOT_DIR)
    ctx = ToolContext(app=app, session=s, run_id="sub_gallery_test", role="subagent")
    monkeypatch.setitem(G._runs, ctx.run_id, run)
    return run, ctx, app.tools.tools["gallery_unity"].handler


async def test_session_switch_to_plan_refuses_later_capture_and_play(app, proj, monkeypatch):
    b = fake_bridge(app, "cli_live")
    run, ctx, handler = scoped_run(app, proj, monkeypatch)
    assert not (await handler(ctx, {"op": "capture"})).is_error
    app.store.update(ctx.session_id, mode="plan")
    for args in ({"op": "capture"}, {"op": "play", "action": "start"}):
        result = await handler(ctx, args)
        assert result.is_error and "Plan only mode" in result.text
    # The capture entry point also rechecks, including after waiting for another capture's lock.
    result = await G.capture(app, ctx, run, {})
    assert result.is_error and "Plan only mode" in result.text
    assert len(b.shot_calls) == 1


@pytest.mark.parametrize("route", ["mcp", "cli_live"])
async def test_play_timeout_returns_error_and_still_attempts_stop(app, proj, monkeypatch, route):
    b = fake_bridge(app, route)
    run, ctx, handler = scoped_run(app, proj, monkeypatch, route)
    actions = []

    async def play(s, action, **kw):
        actions.append(action)
        if action == "start":
            assert run.play_started
            raise TimeoutError()
        return BridgeResult("pass", "stopped", route)

    async def mcp(s, tool, args, *rest):
        action = "start" if args["action"] == "play" else "stop"
        await play(s, action)
        return ToolOutput("stopped")

    monkeypatch.setattr(b, "play", play)
    monkeypatch.setattr(b, "_mcp_out", mcp)
    result = await handler(ctx, {"op": "play", "action": "start"})
    assert result.is_error and "timed out" in result.text
    assert run.play_started
    await G._undo_live_changes(app, run)
    assert actions == ["start", "stop"] and not run.play_started


async def test_existing_play_mode_is_not_stopped_by_cleanup(app, proj, monkeypatch):
    b = fake_bridge(app, "cli_live", live={"isPlaying": True})
    run, ctx, handler = scoped_run(app, proj, monkeypatch)
    actions = []

    async def play(s, action, **kw):
        actions.append(action)
        return BridgeResult("pass", "already playing", "cli_live")

    monkeypatch.setattr(b, "play", play)
    assert not (await handler(ctx, {"op": "play", "action": "start"})).is_error
    await G._undo_live_changes(app, run)
    assert actions == ["start"] and not run.play_started


async def test_cli_play_probe_detects_existing_play_mode(app, proj, fake_cli, monkeypatch):
    app.config.unity = {**app.config.unity, "backend": "cli"}
    fake_cli.set(status="ready", command_result={"isPlaying": True})
    b = bridge(app, open_=True)
    b.allow_op(proj, "play")
    run, ctx, handler = scoped_run(app, proj, monkeypatch)
    result = await handler(ctx, {"op": "play", "action": "start"})
    assert not result.is_error and not run.play_started
    await G._undo_live_changes(app, run)
    calls = fake_cli.calls_of("command")
    assert any(c[1:2] == ["editor_status"] for c in calls)
    assert not any(c[1:2] == ["editor_stop"] for c in calls)


async def test_unity_tool_play_timeout_is_an_error_result(app, proj, monkeypatch):
    from gamedevworkstation.features import unity_tool as UT

    b = fake_bridge(app, "cli_live")

    async def play(*args, **kw):
        raise TimeoutError()

    monkeypatch.setattr(b, "play", play)
    result = await UT.run_op(app, session(app, proj), {"op": "play", "action": "start"})
    assert result.is_error and "timed out" in result.text


@pytest.mark.parametrize("out", ["Assets/scene.png", "../escape.png", "Logs/harness/screenshots/../../outside.png"])
async def test_unity_tool_screenshot_refuses_outputs_outside_shot_dir(app, proj, out):
    from gamedevworkstation.features import unity_tool as UT

    b = fake_bridge(app, "cli_live")
    result = await UT.run_op(app, session(app, proj), {"op": "screenshot", "out": out})
    assert result.is_error and "Logs/harness/screenshots" in result.text
    assert b.shot_calls == []


async def test_unity_tool_screenshot_resolves_symlink_escape(app, proj, tmp_path):
    from gamedevworkstation.features import unity_tool as UT

    b = fake_bridge(app, "cli_live")
    shots = proj / G.SHOT_DIR
    shots.mkdir(parents=True)
    (shots / "escape").symlink_to(tmp_path, target_is_directory=True)
    s = session(app, proj)
    result = await UT.run_op(app, s, {"op": "screenshot", "out": str(shots / "escape/out.png")})
    assert result.is_error and not b.shot_calls
    result = await UT.run_op(app, s, {"op": "screenshot", "out": str(shots / "allowed.png")})
    assert not result.is_error and len(b.shot_calls) == 1


async def test_play_mode_started_is_stopped_afterwards(app, proj):
    b = fake_bridge(app, "cli_live")
    played: list[str] = []

    async def play(session, action="start", **kw):
        played.append(action)
        return BridgeResult("pass", f"play {action}", "cli_live")

    b.play = play  # type: ignore[method-assign]
    model(app, [("gallery_unity", {"op": "play", "action": "start"}), ("gallery_unity", {"op": "capture"}),
                ("screenshot_plan", {"status": "captured"}), "ok"])
    s = session(app, proj)
    eid = pending(app, s, "gameplay")
    await G.request_screenshot(app, s, "gameplay", eid)
    assert entry(app, s, eid)["status"] == "done" and played == ["start", "stop"]


async def test_gallery_tools_are_scoped_to_the_side_agent(app, proj):
    fake_bridge(app, "mcp")
    s = session(app, proj)
    names = {t.name for t in app.tools.specs(role="main", session=s)}
    assert not names & {"gallery_scene", "gallery_unity", "screenshot_plan"}
    main = ToolContext(app=app, session=s, run_id=f"main:{s['id']}")
    out = await app.tools.run(main, "gallery_unity", {"op": "capture"})
    assert out.is_error and "not available" in out.text
    other = ToolContext(app=app, session=s, run_id="sub_other", role="subagent")
    out = await app.tools.run(other, "gallery_unity", {"op": "capture"}, allowed=["gallery_unity"])
    assert out.is_error and "screenshot agent" in out.text
    assert not (proj / "Logs").exists()


def test_post_route_runs_the_side_agent(tmp_path, proj):
    """POST /api/gallery/screenshot → pending → done through the app (create_app registers the tools)."""
    import time

    from fastapi.testclient import TestClient

    from gamedevworkstation.server import create_app

    s = AppState(db_path=tmp_path / "p.db")
    with TestClient(create_app("t", s)) as c:
        fake_bridge(s, "mcp")
        model(s, [("gallery_unity", {"op": "capture", "cam_pos": [0, 2, -5], "cam_rot": [10, 0, 0]}),
                  ("screenshot_plan", {"status": "captured"}), "ok"])
        sess = s.store.create(folder=str(proj))
        e = c.post("/api/gallery/screenshot", json={"session_id": sess["id"], "prompt": "cave"},
                   headers={"Authorization": "Bearer t"}).json()
        deadline = time.time() + 10
        while time.time() < deadline:
            got = [x for x in c.get("/api/gallery", params={"session_id": sess["id"]},
                                    headers={"Authorization": "Bearer t"}).json() if x["id"] == e["id"]]
            if got and got[0]["status"] != "pending":
                break
            time.sleep(0.05)
        assert got[0]["status"] == "done", got
        assert got[0]["meta"]["route"] == "mcp" and got[0]["meta"]["camera"]["cam_rot"] == [10.0, 0.0, 0.0]


# ------------------------------------------------------------------ batch argv


def test_screenshot_args_never_nographics():
    a = uc.sh_screenshot_args(Path("/p/Logs/harness/screenshots/x.png"), scene="Assets/Scenes/Cave.unity",
                              cam_pos=[-0.5, 2, 1e-7], cam_rot=(10, 200.25, 0), fov=50, camera=None, time_of_day="night")
    assert a == ["screenshot", "--out", "/p/Logs/harness/screenshots/x.png", "--width", "1920", "--height", "1080",
                 "--scene", "Assets/Scenes/Cave.unity", "--cam-pos", "-0.5,2,0", "--cam-rot", "10,200.25,0",
                 "--fov", "50", "--time-of-day", "night"]
    assert not any("nographics" in x for x in a)
    for bad in ({"scene": "../x.unity"}, {"scene": "Assets/x.prefab"}, {"camera": "-quit"}, {"cam_pos": [1, 2]},
                {"fov": 500}, {"cam_rot": ["a", 1, 2]}):
        with pytest.raises(ValueError):
            uc.sh_screenshot_args(Path("/x.png"), **bad)
    assert "--time-of-day" not in uc.sh_screenshot_args(Path("/x.png"), time_of_day="-quit")


async def test_bridge_batch_screenshot_argv_and_clone_card(app, proj, tmp_path, monkeypatch):
    """Real bridge, Editor closed, no official CLI: unity.sh screenshot behind a `unity` card; no -nographics."""
    bindir = tmp_path / "shbin"
    bindir.mkdir()
    rec = tmp_path / "sh-args.txt"
    sh = bindir / "unity.sh"
    sh.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" > {rec}\nout=""\nwhile [ $# -gt 0 ]; do [ "$1" = --out ] && out="$2"; shift; done\n'
                  'printf "PNG" > "$out"\necho "[HARNESS] SHOT OK $out 1920x1080 scene=Assets/Scenes/Cave.unity temp camera '
                  'pos=1,2,3 rot=10,20,0 fov=60 bytes=3"\necho "RESULT: OK screenshot $out 1920x1080 scene=Assets/Scenes/Cave.unity '
                  'temp camera pos=1,2,3 rot=10,20,0 fov=60 bytes=3 (log x)"; exit 0\n')
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr("gamedevworkstation.services.default_shell", lambda: "/bin/bash")
    app.config.unity = {**(app.config.unity or {}), "backend": "mcp"}
    b = bridge(app)
    s = session(app, proj)
    assert (await b.editor_state(s, "screenshot")).mode == "raw_batch"
    out = proj / "Logs/harness/screenshots/t.png"
    r = await b.screenshot(s, out, cam_pos=[1, 2, 3], cam_rot=[10, 20, 0])
    assert r.status == "skipped" and r.evidence.get("needs_harness") and r.evidence["actions"] == ["install_harness"]
    uh.install_harness(proj, exclude_from_git=False)
    t = asyncio.create_task(b.screenshot(s, out, cam_pos=[1, 2, 3], cam_rot=[10, 20, 0], scene="Assets/Scenes/Cave.unity"))
    for _ in range(300):
        if cards := app.approvals.pending(s["id"]):
            break
        await asyncio.sleep(0.02)
    (card,) = cards
    p = card["payload"]
    assert p["op"] == "screenshot" and p["key"] == "screenshot" and "without saving it" in p["markdown"]
    assert "-nographics" not in " ".join(p["argv"]) and p["argv"][2:4] == ["screenshot", "--out"]
    app.approvals.resolve(card["id"], "approve")
    r = await t
    assert r.status == "pass" and r.evidence["screenshot"] == str(out) and out.read_bytes() == b"PNG"
    assert r.evidence["shot"]["used_pos"] == [1.0, 2.0, 3.0] and r.evidence["shot"]["used_fov"] == 60.0
    args = rec.read_text().splitlines()
    assert args[:3] == ["screenshot", "--out", str(out)] and "--cam-pos" in args and "--project" in args
    assert not any("nographics" in x for x in args)


def test_unity_sh_screenshot_runs_harness_with_graphics(proj, tmp_path):
    """The real unity.sh with a fake editor binary: HarnessCli.Screenshot, the camera args, no -nographics, no -quit."""
    uh.install_harness(proj, exclude_from_git=False)
    rec = tmp_path / "unity-args.txt"
    ed = tmp_path / "Unity"
    ed.write_text("#!/bin/bash\n"
                  f'printf "%s\\n" "$@" > {rec}\n'
                  'log=""; out=""\n'
                  'while [ $# -gt 0 ]; do case "$1" in -logFile) log="$2"; shift ;; -out) out="$2"; shift ;; esac; shift; done\n'
                  'printf "PNGDATA" > "$out"\n'
                  'echo "[HARNESS] SHOT OK $out 640x360 scene=Assets/Scenes/Cave.unity temp camera pos=1,2,-3 rot=10,0,0 fov=60 bytes=7" > "$log"\n'
                  'exit 0\n')
    ed.chmod(ed.stat().st_mode | stat.S_IEXEC)
    out = proj / "Logs/harness/screenshots/a.png"
    env = {**os.environ, "UNITY_PATH": str(ed)}
    argv = ["bash", str(UNITY_SH), *uc.sh_screenshot_args(out, width=640, height=360, cam_pos=[1, 2, -3],
                                                           cam_rot=[10, 0, 0], time_of_day="dusk"), "--project", str(proj)]
    r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"ARTIFACT: {out}" in r.stdout and r.stdout.strip().splitlines()[-1].startswith("RESULT: OK screenshot")
    ua = rec.read_text().splitlines()
    assert "-nographics" not in ua and "-quit" not in ua and "-batchmode" in ua
    i = ua.index("-executeMethod")
    assert ua[i + 1] == "Harness.Headless.HarnessCli.Screenshot"
    assert ua[ua.index("-camPos") + 1] == "1,2,-3" and ua[ua.index("-timeOfDay") + 1] == "dusk"
    assert ua[ua.index("-width") + 1] == "640" and ua[ua.index("-out") + 1] == str(out) and out.read_bytes() == b"PNGDATA"
    # --graphics or not, screenshot never gets -nographics; a bad --out is a usage error.
    r = subprocess.run(["bash", str(UNITY_SH), "screenshot", "--out", "x.jpg", "--project", str(proj)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 3 and "must end in .png" in r.stdout


def test_unity_sh_screenshot_needs_v3_entry_point(proj, tmp_path):
    ed = tmp_path / "Unity"
    ed.write_text("#!/bin/bash\nexit 0\n")
    ed.chmod(ed.stat().st_mode | stat.S_IEXEC)
    uh.install_harness(proj, exclude_from_git=False)
    (proj / uh.HARNESS_DIR / "HarnessCli.cs").write_text("namespace Harness.Headless { class HarnessCli {} }\n")
    r = subprocess.run(["bash", str(UNITY_SH), "screenshot", "--out", "a.png", "--project", str(proj)],
                       capture_output=True, text=True, env={**os.environ, "UNITY_PATH": str(ed)}, timeout=60)
    assert r.returncode == 3 and "no Screenshot entry point" in r.stdout


def test_unity_sh_screenshot_preserves_existing_output(proj, tmp_path):
    uh.install_harness(proj, exclude_from_git=False)
    ed = tmp_path / "Unity"
    ed.write_text("#!/bin/bash\nexit 99\n")
    ed.chmod(ed.stat().st_mode | stat.S_IEXEC)
    out = proj / "Logs/harness/screenshots/existing.png"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"original image")
    result = subprocess.run(["bash", str(UNITY_SH), "screenshot", "--out", str(out), "--project", str(proj)],
                            capture_output=True, text=True, env={**os.environ, "UNITY_PATH": str(ed)}, timeout=10)
    assert result.returncode == 3
    assert "RESULT: FAIL" in result.stdout and "refusing to overwrite" in result.stdout
    assert out.read_bytes() == b"original image"


# ------------------------------------------------------------------ MCP and live paths of the real bridge


class FakeMCP:
    """manage_camera stand-in: writes <output_folder>/<screenshot_file_name>.png (or only returns an inline image)."""

    def __init__(self, root: Path, *, write=True, assets=False):
        self.root, self.write, self.assets, self.calls = root, write, assets, []
        self.conns = {"unity": SimpleNamespace(tools=[SimpleNamespace(name="manage_camera")])}

    async def call(self, ctx, name, args):
        self.calls.append((name, args, ctx.role))
        if self.write:
            d = self.root / ("Assets" if self.assets else "") / args["output_folder"]
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{args['screenshot_file_name']}.png").write_bytes(b"\x89PNGmcp")
        import base64

        return ToolOutput("Screenshot captured", images=[ImageBlock(media_type="image/png",
                                                                    data=base64.b64encode(b"\x89PNGinline").decode())])


async def test_mcp_route_uses_manage_camera_with_a_temp_camera(app, proj):
    app.config.unity = {**(app.config.unity or {}), "backend": "mcp"}
    b = bridge(app, open_=True, mcp=(True, ""))
    app.mcp = FakeMCP(proj)
    s = session(app, proj)
    out = proj / "Logs/harness/screenshots/m.png"
    r = await b.screenshot(s, out, cam_pos=[0, 1.5, -4], cam_rot=[5, 0, 0], fov=40, width=1280, height=720)
    assert r.status == "pass" and r.mode == "mcp" and out.read_bytes() == b"\x89PNGmcp"
    (name, args, _role), = app.mcp.calls
    assert name == "mcp__unity__manage_camera"
    assert args == {"action": "screenshot", "capture_source": "game_view", "include_image": True, "max_resolution": 1280,
                    "screenshot_file_name": "m", "output_folder": "Logs/harness/screenshots",
                    "view_position": [0.0, 1.5, -4.0], "view_rotation": [5.0, 0.0, 0.0]}
    assert "fov was not applied" in r.evidence["note"]
    # Saved under Assets/ instead: moved out (Assets stays clean); no file at all: the inline image.
    app.mcp = FakeMCP(proj, assets=True)
    out2 = proj / "Logs/harness/screenshots/m2.png"
    r = await b.screenshot(s, out2, camera="Main Camera")
    assert r.status == "pass" and out2.read_bytes() == b"\x89PNGmcp" and r.evidence["moved_from"].startswith(str(proj / "Assets"))
    assert app.mcp.calls[0][1]["camera"] == "Main Camera" and "view_position" not in app.mcp.calls[0][1]
    app.mcp = FakeMCP(proj, write=False)
    out3 = proj / "Logs/harness/screenshots/m3.png"
    r = await b.screenshot(s, out3, view_target="Player")
    assert r.status == "pass" and out3.read_bytes() == b"\x89PNGinline" and r.evidence["from_inline_image"]


@pytest.mark.parametrize("tool,args", [("manage_camera", {"action": "screenshot"}),
                                       ("manage_editor", {"action": "play"}),
                                       ("manage_scene", {"action": "get_hierarchy"}),
                                       ("find_gameobjects", {"search_term": "Player"})])
async def test_mcp_approval_wait_uses_request_timeout(app, proj, tool, args):
    b = bridge(app, open_=True, mcp=(True, ""))
    s = session(app, proj)
    ctx = ToolContext(app=app, session=s, run_id="approval_test", role="subagent")

    async def call(current_ctx, name, params):
        assert current_ctx.session == app.store.get(s["id"])
        response = await app.approvals.ask(s["id"], "mcp_tool", {"subject": name})
        return ToolOutput(response["status"])

    app.mcp = SimpleNamespace(call=call)
    task = asyncio.create_task(b._mcp_out(s, tool, args, None, 0.01, ctx))
    await asyncio.sleep(0.03)
    assert not task.done()  # user hasn't decided yet; the short timeout must not cancel the card
    (card,) = app.approvals.pending(s["id"])
    app.approvals.resolve(card["id"], "approve")
    assert (await task).text == "approved"


async def test_mcp_screenshot_requires_manage_camera_and_handles_disappearing_tool(app, proj):
    b = bridge(app, open_=True, mcp=(True, ""))
    s = session(app, proj)
    app.mcp = FakeMCP(proj)
    app.mcp.conns["unity"].tools = [SimpleNamespace(name="manage_editor")]
    _, problem = await b.screenshot_route(s)
    assert problem.status == "skipped" and "manage_camera" in problem.summary
    out = proj / G.SHOT_DIR / "missing.png"
    r = await b.screenshot(s, out)
    assert r.status == "skipped" and "manage_camera" in r.summary and not app.mcp.calls
    app.mcp.conns["unity"].tools = [SimpleNamespace(name="manage_camera")]

    async def gone(*args):
        raise KeyError("mcp__unity__manage_camera")

    app.mcp.call = gone
    r = await b.screenshot(s, out)
    assert r.status == "skipped" and "no longer exposes manage_camera" in r.summary


async def test_mcp_fallback_removes_only_new_assets_and_sidecars(app, proj):
    b = bridge(app, open_=True, mcp=(True, ""))
    s = session(app, proj)
    keep_dir = proj / "Assets/Logs"
    keep_dir.mkdir()
    keep_meta = proj / "Assets/Logs.meta"
    keep_meta.write_text("keep directory meta")
    old_meta = keep_dir / "harness.meta"
    old_meta.write_text("pre-existing orphan meta")
    app.mcp = FakeMCP(proj, assets=True)
    original = app.mcp.call

    async def with_metas(ctx, name, args):
        result = await original(ctx, name, args)
        d = proj / "Assets" / args["output_folder"]
        png = d / (args["screenshot_file_name"] + ".png")
        Path(str(png) + ".meta").write_text("new image meta")
        Path(str(d) + ".meta").write_text("new folder meta")
        if args["screenshot_file_name"] == "occupied":
            (d / "keep.txt").write_text("another file")
        return result

    app.mcp.call = with_metas
    out = proj / G.SHOT_DIR / "clean.png"
    result = await b.screenshot(s, out)
    assert result.status == "pass" and out.read_bytes() == b"\x89PNGmcp"
    assert keep_dir.is_dir() and keep_meta.read_text() == "keep directory meta"
    assert old_meta.read_text() == "pre-existing orphan meta"
    assert not (keep_dir / "harness").exists()
    # An occupied folder survives, with its sidecar, while the PNG's sidecar is removed.
    result = await b.screenshot(s, proj / G.SHOT_DIR / "occupied.png")
    d = keep_dir / "harness/screenshots"
    assert result.status == "pass" and (d / "keep.txt").read_text() == "another file"
    assert Path(str(d) + ".meta").is_file() and not (d / "occupied.png.meta").exists()


@pytest.mark.parametrize("route", ["mcp", "cli_live", "cli_batch", "raw_batch"])
async def test_screenshot_clamps_dimensions_on_every_route(app, proj, monkeypatch, route):
    b = bridge(app, open_=True, mcp=(True, ""))
    app.mcp = FakeMCP(proj)
    s = session(app, proj)
    seen = []

    async def state(*args, **kw):
        return EditorState(route, True)

    async def batch(session, st, root, out, shot, *args):
        seen.append((shot["width"], shot["height"]))
        out.write_bytes(b"png")
        return BridgeResult("pass", "ok", route)

    async def live(session, root, out, width, height, consent):
        seen.append((width, height))
        out.write_bytes(b"png")
        return BridgeResult("pass", "ok", route)

    monkeypatch.setattr(b, "editor_state", state)
    monkeypatch.setattr(b, "_shot_batch", batch)
    monkeypatch.setattr(b, "_shot_live", live)
    r = await b.screenshot(s, proj / G.SHOT_DIR / "clamp.png", width=-999, height=10**12)
    assert r.status == "pass"
    assert r.evidence["shot"]["width"] == 16 and r.evidence["shot"]["height"] == 8192
    if route == "mcp":
        assert app.mcp.calls[0][1]["max_resolution"] == 8192
    else:
        assert seen == [(16, 8192)]


async def test_bridge_rechecks_plan_mode_for_stale_session_and_context(app, proj):
    b = bridge(app, open_=True, mcp=(True, ""))
    app.mcp = FakeMCP(proj)
    s = session(app, proj)
    ctx = ToolContext(app=app, session=s, run_id="stale")
    app.store.update(s["id"], mode="plan")
    r = await b.screenshot(s, proj / G.SHOT_DIR / "refused.png")
    assert r.status == "error" and "Plan only mode" in r.summary
    r = await b._mcp_out(s, "manage_editor", {"action": "play"}, None, 60, ctx)
    assert r.is_error and "Plan only mode" in r.text and not app.mcp.calls
    b.allow_op(proj, "screenshot")
    refusal = await b.ensure_allowed(s, "screenshot", "screenshot", route="cli_live")
    assert "Plan only mode" in refusal  # an old session snapshot and Always allow cannot bypass the new mode


async def test_cli_live_plain_and_framed(app, proj, fake_cli):
    app.config.unity = {**app.config.unity, "backend": "cli"}
    fake_cli.set(status="ready")
    b = bridge(app, open_=True)
    s = session(app, proj)
    out = proj / "Logs/harness/screenshots/l.png"
    t = asyncio.create_task(b.screenshot(s, out))
    for _ in range(300):
        if cards := app.approvals.pending(s["id"]):
            break
        await asyncio.sleep(0.02)
    (card,) = cards
    assert card["payload"]["op"] == "screenshot" and card["payload"]["route"] == "cli_live"
    app.approvals.resolve(card["id"], "approve")
    r = await t
    assert r.status == "pass" and r.evidence["screenshot"] == str(out) and out.is_file()
    # With framing: the eval card shows the temporary-camera snippet.
    t = asyncio.create_task(b.screenshot(s, proj / "Logs/harness/screenshots/l2.png", cam_pos=[1, 2, 3],
                                         view_target="Player"))
    for _ in range(300):
        if cards := app.approvals.pending(s["id"]):
            break
        await asyncio.sleep(0.02)
    (card,) = cards
    md = card["payload"]["markdown"]
    assert card["payload"]["op"] == "eval" and "HideAndDontSave" in md and "DestroyImmediate(__go)" in md
    app.approvals.resolve(card["id"], "deny")
    r = await t
    assert r.status == "skipped" and "declined" in r.summary


def test_live_shot_code_is_fixed_and_quoted():
    code = live_shot_code(Path('/p/Logs/a "b".png'), width=800, height=600, camera='Cam"; System.IO.File.Delete("x',
                          cam_pos=[1, -0.5, 2], cam_rot=None, fov=35, view_target="Player")
    assert 'new UnityEngine.Vector3(1f, -0.5f, 2f)' in code and "__cam.fieldOfView = 35f;" in code
    assert '"Cam\\"; System.IO.File.Delete(\\"x"' in code  # only ever inside a string literal
    assert '"/p/Logs/a \\"b\\".png"' in code and "LookAt" in code and "SaveScene" not in code
    with pytest.raises(ValueError):
        live_shot_code(Path("/x.png"), fov=0)


# ------------------------------------------------------------------ scene files


def test_scene_reader_on_fixture(proj):
    sc = us.list_scenes(proj)
    assert sc["default"] == "Assets/Scenes/Cave.unity"
    assert [b["path"] for b in sc["build"]] == ["Assets/Scenes/Menu.unity", "Assets/Scenes/Cave.unity"]
    d = us.read_scene(proj, "Assets/Scenes/Cave.unity")
    by = {e["path"]: e for e in d["objects"]}
    assert d["cameras"] == ["Main Camera"] and d["objects"][0]["kind"] == "camera"
    cam = by["Main Camera"]
    assert cam["pos"] == [0.0, 1.0, -10.0] and cam["rot"] == [0.0, 0.0, 0.0] and cam["fov"] == 60.0
    assert by["World/Player"]["pos"] == [16.0, 1.0, 0.0] and by["World/Player"]["rot"] == [0.0, 90.0, 0.0]
    assert by["Directional Light"]["kind"] == "light" and by["Directional Light"]["type"] == "directional"
    assert by["Torch"]["kind"] == "prefab" and by["Torch"]["pos"] == [-4.0, 0.0, 6.0]  # name from the prefab's .meta
    assert by["Torch/Flame"]["pos"] == [-4.0, 1.0, 6.0] and by["Torch/Flame"]["active"] is False
    assert d["bounds"]["max"] == [16.0, 1.0, 6.0]
    q = us.read_scene(proj, "Assets/Scenes/Cave.unity", query="play")
    assert [e["path"] for e in q["objects"]] == ["Main Camera", "World/Player"]  # cameras always listed
    for bad in ("../Cave.unity", "Assets/Scenes/Nope.unity", "/etc/passwd", "Assets/Props/Torch.prefab"):
        with pytest.raises(ValueError):
            us.read_scene(proj, bad)
    with pytest.raises(ValueError, match="Force Text"):
        (proj / "Assets/Scenes/Bin.unity").write_bytes(b"\x00\x01binary")
        us.read_scene(proj, "Assets/Scenes/Bin.unity")
    assert us.look_rotation([0, 0, 0], [0, -1, 1]) == [45.0, 0.0, 0.0]
    assert us.look_rotation([0, 0, 0], [-1, 0, 0]) == [0.0, 270.0, 0.0]
    assert us.look_rotation([0, 1, 0], [0, 2, 1]) == [315.0, 0.0, 0.0]  # looking up = negative pitch


# ------------------------------------------------------------------ the HarnessCli template


def test_harness_v3_has_screenshot_and_v2_is_an_older_version():
    data = (uh.templates_dir() / "HarnessCli.cs").read_text()
    assert uh.version_of(data.encode()) == 3
    assert "public static void Screenshot()" in data and "EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single)" in data
    assert "HideFlags.HideAndDontSave" in data and "EncodeToPNG" in data and "ReadPixels" in data
    assert "SaveScene" not in data and "MarkSceneDirty" not in data
    assert "75c0042c3e2b1e30a9fc70e8c19607c60b4756e2be50cdc7db2a358937ac0379" in uh.PREVIOUS["HarnessCli.cs"]
    assert uh._digest(data.encode()) not in uh.PREVIOUS["HarnessCli.cs"]
    assert data.count("{") == data.count("}")  # a cheap static balance check (no Unity here)
