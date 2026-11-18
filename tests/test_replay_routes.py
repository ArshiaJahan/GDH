"""Tests for the replay REST routes (POST /api/sessions/{sid}/replays/*) using FakeUnityBridge.
Regressions: jobs always finish (M1), stop/status reject non-contract run ids (L1), validation
answers 400 before a job exists (M7) and render needs capture + change permission (H2)."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.features import hooks as H
from gamedevworkstation.features import ladder as L
from gamedevworkstation.features import unity_tool as UT
from gamedevworkstation.features.unity_bridge import BridgeResult, FakeUnityBridge

GOLDEN = Path(__file__).parent / "fixtures" / "replay" / "golden_v1.gdwreplay"
RUN_ID = "rr-test0001"
REL_ARCHIVE = f"Logs/harness/replay/{RUN_ID}/run.gdwreplay"


@pytest.fixture
def appstate(tmp_path):
    a = AppState(db_path=tmp_path / "u.db")
    H.install(a)
    L.install(a)
    UT.install(a)
    return a


@pytest.fixture
def app(appstate):
    """A FastAPI test app with replay routes registered."""
    fastapi_app, api = FastAPI(), APIRouter()
    from gamedevworkstation.features import replay
    replay.register(fastapi_app, api, appstate)
    fastapi_app.include_router(api)
    fastapi_app.state.app = appstate
    return fastapi_app


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "Game"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")
    (d / "Assets/Game").mkdir(parents=True)
    (d / "Assets/Game/Hit.cs").write_text("class Hit {}\n")
    (d / "Packages").mkdir()
    (d / "Packages/manifest.json").write_text(json.dumps({"dependencies": {}}))
    return d.resolve()


@pytest.fixture
def archive(proj):
    dest = proj / REL_ARCHIVE
    dest.parent.mkdir(parents=True)
    shutil.copyfile(GOLDEN, dest)
    return dest


@pytest.fixture
def client(app, appstate, proj, archive):
    appstate.extensions["unity_bridge"] = FakeUnityBridge(appstate)
    sid = appstate.store.create(folder=str(proj), mode="ask")["id"]
    return TestClient(app), sid


def wait_job(appstate: AppState, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = appstate.jobs.get(job_id)
        if job and job.get("status") != "running":
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: {appstate.jobs.get(job_id)}")


class TestRecordRoute:
    def test_record_returns_202_and_finishes(self, client, appstate):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/record", json={})
        assert r.status_code == 202, r.text
        body = r.json()
        assert "job_id" in body
        assert "run_id" in body
        assert body["run_id"].startswith("rr_")
        assert "status_url" in body
        job = wait_job(appstate, body["job_id"])
        assert job["status"] == "done"

    def test_record_refused_no_session(self, client):
        c, _ = client
        r = c.post("/api/sessions/nonexistent/replays/record", json={})
        assert r.status_code == 404

    def test_record_refused_in_plan_mode(self, appstate, app, proj):
        appstate.extensions["unity_bridge"] = FakeUnityBridge(appstate)
        sid = appstate.store.create(folder=str(proj), mode="plan")["id"]
        c = TestClient(app)
        r = c.post(f"/api/sessions/{sid}/replays/record", json={})
        assert r.status_code == 403

    def test_record_rejects_replay_path(self, client):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/record", json={"replay_path": REL_ARCHIVE})
        assert r.status_code == 400
        assert "replay_path" in r.text.lower()


class TestReplayRoute:
    def test_replay_returns_202(self, client, appstate, proj):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/replay",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["run_id"] == RUN_ID
        assert wait_job(appstate, body["job_id"])["status"] == "done"

    def test_replay_writes_full_report(self, client, appstate, proj):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/replay",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        wait_job(appstate, r.json()["job_id"])
        report = json.loads((proj / "Logs/harness/replay" / RUN_ID / "report.json").read_text())
        assert report["schema"] == "gdw.replay.report/1"
        assert report["status"] == "pass"
        assert report["frames"]["expected"] == report["frames"]["compared"]
        assert report["replay_sha256"]
        assert report["request_digest"]
        assert report["environment"] in ("matched", "differs")
        if report["environment"] == "differs":
            assert report["environment_diff"] == sorted(report["environment_diff"])

    def test_replay_requires_path(self, client):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/replay", json={"run_id": RUN_ID})
        # replay_path defaults per contract §1, but the archive must exist to run.
        assert r.status_code == 202

    def test_replay_refused_in_plan_mode(self, appstate, app, proj, archive):
        appstate.extensions["unity_bridge"] = FakeUnityBridge(appstate)
        sid = appstate.store.create(folder=str(proj), mode="plan")["id"]
        c = TestClient(app)
        r = c.post(f"/api/sessions/{sid}/replays/replay",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.status_code == 403


class TestVerifyRoute:
    def test_verify_returns_202(self, client, appstate):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/verify",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.status_code == 202, r.text
        assert wait_job(appstate, r.json()["job_id"])["status"] == "done"

    def test_verify_allowed_in_plan_mode_without_capture(self, appstate, app, proj, archive):
        appstate.extensions["unity_bridge"] = FakeUnityBridge(appstate)
        sid = appstate.store.create(folder=str(proj), mode="plan")["id"]
        c = TestClient(app)
        r = c.post(f"/api/sessions/{sid}/replays/verify",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.status_code == 202, r.text


class TestRenderRoute:
    def test_render_returns_202(self, client, appstate):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/render",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID,
                         "capture": {"formats": ["mp4"]}})
        assert r.status_code == 202, r.text
        assert wait_job(appstate, r.json()["job_id"])["status"] == "done"

    def test_render_requires_capture(self, client):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/render",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.status_code == 400
        assert "capture" in r.text.lower()

    def test_render_refused_in_plan_mode(self, appstate, app, proj, archive):
        appstate.extensions["unity_bridge"] = FakeUnityBridge(appstate)
        sid = appstate.store.create(folder=str(proj), mode="plan")["id"]
        c = TestClient(app)
        r = c.post(f"/api/sessions/{sid}/replays/render",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID,
                         "capture": {"formats": ["mp4"]}})
        assert r.status_code == 403


class TestJobsAlwaysFinish:
    def test_exception_marks_job_failed(self, app, appstate, proj, archive):
        class Boom(FakeUnityBridge):
            async def run_replay(self, session, op, request, **kw):
                raise RuntimeError("boom")

        appstate.extensions["unity_bridge"] = Boom(appstate)
        sid = appstate.store.create(folder=str(proj), mode="ask")["id"]
        c = TestClient(app)
        r = c.post(f"/api/sessions/{sid}/replays/replay",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.status_code == 202
        job = wait_job(appstate, r.json()["job_id"])
        assert job["status"] == "failed"
        assert "boom" in json.dumps(job)


class TestStopRoute:
    def test_stop_unknown_run(self, client):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/rr-unknown1/stop")
        assert r.status_code == 404

    def test_stop_invalid_run_id(self, client):
        """L1: a run id that can't match the contract pattern is a 404, never a path probe."""
        c, sid = client
        for bad in ("unknown", "..", "a"):
            r = c.post(f"/api/sessions/{sid}/replays/{bad}/stop")
            assert r.status_code == 404, bad


