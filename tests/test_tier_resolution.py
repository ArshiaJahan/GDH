"""Tier keys (claude.fast, codex.standard, ...) are resolved to model ids wherever a session's model is stored or used."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from workspace.app import AppState
from workspace.providers.fake import FakeProvider, text_response
from workspace.server import create_app

from .test_harnesses import fake_codex  # noqa: F401  (fixture)

H = {"Authorization": "Bearer t"}


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "t.db")
    fake = FakeProvider()
    s.providers.override("anthropic", "default", fake)
    with TestClient(create_app("t", s)) as c:
        yield c, s, fake


def wait_idle(c, sid):
    for _ in range(200):
        if not c.get(f"/api/sessions/{sid}", headers=H).json()["running"]:
            return
        time.sleep(0.03)
    raise TimeoutError


def test_store_create_and_update_resolve_tier(env):
    _, s, _ = env
    sess = s.store.create(model="claude.fast")
    assert sess["model"] == "claude-haiku-5-5"
    assert s.store.update(sess["id"], model="codex.standard")["model"] == "gpt-6.1-sol"


def test_scheduled_task_with_tier_key_stores_model_id(env):
    c, s, fake = env
    fake.script = [text_response("ok")]
    t = c.post("/api/tasks", json={"name": "n", "prompt": "p", "schedule": "0 9 * * *"}, headers=H).json()
    s.db.execute("UPDATE scheduled_tasks SET model='claude.standard' WHERE id=?", [t["id"]])  # an older row
    sid = c.post(f"/api/tasks/{t['id']}/run", headers=H).json()["session_id"]
    assert s.store.get(sid)["model"] == "claude-sonnet-5-5"


def test_main_loop_resolves_stored_tier_key(env):
    c, s, fake = env
    fake.script = [text_response("hi")]
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    s.db.execute("UPDATE sessions SET model='claude.standard' WHERE id=?", [sid])  # bypasses the store
    c.post(f"/api/sessions/{sid}/messages", json={"text": "hello"}, headers=H)
    wait_idle(c, sid)
    assert fake.calls[0].model == "claude-sonnet-5-5"


def test_codex_cli_resolves_stored_tier_key(env, fake_codex, tmp_path):  # noqa: F811
    c, s, _ = env
    folder = tmp_path / "proj"
    folder.mkdir()
    s.config.modes["allowlist"] = ["codex_cli:*"]  # Accept edits asks for each Codex CLI turn otherwise
    sid = c.post("/api/sessions", json={"folder": str(folder), "mode": "accept_edits"}, headers=H).json()["id"]
    assert c.patch(f"/api/sessions/{sid}", json={"harness": "codex_cli"}, headers=H).status_code == 200
    s.db.execute("UPDATE sessions SET model='codex.fast' WHERE id=?", [sid])  # bypasses the store
    c.post(f"/api/sessions/{sid}/messages", json={"text": "write a file"}, headers=H)
    wait_idle(c, sid)
    a = json.loads(fake_codex.read_text().splitlines()[0])["args"]
    assert a[a.index("-m") + 1] == "gpt-6.1-terra"


def test_startup_rewrites_tier_keys(tmp_path):
    s = AppState(db_path=tmp_path / "t.db")
    a, b = s.store.create(), s.store.create()
    s.db.execute("UPDATE sessions SET model='codex.standard' WHERE id=?", [a["id"]])
    s.db.execute("UPDATE sessions SET model='claude.deep' WHERE id=?", [b["id"]])
    s.on_startup()
    assert s.store.get(a["id"])["model"] == "gpt-6.1-sol"
    assert s.store.get(b["id"])["model"] == "claude-opus-5-5"
