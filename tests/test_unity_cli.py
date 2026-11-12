"""Unity CLI backend: discovery, argv builders, route resolution (auto | mcp | cli), the runner
(streaming, lock, process-tree kill), result parsing, consent / Plan mode, ladder evidence and the
/api/unity routes. Every `unity` here is tests/fixtures/fake_unity_cli.py in a tmp dir; the real CLI
is never searched for (conftest sets GDW_UNITY_CLI_SEARCH=0)."""
import asyncio
import json
import os
import signal
import stat
import sys
import time
from pathlib import Path

import pytest

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.features import hooks as H
from gamedevworkstation.features import ladder as L
from gamedevworkstation.features import unity_cli as uc
from gamedevworkstation.features import unity_tool as UT
from gamedevworkstation.features.unity_bridge import BridgeResult, UnityBridge

from .conftest import untrusted

FIX = Path(__file__).parent / "fixtures" / "fake_unity_cli.py"
CS_ERR = "Assets/Game/Hit.cs(3,5): error CS1002: ; expected"


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "u.db")
    H.install(a)
    L.install(a)
    UT.install(a)
    return a


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "Game"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")
    (d / "Assets/Game").mkdir(parents=True)
    (d / "Assets/Game/Hit.cs").write_text("class Hit {}\n")
    (d / "Packages").mkdir()
    (d / "Packages/manifest.json").write_text(json.dumps({"dependencies": {}}))
    old = time.time() - 3600
    for p in d.rglob("*"):
        os.utime(p, (old, old))
    return d.resolve()


def write_cli(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable} -I\nimport runpy\nrunpy.run_path({str(FIX)!r}, run_name='__main__')\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class Fake:
    def __init__(self, d: Path, exe: Path):
        self.dir, self.path, self.scn = d, exe, d / "scenario.json"

    def set(self, **kw):
        cur = json.loads(self.scn.read_text())
        cur.update(kw)
        self.scn.write_text(json.dumps(cur))

    def calls(self) -> list[list[str]]:
        f = self.dir / "calls.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def calls_of(self, sub: str) -> list[list[str]]:
        return [c for c in self.calls() if c[:1] == [sub]]


@pytest.fixture
def fake_cli(tmp_path, monkeypatch, app):
    d = tmp_path / "unity_scn"
    d.mkdir()
    (d / "scenario.json").write_text("{}")
    exe = write_cli(tmp_path / "ubin" / "unity")
    monkeypatch.setenv("FAKE_UNITY_SCENARIO", str(d / "scenario.json"))
    app.config.unity = {**(app.config.unity or {}), "cli_path": str(exe), "editor_root": str(tmp_path / "Editors")}
    uc.invalidate_live()
    return Fake(d, exe)


def session(app, folder, mode="ask", **settings):
    s = app.store.create(folder=str(folder), mode=mode)
    if settings:
        s = app.store.update(s["id"], settings=settings)
    return s


def bridge(app, *, open_=False, mcp: tuple[bool, str] = (False, "the unity connector is off for this session")):
    async def probe(p):
        return open_

    b = app.extensions["unity_bridge"] = UnityBridge(app, editor_open=probe)

    async def mcp_ready(s):
        return mcp

    b.mcp_ready = mcp_ready  # type: ignore[method-assign]
    return b


def consent(app, proj):
    return app.extensions["unity_bridge"].consent_for(proj)


# --------------------------------------------------------------- discovery


def test_discovery_config_path_bogus_and_too_old(app, fake_cli):
    st = uc.find_unity_cli(uc.unity_cfg(app))
    assert st.ok and st.info and st.info.version == "1.0.0-beta.13" and st.info.path == fake_cli.path
    assert st.info.has("build", "--timeout") and not st.info.has("recompile", "--nope")
    fake_cli.set(bogus=True)  # a `unity` that isn't the Unity CLI
    uc._PROBE_CACHE.clear()
    st = uc.find_unity_cli(uc.unity_cfg(app))
    assert st.info is None and not st.ok and "doesn't answer like the Unity CLI" in st.reason
    fake_cli.set(bogus=False, version="1.0.0-beta.5")
    uc._PROBE_CACHE.clear()
    st = uc.find_unity_cli(uc.unity_cfg(app))
    assert st.info and not st.ok and "older than 1.0.0-beta.11" in st.reason
    uc._PROBE_CACHE.clear()


