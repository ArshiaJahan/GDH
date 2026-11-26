"""Prefab preview rendering: the Prefabs tab route (fake bridge) and the bridge's routing (Unity stubbed out)."""
import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.server import create_app
from gamedevworkstation.features import unity_bridge as ub
from gamedevworkstation.features.unity_bridge import BridgeResult, EditorState, FakeUnityBridge, UnityBridge

H = {"Authorization": "Bearer t"}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Game"
    write(root / "ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.3.21f1\n")
    write(root / "Assets/A.prefab", "%YAML 1.1\n")
    write(root / "Assets/A.prefab.meta", "fileFormatVersion: 2\nguid: " + "a" * 32 + "\n")
    return root


def wait_done(client, url):
    for _ in range(100):
        status = client.get(url + "/previews/status").json()
        if not status["running"]:
            return status
        time.sleep(0.02)
    raise AssertionError("render never finished")


def test_route_runs_the_bridge_in_the_background(project, tmp_path):
    state = AppState(db_path=tmp_path / "x.db")
    fake = state.extensions["unity_bridge"] = FakeUnityBridge(state, previews=[BridgeResult(
        "pass", "4 previews rendered, 1 unchanged", "raw_batch", evidence={"counts": {"rendered": 4, "skipped": 1}})])
    session = state.store.create(folder=str(project))
    url = f"/api/sessions/{session['id']}/prefabs"
    with TestClient(create_app("t", state), headers=H) as client:
        assert client.get(url + "/previews/status").json() == {"running": False, "result": None}
        started = client.post(url + "/previews", json={"force": True}).json()
        assert started["running"] is True and "task" not in started
        done = wait_done(client, url)
    assert done["result"]["status"] == "pass" and done["result"]["counts"] == {"rendered": 4, "skipped": 1}
    call = fake.preview_calls[0]
    assert call["out"] == str(project.resolve() / ".gdw" / "prefab-previews") and call["force"] is True
    assert call["size"] == 128


def test_route_needs_a_session_in_the_project_folder(project, tmp_path):
    state = AppState(db_path=tmp_path / "x.db")
    state.extensions["unity_bridge"] = FakeUnityBridge(state)
    session = state.store.create(folder=str(tmp_path))  # the project is a subfolder
    with TestClient(create_app("t", state), headers=H) as client:
        r = client.post(f"/api/sessions/{session['id']}/prefabs/previews", json={})
    assert r.status_code == 400 and "Unity project folder" in r.json()["detail"]


def test_route_reports_bridge_errors(project, tmp_path):
    state = AppState(db_path=tmp_path / "x.db")
    bridge = state.extensions["unity_bridge"] = FakeUnityBridge(state)

    async def boom(*a, **k):
        raise RuntimeError("unity exploded")

    bridge.prefab_previews = boom
    session = state.store.create(folder=str(project))
    url = f"/api/sessions/{session['id']}/prefabs"
    with TestClient(create_app("t", state), headers=H) as client:
        client.post(url + "/previews", json={})
        done = wait_done(client, url)
    assert done["result"] == {"status": "error", "summary": "unity exploded", "counts": {}, "actions": []}


class Stub(UnityBridge):
    """The real prefab_previews with the route, harness check and Unity runs stubbed."""

    def __init__(self, app, mode, *, harness=None, editor_open=False):
        super().__init__(app)
        self.mode, self.harness, self.open_ = mode, harness, editor_open
        self.raw_args, self.evals = [], []

    async def _route(self, session, op):
        assert op == "previews"
        return EditorState(self.mode, True, self.open_), Path(session["folder"]).resolve()

    async def _needs_harness(self, root, what, mode, *, min_version=1):
        assert min_version == 4
        return self.harness

    @staticmethod
    def unity_sh():
        return Path("/x/unity.sh")

    async def _raw(self, session, op, args, consent, **kw):
        self.raw_args.append(args)
        return 0, "", "RESULT: OK previews rendered=3 skipped=2 empty=1 failed=0 size=128 out=/x", "", 0.0

    async def editor_command(self, session, name, params=None, **kw):
        self.evals.append((name, params, kw))
        return BridgeResult("pass", "eval ok", "cli_live", report='"PREVIEWS OK rendered=1 skipped=0 empty=0 failed=1"')


