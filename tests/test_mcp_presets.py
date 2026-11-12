"""Built-in MCP servers ([mcp.presets.*]) and skills that turn MCP servers on ([skills.mcp_on_invoke]).

Nothing here launches uvx: connections are stubbed, or the command is made unfindable."""
import time

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.features import mcp_feature
from gamedevworkstation.providers.fake import FakeProvider, text_response
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}
UNITY_ARGS = ["--offline", "--from", "mcpforunityserver==10.3.0", "mcp-for-unity"]


def wait_idle(c, sid, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not c.get(f"/api/sessions/{sid}", headers=H).json()["running"]:
            return
        time.sleep(0.02)
    raise TimeoutError


@pytest.fixture
def connects(monkeypatch):
    """Record connection attempts instead of starting servers; they fail like a missing Unity would."""
    names: list[str] = []

    async def connect(self, name):
        names.append(name)
        raise RuntimeError("stub: not started")

    monkeypatch.setattr(mcp_feature.MCPManager, "connect", connect)
    return names


def client(s: AppState, seen: list | None = None):
    if seen is not None:
        orig = s.bus.publish

        def publish(type, data=None, session_id=None):
            seen.append((type, data or {}, session_id))
            return orig(type, data, session_id)

        s.bus.publish = publish  # type: ignore[method-assign]
    return TestClient(create_app("t", s))


def unity(c) -> dict | None:
    return next((x for x in c.get("/api/mcp/servers", headers=H).json() if x["name"] == "unity"), None)


# ------------------------------------------------------------------ seeding


def test_fresh_db_seeds_the_unity_preset_once(tmp_path):
    s = AppState(db_path=tmp_path / "p.db")
    with client(s) as c:
        u = unity(c)
        assert u and u["preset"] and not u["modified"] and not u["shared"]
        assert u["command"] == "uvx" and u["args"] == UNITY_ARGS and u["transport"] == "stdio"
        assert u["enabled_default"] is False  # not on for every session
        assert "com.coplaydev.unity-mcp" in u["description"]
        sess = c.post("/api/sessions", json={}, headers=H).json()
        assert s.mcp.enabled_for(sess) == []
        assert s.mcp.seed_presets() == []  # a second startup adds nothing
    with client(s) as c:  # restart on the same database
        assert [x["name"] for x in c.get("/api/mcp/servers", headers=H).json()] == ["unity"]
    assert s.db.kv_get("mcp_presets_seeded") == ["unity"]


def test_deleted_preset_stays_deleted_until_reset(tmp_path):
    s = AppState(db_path=tmp_path / "p.db")
    with client(s) as c:
        assert c.delete("/api/mcp/servers/unity", headers=H).json()["ok"]
    with client(s) as c:  # restart: not added back
        assert unity(c) is None
        assert s.mcp.seed_presets() == []
        assert s.db.kv_get("mcp_presets_deleted") == ["unity"]
        r = c.post("/api/mcp/servers/unity/reset", headers=H)  # Reset to default brings it back
        assert r.status_code == 200 and r.json()["preset"] and not r.json()["modified"]
        assert s.db.kv_get("mcp_presets_deleted") == []
        assert c.post("/api/mcp/servers/nope/reset", headers=H).status_code == 404


def test_existing_user_server_with_the_preset_name_is_untouched(tmp_path):
    s = AppState(db_path=tmp_path / "p.db")
    mine = {"name": "unity", "transport": "stdio", "command": "/usr/bin/true", "args": ["mine"], "env": {},
            "headers": {}, "enabled_default": 1, "shared": 0}
    s.db.insert("mcp_servers", mine)
    with client(s) as c:
        u = unity(c)
        assert u["command"] == "/usr/bin/true" and u["args"] == ["mine"] and u["enabled_default"] is True
        assert not u["preset"] and not u["modified"]
        assert c.post("/api/mcp/servers/unity/reset", headers=H).status_code == 409  # yours, not the built-in
        assert unity(c)["args"] == ["mine"]
        # Deleting it doesn't let the preset take its place at the next startup.
        c.delete("/api/mcp/servers/unity", headers=H)
    with client(s) as c:
        assert unity(c) is None


def test_uvx_missing_still_seeds_with_a_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_feature.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(mcp_feature, "COMMAND_FALLBACKS", {})
    s = AppState(db_path=tmp_path / "p.db")
    with client(s) as c:
        u = unity(c)
        assert u and u["preset"]
        assert "uvx wasn't found" in u["hint"] and "brew install uv" in u["hint"]
        r = c.post("/api/mcp/servers/unity/test", headers=H).json()  # fails fast with the same advice
        assert r["ok"] is False and "uvx wasn't found" in r["error"]


def test_uvx_is_found_in_the_homebrew_fallback(monkeypatch, tmp_path):
    exe = tmp_path / "uvx"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(mcp_feature.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(mcp_feature, "COMMAND_FALLBACKS", {"uvx": ("/nonexistent/uvx", str(exe))})
    assert mcp_feature.resolve_command("uvx") == str(exe)
    assert mcp_feature.missing_command_hint("uvx") is None
    assert mcp_feature.resolve_command("/nonexistent/bin") is None


def test_modified_preset_shows_and_resets_keeping_its_default(tmp_path):
    s = AppState(db_path=tmp_path / "p.db")
    with client(s) as c:
        edited = {"name": "unity", "transport": "stdio", "command": "uvx", "args": ["--from", "mcpforunityserver==10.4.0",
                                                                                    "mcp-for-unity"]}
        u = c.post("/api/mcp/servers", json={**edited, "enabled_default": False}, headers=H).json()
        assert u["preset"] and u["modified"]
        c.patch("/api/mcp/servers/unity", json={"enabled_default": True}, headers=H)
        u = c.post("/api/mcp/servers/unity/reset", headers=H).json()
        assert not u["modified"] and u["args"] == UNITY_ARGS and u["enabled_default"] is True


# ------------------------------------------------------- skills turn servers on


@pytest.fixture
def env(tmp_path, connects):
    s = AppState(db_path=tmp_path / "s.db")
    fake = FakeProvider()
    s.providers.override("anthropic", "default", fake)
    seen: list = []
    with client(s, seen) as c:
        yield c, s, fake, seen


def notices(seen, sid):
    return [d for t, d, x in seen if t == "mcp.auto_enabled" and x == sid]


def test_invoking_a_unity_skill_enables_unity_for_the_session(env, connects):
    c, s, fake, seen = env
    fake.script = [text_response("routed"), text_response("again")]
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    other = c.post("/api/sessions", json={}, headers=H).json()["id"]
    assert c.post(f"/api/sessions/{sid}/messages", json={"text": "make a game", "skill": "unity-router"},
                  headers=H).status_code == 200
    wait_idle(c, sid)
    st = s.store.get(sid)["settings"]
    assert st["connectors"] == {"unity": True} and st["shared_tools"] is False
    assert "unity" in connects  # warmed before the turn; it failed to start and the turn still ran
    assert fake.calls and c.get(f"/api/sessions/{sid}/messages", headers=H).json()[-1]["role"] == "assistant"
    assert [n["message"] for n in notices(seen, sid)] == ["Enabled MCP server unity for this session"]
    assert any(t == "session.updated" and x == sid and d["settings"]["connectors"] == {"unity": True}
               for t, d, x in seen)
    assert s.store.get(other)["settings"]["connectors"] == {}  # only that session
    # Invoking it again (or another Unity skill) says nothing new.
    c.post(f"/api/sessions/{sid}/messages", json={"text": "next", "skill": "play-verify"}, headers=H)
    wait_idle(c, sid)
    assert len(notices(seen, sid)) == 1
    # A skill without MCP servers enables none.
    sid2 = c.post("/api/sessions", json={}, headers=H).json()["id"]
    fake.script = [text_response("ok")]
    c.post(f"/api/sessions/{sid2}/messages", json={"text": "x", "skill": "grill-me"}, headers=H)
    wait_idle(c, sid2)
    assert s.store.get(sid2)["settings"]["connectors"] == {} and not notices(seen, sid2)


def test_connectors_card_skill_tick_enables_its_server(env):
    c, s, _, seen = env
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    r = c.patch(f"/api/sessions/{sid}", json={"settings": {"skills": ["delegation", "compile-fix-loop"]}}, headers=H)
    assert r.status_code == 200 and r.json()["settings"]["connectors"] == {"unity": True}
    assert len(notices(seen, sid)) == 1
    # Unticking the skill leaves the server alone; other settings changes don't enable anything.
    c.patch(f"/api/sessions/{sid}", json={"settings": {"connectors": {"unity": False}}}, headers=H)
    c.patch(f"/api/sessions/{sid}", json={"settings": {"skills": ["delegation"]}}, headers=H)
    c.patch(f"/api/sessions/{sid}", json={"title": "renamed"}, headers=H)
    assert s.store.get(sid)["settings"]["connectors"] == {"unity": False} and len(notices(seen, sid)) == 1


def test_no_implicit_shared_tools_or_shared_servers(env):
    c, s, fake, seen = env
    s.db.execute("UPDATE mcp_servers SET shared=1 WHERE name='unity'")  # as if it came from another machine
    fake.script = [text_response("ok")]
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    c.post(f"/api/sessions/{sid}/messages", json={"text": "x", "skill": "unity-router"}, headers=H)
    wait_idle(c, sid)
    st = s.store.get(sid)["settings"]
    assert st["connectors"] == {} and st["shared_tools"] is False and not notices(seen, sid)


def test_server_on_by_default_or_missing_needs_nothing(env):
    c, s, _, seen = env
    c.patch("/api/mcp/servers/unity", json={"enabled_default": True}, headers=H)
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    s.mcp.enable_for_skills(sid, ["unity-router"])
    assert s.store.get(sid)["settings"]["connectors"] == {} and not notices(seen, sid)
    c.delete("/api/mcp/servers/unity", headers=H)
    assert s.mcp.enable_for_skills(sid, ["unity-router"]) == []


def test_config_maps_every_unity_skill_to_unity(cfg):
    from .test_skills import UNITY_PACK

    for name in UNITY_PACK:
        assert cfg.skill_mcp_servers(name) == ["unity"], name
    assert cfg.skill_mcp_servers("grill-me") == []
    assert cfg.mcp_presets()["unity"]["args"] == UNITY_ARGS