def test_discovery_path_and_home_candidates(app, fake_cli, tmp_path, monkeypatch):
    monkeypatch.setenv(uc.SEARCH_ENV, "1")
    cfg = {**uc.unity_cfg(app), "cli_path": ""}
    monkeypatch.setenv("PATH", f"{fake_cli.path.parent}{os.pathsep}/usr/bin:/bin")
    monkeypatch.setattr(uc, "CLI_CANDIDATES", [])
    assert uc.find_unity_cli(cfg).info.path == fake_cli.path
    home = tmp_path / "h"
    exe = write_cli(home / ".unity" / "bin" / "unity")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(uc, "CLI_CANDIDATES", ["~/.unity/bin/unity", str(tmp_path / "Hub/unity")])
    assert uc.find_unity_cli(cfg).info.path == exe
    monkeypatch.setattr(uc, "CLI_CANDIDATES", [])
    st = uc.find_unity_cli(cfg)
    assert st.info is None and "isn't installed" in st.reason


def test_version_order():
    assert uc.version_at_least("1.0.0-beta.13", "1.0.0-beta.11")
    assert not uc.version_at_least("1.0.0-beta.9", "1.0.0-beta.11")
    assert uc.version_at_least("1.0.0", "1.0.0-beta.17") and uc.version_at_least("1.2.0", "1.0.0")


# ------------------------------------------------------------- argv builders


def test_argv_golden(tmp_path):
    cli = uc.UnityCliInfo(Path("/u/unity"), "1.0.0-beta.13")
    P = Path("/p/Game")
    assert uc.argv_status(cli, P) == ["/u/unity", "status", "--project-path", "/p/Game", "--format", "json"]
    assert uc.argv_status(cli, P, 20)[-6:] == ["/p/Game", "--until-ready", "--timeout", "20", "--format", "json"]
    assert uc.argv_recompile(cli, P, 120, strict=True) == ["/u/unity", "recompile", "--project-path", "/p/Game",
                                                           "--timeout", "120", "--strict", "--format", "json"]
    assert uc.argv_run_batch(cli, P, Path("/p/l.log"), 900, ["-nographics"]) == [
        "/u/unity", "run", "/p/Game", "--timeout", "900", "--log-file", "/p/l.log", "--format", "json", "--",
        "-nographics"]
    t = uc.argv_test_batch(cli, P, "editmode", Path("/p/r.xml"), 1800, test_filter="A.B", category="M1",
                           assemblies="Game.Tests")
    assert t == ["/u/unity", "test", "/p/Game", "--mode", "EditMode", "--output", "/p/r.xml", "--timeout", "1800",
                 "--filter", "A.B", "--format", "json", "--", "-testCategory", "M1", "-assemblyNames", "Game.Tests",
                 "-nographics"]
    play = uc.argv_test_batch(cli, P, "playmode", Path("/p/r.xml"), 60)
    assert "-nographics" not in play and "--" not in play and play[4] == "PlayMode"
    assert uc.argv_build(cli, P, profile=None, target="StandaloneOSX", out=Path("/o"), log=Path("/l"), timeout_s=60) == [
        "/u/unity", "build", "/p/Game", "--target", "StandaloneOSX", "--output-path", "/o", "--log-file", "/l",
        "--timeout", "60", "--format", "json"]
    c = uc.argv_command(cli, P, "eval", {"code": "return 1;", "timeout": 5000}, timeout_s=30)
    assert c == ["/u/unity", "command", "eval", "--project-path", "/p/Game", "--timeout", "30", "--format", "json",
                 "--", "--code", "return 1;", "--timeout", "5000"]  # Editor params after the fence
    assert uc.argv_command(cli, P, "test run", {"mode": "editmode"}, detach=True)[2:4] == ["test", "run"]
    assert uc.argv_job(cli, P, "wait", "job-1", 600) == ["/u/unity", "job", "wait", "job-1", "--project-path",
                                                         "/p/Game", "--timeout", "600", "--format", "json"]
    assert uc.argv_close(cli, P) == ["/u/unity", "close", "/p/Game", "--timeout", "30", "--format", "json"]
    assert "--force" not in uc.argv_close(cli, P)
    assert uc.argv_pipeline_install(cli, P, "1.0.0")[-4:] == ["--package-version", "1.0.0", "--format", "json"]
    for bad in (["-quit"], ["-batchmode"], ["-projectPath=/x"], ["-useHub"]):
        with pytest.raises(ValueError):
            uc.argv_run_batch(cli, P, Path("/l"), 10, bad)
    with pytest.raises(ValueError):
        uc.argv_test_batch(cli, P, "editmode", Path("/x"), 10, extra=["-runTests"])
    with pytest.raises(ValueError):
        uc.argv_command(cli, P, "eval; rm", {})
    with pytest.raises(ValueError):
        uc.argv_job(cli, P, "wait", "a b")