def run(coro):
    return asyncio.run(coro)


def test_batch_route_runs_unity_sh_previews(project, tmp_path):
    state = AppState(db_path=tmp_path / "x.db")
    session = state.store.create(folder=str(project))
    b = Stub(state, "raw_batch")
    out = project.resolve() / ".gdw" / "prefab-previews"
    r = run(b.prefab_previews(session, out, size=4000, force=True))
    assert b.raw_args == [["previews", "--out", str(out), "--size", "1024", "--force"]]
    assert r.status == "pass" and r.summary == "3 previews rendered, 2 unchanged, 1 with nothing to show"
    assert r.evidence["counts"] == {"rendered": 3, "skipped": 2, "empty": 1, "failed": 0}


def test_live_route_evals_the_renderer(project, tmp_path):
    state = AppState(db_path=tmp_path / "x.db")
    session = state.store.create(folder=str(project))
    b = Stub(state, "cli_live", editor_open=True)
    out = project.resolve() / ".gdw" / "prefab-previews"
    r = run(b.prefab_previews(session, out))
    name, params, kw = b.evals[0]
    assert name == "eval" and kw["op"] == "previews" and kw["code"] == params["code"]
    assert params["code"] == f'return Harness.Headless.HarnessCli.RenderPrefabPreviews("{out}", 128, false);'
    assert r.summary == "1 previews rendered, 0 unchanged, 1 failed"


def test_mcp_only_points_to_the_menu_item_and_harness_is_required(project, tmp_path):
    state = AppState(db_path=tmp_path / "x.db")
    session = state.store.create(folder=str(project))
    out = project.resolve() / ".gdw" / "prefab-previews"
    r = run(Stub(state, "mcp", editor_open=True).prefab_previews(session, out))
    assert r.status == "skipped" and ub.PREVIEWS_MENU in r.summary and r.evidence["menu"] == ub.PREVIEWS_MENU
    need = BridgeResult("skipped", "needs_harness: …", "raw_batch", evidence={"actions": ["install_harness"]})
    r = run(Stub(state, "raw_batch", harness=need).prefab_previews(session, out))
    assert r is need
    r = run(Stub(state, "raw_batch").prefab_previews(session, project / "Assets" / "x"))
    assert r.status == "error" and ".gdw" in r.summary


def test_plan_mode_refuses(project, tmp_path):
    state = AppState(db_path=tmp_path / "x.db")
    session = state.store.create(folder=str(project))
    state.store.update(session["id"], mode="plan")
    r = run(Stub(state, "raw_batch").prefab_previews(session, project / ".gdw" / "prefab-previews"))
    assert r.status == "error" and "Plan only" in r.summary


def test_status_says_when_the_unity_card_waits(project, tmp_path):
    state = AppState(db_path=tmp_path / "x.db")
    bridge = state.extensions["unity_bridge"] = FakeUnityBridge(state)

    async def asks(session, out, **kw):
        res = await state.approvals.ask(session["id"], "unity", {"subject": "Unity previews", "op": "previews",
                                                                 "markdown": "", "buttons": []})
        return BridgeResult("pass" if res.get("status") == "approved" else "skipped", "declined", "raw_batch")

    bridge.prefab_previews = asks
    session = state.store.create(folder=str(project))
    url = f"/api/sessions/{session['id']}/prefabs"
    with TestClient(create_app("t", state), headers=H) as client:
        client.post(url + "/previews", json={})
        for _ in range(100):
            status = client.get(url + "/previews/status").json()
            if status.get("waiting_approval"):
                break
            time.sleep(0.02)
        assert status["running"] and status["waiting_approval"] is True
        card = client.get("/api/approvals", params={"session_id": session["id"]}).json()[0]
        client.post(f"/api/approvals/{card['id']}", json={"decision": "deny"})
        done = wait_done(client, url)
    assert done["waiting_approval"] is False and done["result"]["status"] == "skipped"
