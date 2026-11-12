import time

import pytest
from fastapi.testclient import TestClient

from workspace.app import AppState
from workspace.providers.fake import FakeProvider, text_response
from workspace.server import create_app

H = {"Authorization": "Bearer t"}


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "t.db")
    fake = FakeProvider()
    fake.script = [text_response("Daily summary: all good.")]
    s.providers.override("anthropic", "default", fake)
    with TestClient(create_app("t", s)) as c:
        yield c, s, fake


def test_create_schedule_and_run_now(env):
    c, s, fake = env
    t = c.post("/api/tasks", json={"name": "Morning digest", "prompt": "Summarize yesterday.", "schedule": "30 8 * * 1-5",
                                   "model": "claude.fast", "effort": "low", "mode": "plan"}, headers=H).json()
    assert t["model"] == "claude-haiku-5-5"
    listed = c.get("/api/tasks", headers=H).json()
    assert listed["scheduler_running"] and listed["tasks"][0]["next_run"] > time.time()
    sid = c.post(f"/api/tasks/{t['id']}/run", headers=H).json()["session_id"]
    for _ in range(100):
        runs = c.get("/api/tasks", headers=H).json()["tasks"][0]["runs"]
        if runs and runs[0]["status"] != "running":
            break
        time.sleep(0.05)
    assert runs[0]["status"] == "done" and runs[0]["session_id"] == sid
    sess = c.get(f"/api/sessions/{sid}", headers=H).json()
    assert sess["model"] == "claude-haiku-5-5" and sess["effort"] == "low" and sess["mode"] == "plan"
    assert fake.calls[0].messages[0].text() == "Summarize yesterday."
    # Disable → no next run.
    c.patch(f"/api/tasks/{t['id']}", json={"enabled": False}, headers=H)
    assert c.get("/api/tasks", headers=H).json()["tasks"][0]["next_run"] is None


def test_validation(env):
    c, s, _ = env
    assert c.post("/api/tasks", json={"name": "x", "prompt": "y", "schedule": "not cron"}, headers=H).status_code == 400
    assert c.post("/api/tasks", json={"name": "x", "prompt": "y", "schedule": "0 9 * * *", "effort": "max"}, headers=H).status_code == 400
    assert c.post("/api/tasks", json={"name": "x", "prompt": "y", "schedule": "every:30m"}, headers=H).status_code == 200
    assert c.post("/api/tasks", json={"name": "x", "prompt": "y", "schedule": "once:2030-01-01T09:00"}, headers=H).status_code == 200