class TestStatusRoute:
    def test_status_unknown_run(self, client):
        c, sid = client
        r = c.get(f"/api/sessions/{sid}/replays/rr-unknown1")
        assert r.status_code == 404

    def test_status_invalid_run_id(self, client):
        c, sid = client
        r = c.get(f"/api/sessions/{sid}/replays/unknown")
        assert r.status_code == 404

    def test_status_returns_report(self, client, appstate, proj):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/replay",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        wait_job(appstate, r.json()["job_id"])
        st = c.get(f"/api/sessions/{sid}/replays/{RUN_ID}")
        assert st.status_code == 200
        assert st.json()["report"]["schema"] == "gdw.replay.report/1"
        assert st.json()["archive"]["size"] > 0


class TestReportIsNeverOverwritten:
    def test_unity_report_survives(self, client, appstate, proj):
        run_dir = proj / "Logs/harness/replay" / RUN_ID
        run_dir.mkdir(parents=True, exist_ok=True)
        own = {"schema": "gdw.replay.report/1", "run_id": RUN_ID, "status": "pass",
               "message": "written by the Unity package"}
        (run_dir / "report.json").write_text(json.dumps(own))
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/replay",
                   json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        wait_job(appstate, r.json()["job_id"])
        assert json.loads((run_dir / "report.json").read_text()) == own


class TestBadArgs:
    def test_bad_run_id(self, client):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/record", json={"run_id": "bad"})
        assert r.status_code == 400
        assert "run_id" in r.text.lower()

    def test_bad_seed(self, client):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/record", json={"seed": -1})
        assert r.status_code == 400

    def test_bad_fixed_dt(self, client):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/record", json={"fixed_dt": -0.1})
        assert r.status_code == 400

    def test_absolute_replay_path(self, client):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/replay",
                   json={"replay_path": "/tmp/run.gdwreplay", "run_id": RUN_ID})
        assert r.status_code == 400

    def test_wrong_extension(self, client):
        c, sid = client
        r = c.post(f"/api/sessions/{sid}/replays/replay",
                   json={"replay_path": "Logs/harness/replay/x/run.zip", "run_id": RUN_ID})
        assert r.status_code == 400


class TestJobCancelled:
    def test_cancelled_run_finishes_job_as_cancelled(self, app, appstate, proj, archive):
        import asyncio

        class Slow(FakeUnityBridge):
            async def run_replay(self, session, op, request, **kw):
                await asyncio.sleep(30)

        appstate.extensions["unity_bridge"] = Slow(appstate)
        sid = appstate.store.create(folder=str(proj), mode="ask")["id"]
        c = TestClient(app)
        r = c.post(f"/api/sessions/{sid}/replays/replay", json={"replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        job_id = r.json()["job_id"]
        time.sleep(0.2)
        s = c.post(f"/api/sessions/{sid}/replays/{RUN_ID}/stop")
        assert s.status_code == 200 and s.json()["status"] == "stopped"
        assert wait_job(appstate, job_id)["status"] == "cancelled"