# ---------------------------------------------------------------- routes


ROUTE_CASES = [
    # backend, editor open, MCP ready, Pipeline status, CLI found → route
    ("mcp", True, True, "ready", True, "mcp"),
    ("mcp", True, False, "ready", True, "unavailable"),
    ("mcp", False, False, "none", True, "raw_batch"),
    ("cli", True, True, "ready", True, "cli_live"),
    ("cli", True, True, "none", True, "unavailable"),
    ("cli", True, True, "load_pending", True, "unavailable"),
    ("cli", False, True, "none", True, "cli_batch"),
    ("cli", False, True, "none", False, "raw_batch"),
    ("auto", True, True, "ready", True, "mcp"),
    ("auto", True, False, "ready", True, "cli_live"),
    ("auto", True, False, "none", True, "unavailable"),
    ("auto", False, False, "none", True, "cli_batch"),
    ("auto", False, False, "none", False, "raw_batch"),
]


@pytest.mark.parametrize("backend,open_,mcp_ok,live,found,route", ROUTE_CASES)
async def test_route_matrix(app, proj, fake_cli, backend, open_, mcp_ok, live, found, route):
    fake_cli.set(status=live)
    app.config.unity = {**app.config.unity, "backend": backend, "live_wait_s": 1}
    if not found:
        app.config.unity = {**app.config.unity, "cli_path": ""}
    b = bridge(app, open_=open_, mcp=(mcp_ok, "" if mcp_ok else "the unity connector is off for this session"))
    st = await b.editor_state(session(app, proj), "compile")
    assert st.mode == route, st.reason
    assert st.backend == backend and st.backend_source == "global"
    if route == "unavailable" and backend == "mcp":
        assert "MCP bridge isn't reachable" in st.reason


async def test_backend_precedence(app, proj, fake_cli):
    b = bridge(app)
    s = session(app, proj)
    assert b.backend_for(s) == ("auto", "global")
    b.set_project_backend(proj, "cli")
    assert b.backend_for(s) == ("cli", "project")
    s = app.store.update(s["id"], settings={"unity_backend": "mcp"})
    assert b.backend_for(s) == ("mcp", "session")
    b.set_project_backend(proj, None)
    s = app.store.update(s["id"], settings={"unity_backend": None})
    assert b.backend_for(s) == ("auto", "global")
    with pytest.raises(ValueError):
        b.set_project_backend(proj, "nope")


# ----------------------------------------------------------------- compile


async def test_cli_batch_compile_pass_then_fail_under_gate_consent(app, proj, fake_cli):
    b = bridge(app)
    s = session(app, proj)
    fake_cli.set(run={"result": "pass"})
    r = await b.compile(s, consent=consent(app, proj))
    assert r.status == "pass" and r.mode == "cli_batch" and app.approvals.pending() == []
    (run,) = fake_cli.calls_of("run")
    assert run[:4] == ["run", str(proj), "--timeout", "900"] and run[-2:] == ["--", "-nographics"]
    assert Path(r.evidence["log"]).is_file() and r.evidence["log"].startswith(str(proj / "Logs" / "harness"))
    fake_cli.set(run={"result": "fail"})
    r = await b.compile(s, consent=consent(app, proj))
    assert r.status == "fail" and r.errors == 1 and "CS1002" in r.report
    fake_cli.set(run={"result": "multi"})
    assert (await b.compile(s, consent=consent(app, proj))).status == "skipped"


async def test_cli_batch_needs_the_projects_editor_version(app, proj, fake_cli):
    fake_cli.set(editor_version="6000.0.1f1")
    b = bridge(app)
    r = await b.compile(session(app, proj), consent=consent(app, proj))
    assert r.status == "skipped" and "6000.3.21f1" in r.summary and "isn't installed" in r.summary
    assert fake_cli.calls_of("run") == []


