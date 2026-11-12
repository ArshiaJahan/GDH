"""Fixes from the UI smoke test: dev-safe key storage under GDW_NO_KEYCHAIN=1, the default
skill set in /api/state, 404 for missing /assets/* chunks, the Stop notice and reusable storage."""
import stat

import keyring
import pytest
from fastapi.testclient import TestClient

from gamedevworkstation import config as config_mod
from gamedevworkstation.app import AppState
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}


@pytest.fixture
def no_keyring(monkeypatch):
    """Any keyring call fails the test: with the flag set the real Keychain must never be touched."""
    calls = []

    def boom(*a, **k):
        calls.append(a)
        raise AssertionError("keyring must not be called with GDW_NO_KEYCHAIN=1")

    for fn in ("set_password", "get_password", "delete_password"):
        monkeypatch.setattr(keyring, fn, boom)
    return calls


def test_keys_round_trip_without_the_keychain(no_keyring):
    assert config_mod.get_key("openai", "work") is None
    config_mod.set_key("openai", "work", "sk-dev-key-dummy")
    assert config_mod.get_key("openai", "work") == "sk-dev-key-dummy"
    p = config_mod._dev_keys_path()
    assert p.parent == config_mod.data_dir() and stat.S_IMODE(p.stat().st_mode) == 0o600
    config_mod.set_key("anthropic", "default", "sk-ant-dummy-key")
    config_mod.delete_key("openai", "work")
    assert config_mod.get_key("openai", "work") is None
    assert config_mod.get_key("anthropic", "default") == "sk-ant-dummy-key"
    assert no_keyring == []


def test_saving_a_key_in_the_ui_sticks_in_dev(tmp_path, no_keyring, monkeypatch):
    from gamedevworkstation.features.status import StatusChecker

    async def no_check(self, only=None):
        return []

    monkeypatch.setattr(StatusChecker, "check_all", no_check)
    with TestClient(create_app("t", AppState(db_path=tmp_path / "k.db"))) as c:
        r = c.post("/api/settings/keys", json={"provider": "openai", "profile": "default", "key": "sk-ui-key-dummy"},
                   headers=H)
        assert r.status_code == 200, r.text
        assert config_mod.get_key("openai") == "sk-ui-key-dummy"
        assert c.delete("/api/settings/keys/openai/default", headers=H).status_code == 200
        assert config_mod.get_key("openai") is None
    assert no_keyring == []


def test_state_reports_the_default_skills(tmp_path):
    s = AppState(db_path=tmp_path / "s.db")
    with TestClient(create_app("t", s)) as c:
        assert c.get("/api/state", headers=H).json()["default_skills"] == ["delegation"]
        c.post("/api/skills/global", json={"names": ["delegation", "notes"]}, headers=H)
        st = c.get("/api/state", headers=H).json()
        new = c.post("/api/sessions", json={}, headers=H).json()
        assert st["default_skills"] == ["delegation", "notes"] == new["settings"]["skills"]


def test_missing_assets_are_404_not_the_app_page(tmp_path, monkeypatch):
    from gamedevworkstation import server

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(server, "frontend_dist", lambda: dist)
    with TestClient(server.create_app("t", AppState(db_path=tmp_path / "c.db"))) as c:
        assert c.get("/assets/app.js").status_code == 200
        r = c.get("/assets/Settings-old123.js")
        assert r.status_code == 404 and "id=root" not in r.text
        assert c.get("/settings").status_code == 200  # client routes still get the app page


async def test_stop_by_the_user_leaves_a_notice_the_model_never_sees(tmp_path):
    import asyncio

    app = AppState(db_path=tmp_path / "n.db")
    s = app.store.create()
    app.runner.running[s["id"]] = asyncio.create_task(asyncio.sleep(30))  # a turn in progress
    assert await app.runner.stop(s["id"], notice=True)
    msgs = app.store.messages(s["id"])
    assert msgs[-1].meta.get("notice") == "stopped" and "Stopped" in msgs[-1].text()
    assert app.runner.model_history(s["id"]) == []
    # Internal stops (deleting a session, shutdown) and idle sessions add nothing.
    app.runner.running[s["id"]] = asyncio.create_task(asyncio.sleep(30))
    await app.runner.stop(s["id"])
    app.runner.running.pop(s["id"])  # the real runner's done-callback does this
    assert not await app.runner.stop(s["id"], notice=True)
    assert len(app.store.messages(s["id"])) == 1


def test_storage_reports_reclaimable_space_including_the_wal(tmp_path):
    from fastapi import APIRouter, FastAPI

    from gamedevworkstation.routes import register_routes

    app = AppState(db_path=tmp_path / "r.db")
    register_routes(FastAPI(), APIRouter(), app)
    st = app.extensions["storage"]
    s = app.store.create()
    for i in range(300):
        app.db.insert("events", {"seq": 10_000 + i, "type": "x", "session_id": s["id"], "data": "y" * 4000, "ts": 1.0})
    app.db.execute("DELETE FROM events WHERE seq >= 10000")
    u = st.usage()["database"]
    wal = (tmp_path / "r.db-wal")
    assert u["free_bytes"] >= app.db.free_bytes() + (wal.stat().st_size if wal.exists() else 0) > 0
    freed = st.compact()["freed_bytes"]
    assert freed > 0 and st.usage()["database"]["free_bytes"] < u["free_bytes"]