async def test_cli_live_compile(app, proj, fake_cli):
    app.config.unity = {**app.config.unity, "backend": "cli"}
    fake_cli.set(status="ready", recompile={"exit": 0})
    b = bridge(app, open_=True)
    s = session(app, proj)
    r = await b.compile(s, consent=consent(app, proj))
    assert r.status == "pass" and r.mode == "cli_live"
    fake_cli.set(recompile={"exit": 6, "errors": [{"file": "Assets/Game/Hit.cs", "line": 3, "column": 5,
                                                   "code": "CS1002", "message": "; expected"}]})
    r = await b.compile(s, consent=consent(app, proj))
    assert r.status == "fail" and r.errors == 1 and "Assets/Game/Hit.cs(3,5)" in r.report and "CS1002" in r.report
    fake_cli.set(recompile={"exit": 7})
    r = await b.compile(s, consent=consent(app, proj))
    assert r.status == "skipped" and "reachable" in r.summary  # cli: no silent reroute


async def test_auto_live_exit7_falls_back_to_mcp(app, proj, fake_cli):
    app.config.unity = {**app.config.unity, "auto_live_order": ["cli_live", "mcp"]}
    fake_cli.set(status="ready", recompile={"exit": 7})
    b = bridge(app, open_=True, mcp=(True, ""))
    hit = []

    async def mcp_compile(s, c):
        hit.append(1)
        return BridgeResult("pass", "0 compile errors", "mcp")

    b._compile_mcp = mcp_compile  # type: ignore[method-assign]
    r = await b.compile(session(app, proj), consent=consent(app, proj))
    assert r.mode == "mcp" and hit == [1] and fake_cli.calls_of("recompile")


async def test_safe_mode_fails_from_editor_log_never_passes(app, proj, fake_cli):
    app.config.unity = {**app.config.unity, "backend": "cli"}
    fake_cli.set(status="none", safe_mode=True)
    b = bridge(app, open_=True)
    s = session(app, proj)
    st = await b.editor_state(s)
    assert st.mode == "unavailable" and st.live["state"] == "safe_mode"
    r = await b.compile(s, consent=consent(app, proj))
    assert r.status == "skipped" and "Safe Mode" in r.summary  # no log: never a pass
    (proj / "Logs").mkdir(exist_ok=True)
    (proj / "Logs/Editor.log").write_text(f"Loading\n{CS_ERR}\n{CS_ERR}\nother noise\n")
    uc.invalidate_live()
    r = await b.compile(s, consent=consent(app, proj))
    assert r.status == "fail" and r.errors == 1 and r.evidence["source"] == "editor_log_safe_mode" and "CS1002" in r.report
    r = await b.run_tests(s, consent=consent(app, proj))
    assert r.status == "skipped" and "Safe Mode" in r.summary


async def test_editor_open_without_pipeline_offers_actions(app, proj, fake_cli):
    (proj / "Packages/manifest.json").write_text(json.dumps({"dependencies": {"com.coplaydev.unity-mcp": "x"}}))
    app.config.unity = {**app.config.unity, "backend": "cli"}
    fake_cli.set(status="none")
    b = bridge(app, open_=True)
    s = session(app, proj)
    st = await b.editor_state(s)
    assert st.mode == "unavailable" and st.actions == ["install_pipeline", "use_mcp_once", "close_editor"]
    assert st.live["state"] == "absent"
    r = await b.compile(s, consent=consent(app, proj))
    assert r.status == "skipped" and fake_cli.calls_of("run") == [] and fake_cli.calls_of("recompile") == []
    # auto picks MCP when it's ready, before any card
    app.config.unity = {**app.config.unity, "backend": "auto"}
    b = bridge(app, open_=True, mcp=(True, ""))
    assert (await b.editor_state(s)).mode == "mcp"


# ------------------------------------------------------------------- tests


async def test_batch_test_outcomes(app, proj, fake_cli):
    b = bridge(app)
    s = session(app, proj)
    c = consent(app, proj)
    fake_cli.set(test={"result": "pass"})
    r = await b.run_tests(s, "editmode", category="M1", consent=c)
    assert r.status == "pass" and r.mode == "cli_batch" and r.evidence["total"] == 2 and Path(r.evidence["xml"]).is_file()
    (t,) = fake_cli.calls_of("test")
    assert t[t.index("--") + 1:] == ["-testCategory", "M1", "-nographics"] and "EditMode" in t
    fake_cli.set(test={"result": "fail"})
    r = await b.run_tests(s, "playmode", consent=consent(app, proj) | {"unity_cli": {"test:playmode"}})
    assert r.status == "fail" and r.evidence["failed_names"] == ["Game.Tests.HitTests.Flash"]
    assert "-nographics" not in fake_cli.calls_of("test")[-1]
    fake_cli.set(test={"result": "timeout"})
    assert (await b.run_tests(s, consent=c)).summary.startswith("the test run timed out")
    fake_cli.set(test={"result": "empty"})
    r = await b.run_tests(s, consent=c)
    assert r.status == "skipped" and "no tests ran" in r.summary
    fake_cli.set(test={"result": "compile_error"})
    r = await b.run_tests(s, consent=c)
    assert r.status == "fail" and r.summary.startswith("tests can't run: 1 compile error")


@pytest.mark.parametrize("catalog,words", [(["run_tests", "eval"], ["run_tests"]), (["test run", "eval"], ["test", "run"])])
async def test_live_tests_detach_and_wait(app, proj, fake_cli, catalog, words):
    app.config.unity = {**app.config.unity, "backend": "cli"}
    fake_cli.set(status="ready", catalog=catalog)
    b = bridge(app, open_=True)
    r = await b.run_tests(session(app, proj), "editmode", test_filter="Hit", consent=consent(app, proj))
    assert r.status == "fail" and r.mode == "cli_live" and r.evidence["total"] == 3
    assert r.evidence["failed_names"] == ["Game.Tests.HitTests.Flash"] and "Expected 0" in r.report
    start = next(c for c in fake_cli.calls_of("command") if "--detach" in c)
    assert start[1:1 + len(words)] == words
    assert start[start.index("--") + 1:] == ["--mode", "editmode", "--filter", "Hit", "--timeout", "900"]
    (wait,) = [c for c in fake_cli.calls_of("job") if c[1] == "wait"]
    assert wait[2] == "job-1"


# ------------------------------------------------------- runner: kill, lock, stream


def _gone(pid: int, wait_s: float = 8.0) -> bool:
    t = time.monotonic() + wait_s
    while time.monotonic() < t:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


async def test_cancel_kills_cli_group_and_batch_grandchild(app, proj, fake_cli):
    fake_cli.set(run={"result": "pass", "hang": 120, "grandchild": True})
    b = bridge(app)
    s = session(app, proj)
    cancel = asyncio.Event()
    task = asyncio.create_task(b.compile(s, consent=consent(app, proj), source="tool", cancel=cancel))
    pidf = fake_cli.dir / "grandchild.pid"
    pid = None
    try:
        for _ in range(200):
            if pidf.exists() and pidf.read_text():
                break
            await asyncio.sleep(0.05)
        pid = int(pidf.read_text())
        assert b.runner.busy.get(str(proj))
        cancel.set()
        r = await asyncio.wait_for(task, 30)
        assert r.status == "skipped" and "cancelled" in r.summary
        assert await asyncio.to_thread(_gone, pid)
        j = app.jobs.list(s["id"])[0]
        assert j["kind"] == "unity" and j["status"] == "cancelled"
        assert not b.runner.busy.get(str(proj))
    finally:
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


async def test_watchdog_timeout_kills_the_tree(app, proj, fake_cli):
    fake_cli.set(run={"result": "pass", "hang": 120, "grandchild": True})
    runner = uc.get_runner(app)
    cli = uc.find_unity_cli(uc.unity_cfg(app)).info
    argv = uc.argv_run_batch(cli, proj, proj / "Logs/x.log", 1, [])
    pid = None
    try:
        run = await runner.run(None, argv, project=proj, label="t", timeout_s=1.5, grace_s=0)
        assert run.timed_out
        pid = int((fake_cli.dir / "grandchild.pid").read_text())
        assert await asyncio.to_thread(_gone, pid)
    finally:
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


async def test_one_unity_job_per_project_and_status_bypasses_the_lock(app, proj, fake_cli):
    runner = uc.get_runner(app)
    slow = [sys.executable, "-c", "import time; time.sleep(0.6)"]
    a, b_ = await asyncio.gather(runner.run(None, slow, project=proj, label="a", timeout_s=10),
                                 runner.run(None, slow, project=proj, label="b", timeout_s=10))
    first, second = sorted([a, b_], key=lambda r: r.started_at)
    assert second.started_at >= first.started_at + first.duration_s - 0.05
    cli = uc.find_unity_cli(uc.unity_cfg(app)).info
    async with runner.lock(proj):  # a job holds the project: status still answers
        st = await asyncio.wait_for(uc.live_state(runner, cli, proj, editor_open=False, use_cache=False), 10)
    assert st.state == "absent"


async def test_stderr_streams_to_the_job_log_before_the_end(app, proj, fake_cli):
    fake_cli.set(test={"result": "pass", "lines": ["L1 opening", "L2 running", "L3 done"], "delay": 0.25})
    seen = []
    orig = app.bus.publish

    def spy(t, data=None, sid=None):
        seen.append((t, dict(data or {})))
        return orig(t, data, sid)

    app.bus.publish = spy  # type: ignore[method-assign]
    b = bridge(app)
    r = await b.run_tests(session(app, proj), consent=consent(app, proj))
    assert r.status == "pass"
    logs = [i for i, (t, d) in enumerate(seen) if t == "job.log" and "L1 opening" in d.get("text", "")]
    done = [i for i, (t, d) in enumerate(seen) if t == "job.updated" and d.get("kind") == "unity"
            and d.get("status") == "done"]
    cmd = [d for t, d in seen if t == "terminal.agent_command"]
    assert logs and done and logs[0] < done[0] and " test " in cmd[0]["command"]
    texts = "".join(d.get("text", "") for t, d in seen if t == "job.log")
    assert texts.index("L1 opening") < texts.index("L2 running") < texts.index("L3 done")


# ------------------------------------------------------------ consent, Plan mode


async def test_tool_ops_ask_and_always_allow(app, proj, fake_cli):
    bridge(app)
    s = session(app, proj)
    t = asyncio.create_task(UT.run_op(app, s, {"op": "build", "target": "StandaloneOSX"}))
    for _ in range(300):
        if app.approvals.pending(s["id"]):
            break
        await asyncio.sleep(0.02)
    (card,) = app.approvals.pending(s["id"])
    assert card["kind"] == "unity" and card["payload"]["op"] == "build" and "unity build" not in card["payload"]["subject"]
    assert "--target" in card["payload"]["markdown"] and "StandaloneOSX" in card["payload"]["markdown"]
    app.approvals.resolve(card["id"], "approve", choice="always")
    out = await t
    assert '"status": "pass"' in out.text and fake_cli.calls_of("build")
    assert "build" in app.extensions["unity_bridge"].allowed_ops(proj)
    out = await UT.run_op(app, s, {"op": "build", "target": "StandaloneOSX"})  # allowlisted: no card
    assert not app.approvals.pending(s["id"]) and not out.is_error


async def test_eval_always_shows_code_and_plan_mode_rules(app, proj, fake_cli):
    app.config.unity = {**app.config.unity, "backend": "cli"}
    fake_cli.set(status="ready")
    bridge(app, open_=True)
    s = session(app, proj)
    t = asyncio.create_task(UT.run_op(app, s, {"op": "eval", "code": "return 1+1;"}))
    for _ in range(300):
        if app.approvals.pending(s["id"]):
            break
        await asyncio.sleep(0.02)
    (card,) = app.approvals.pending(s["id"])
    assert card["kind"] == "unity" and "return 1+1;" in card["payload"]["markdown"]
    app.approvals.resolve(card["id"], "deny")
    out = await t
    assert "declined" in out.text and not [c for c in fake_cli.calls_of("command") if "eval" in c]
    # Plan only mode: no build / eval / exec, but compile and tests run (with the gates' consent).
    plan = session(app, proj, mode="plan")
    for a in ({"op": "eval", "code": "x"}, {"op": "build", "target": "StandaloneOSX"},
              {"op": "exec", "method": "A.B.C"}):
        out = await UT.run_op(app, plan, a)
        assert "Plan only mode" in out.text, a
    H.get_engine(app).enable_preset(proj)
    fake_cli.set(recompile={"exit": 0})
    out = await UT.run_op(app, plan, {"op": "compile"})
    assert '"status": "pass"' in out.text and not app.approvals.pending(plan["id"])
    assert (await UT.run_op(app, plan, {"op": "status"})).text.startswith("Unity backend: cli")


async def test_gate_preset_consent_covers_cli_routes(app, proj, fake_cli):
    bridge(app)
    detail = H.get_engine(app).enable_preset(proj)
    assert {"compile", "test:editmode"} <= set(detail["unity_ops"])
    s = session(app, proj)
    fake_cli.set(run={"result": "fail"})
    r = await H.get_engine(app).run_gate(s, "unity.compile")
    assert r.status == "fail" and app.approvals.pending() == [] and fake_cli.calls_of("run")
    assert "CS1002" in (r.untrusted or "")
    # Consent given before the CLI backend (MCP tools only) still covers the same gate op.
    b = app.extensions["unity_bridge"]
    assert b.cli_consented({"mcp": {"unity__refresh_unity", "unity__read_console"}}, "compile")
    assert not b.cli_consented({"mcp": {"unity__refresh_unity"}}, "compile")
    assert not b.cli_consented({"mcp": {"unity__run_tests", "unity__get_test_job"}}, "compile")


# ------------------------------------------------------------------- evidence


async def test_tool_results_become_ladder_evidence(app, proj, fake_cli):
    bridge(app)
    H.get_engine(app).enable_preset(proj)
    s = session(app, proj)
    fake_cli.set(run={"result": "pass"}, test={"result": "pass"})
    out = await UT.run_op(app, s, {"op": "compile"})
    assert not out.is_error
    lad = app.extensions["ladder"]
    (l1,) = lad.evidence(proj, levels=["L1"])
    assert l1["status"] == "pass" and l1["observed"] == "tool" and l1["source"] == "unity:compile:cli_batch"
    job = app.jobs.list(s["id"])[0]
    assert abs(l1["ts"] - job["started_at"]) < 2 and l1["ts"] <= job["ended_at"]
    await UT.run_op(app, s, {"op": "test"})
    (l2,) = lad.evidence(proj, levels=["L2"])
    assert l2["status"] == "pass" and l2["path"].endswith(".xml") and l2["subjects"] == ["M1-S01"]
    assert l2["detail"]["route"] == "cli_batch"


async def test_agent_typed_unity_test_is_rechecked_from_the_xml(app, proj):
    s = session(app, proj)
    ctx = ToolContext(app=app, session=s, run_id="r")
    lad = app.extensions["ladder"]
    xml = proj / "Logs/r.xml"
    xml.parent.mkdir(exist_ok=True)
    xml.write_text('<test-run total="2" passed="1" failed="1"><test-case fullname="A.B" result="Passed"/>'
                   '<test-case fullname="A.C" result="Failed"/></test-run>')
    specs = lad._from_command(ctx, "unity test . --mode EditMode --output Logs/r.xml", "exit code 8\nPASSED all")
    assert [(x["level"], x["status"], x["source"]) for x in specs] == [("L2", "fail", "cmd:unity test")]
    env = json.dumps({"success": True, "command": "recompile", "data": {"errors": []}})
    specs = lad._from_command(ctx, f"unity recompile --project-path {proj} --format json", f"exit code 0\n{env}")
    assert [(x["level"], x["status"]) for x in specs] == [("L1", "pass")]
    specs = lad._from_command(ctx, "unity recompile --format json", "exit code 7\n{}")
    assert specs == []  # no Editor reachable: no evidence either way
    assert lad._from_command(ctx, "echo unity test --output Logs/r.xml", "exit code 0\n") == []


# ---------------------------------------------------------------------- API


def test_api_state_backend_and_cancel(tmp_path, proj, fake_cli, monkeypatch):
    from fastapi.testclient import TestClient

    from gamedevworkstation.server import create_app

    st = AppState(db_path=tmp_path / "api.db")
    st.config.unity = {"cli_path": str(fake_cli.path), "editor_root": str(tmp_path / "Editors")}
    h = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", st)) as c:
        bridge(st)
        s = st.store.create(folder=str(proj), mode="ask")
        r = c.get("/api/unity/state", params={"session_id": s["id"]}, headers=h).json()
        assert r["unity_project"] and r["route"] == "cli_batch" and r["routes"]["build"] == "cli_batch"
        assert r["routes"]["eval"] == "unavailable" and r["cli"]["version"] == "1.0.0-beta.13"
        assert r["backend"] == "auto" and r["backend_source"] == "global" and r["session_backend"] is None
        r = c.put("/api/unity/backend", json={"session_id": s["id"], "scope": "project", "backend": "mcp"}, headers=h).json()
        assert r["backend"] == "mcp" and r["backend_source"] == "project" and r["route"] == "raw_batch"
        r = c.put("/api/unity/backend", json={"session_id": s["id"], "scope": "session", "backend": "cli"}, headers=h).json()
        assert r["backend"] == "cli" and r["backend_source"] == "session" and r["project_backend"] == "mcp"
        assert c.put("/api/unity/backend", json={"session_id": s["id"], "backend": "x"}, headers=h).status_code == 400
        info = c.get("/api/unity/info", headers=h).json()
        assert info["editors"][0]["version"] == "6000.3.21f1" and info["config"]["backend"] == "auto"
        assert c.get("/api/hooks/unity", params={"session_id": s["id"]}, headers=h).json()["route"] == "cli_batch"
        assert c.post("/api/unity/jobs/nope/cancel", headers=h).status_code == 404
        r = c.patch("/api/settings", json={"unity": {"backend": "cli"}}, headers=h)
        assert r.status_code == 200 and r.json()["unity"]["backend"] == "cli"
        assert c.patch("/api/settings", json={"unity": {"backend": "both"}}, headers=h).status_code == 400
        assert "unity" in {t.name for t in st.runner.tool_specs(st.store.get(s["id"]))}


# ------------------------------------------------------------- review fixes


async def test_tool_raw_batch_route_reads_unity_sh_stdout(app, proj, tmp_path, monkeypatch):
    """The unity tool on the unity.sh route (mcp backend, Editor closed) runs it as a Unity job in a
    login shell, with stdout (RESULT / FAILED lines) streamed and parsed."""
    bindir = tmp_path / "shbin"
    bindir.mkdir()
    sh = bindir / "unity.sh"
    sh.write_text('#!/bin/bash\nif [ "$1" = "test" ]; then echo "FAILED Game.Tests.HitTests.Flash :: boom"\n'
                  'echo "tests: total=3 passed=2 failed=1"; echo "RESULT: FAIL tests EditMode total=3 failed=1"; exit 2; fi\n'
                  'echo "RESULT: OK compile 0 errors"; exit 0\n')
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr("gamedevworkstation.services.default_shell", lambda: "/bin/bash")
    app.config.unity = {**(app.config.unity or {}), "backend": "mcp"}
    bridge(app)
    H.get_engine(app).enable_preset(proj)
    s = session(app, proj)
    out = await UT.run_op(app, s, {"op": "compile"})
    assert '"status": "pass"' in out.text and '"route": "raw_batch"' in out.text
    out = await UT.run_op(app, s, {"op": "test"})
    assert '"status": "fail"' in out.text and "Game.Tests.HitTests.Flash" in out.text
    assert all(j["kind"] == "unity" for j in app.jobs.list(s["id"]))


def test_live_job_result_needs_a_complete_run():
    ok = uc.CliRun(0, {"success": True, "data": {"result": {"Summary": {"Total": 2, "Passed": 2, "Failed": 0}}}})
    assert uc.result_from_job(ok, "editmode").status == "pass"
    partial = uc.CliRun(6, {"success": False, "data": {"state": "running", "summary": {"total": 50, "passed": 12,
                                                                                      "failed": 0}}})
    assert uc.result_from_job(partial, "editmode").status == "skipped"
    short = uc.CliRun(0, {"success": True, "data": {"summary": {"total": 5, "passed": 3, "failed": 0}}})
    assert uc.result_from_job(short, "editmode").status == "skipped"
    hidden = uc.CliRun(0, {"success": True, "data": {"summary": {"total": 2, "passed": 2, "failed": 0},
                                                     "results": [{"fullName": "A.B", "status": "Failed"}]}})
    assert uc.result_from_job(hidden, "editmode").status == "fail"


def test_read_commands_are_an_explicit_list():
    op_class = UnityBridge.op_class
    assert op_class("command", "editor_status") == "read" and op_class("command", "test status") == "read"
    for n in ("set_status", "find_and_delete_missing", "get_or_create_x", "editor_play", "eval"):
        assert op_class("command", n) == "change", n
    assert op_class("compile") == "verify" and op_class("eval") == "code" and op_class("close_editor") == "setup"
