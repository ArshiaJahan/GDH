"""MCP: shared-tool allowlist, and secrets in env/headers kept in the Keychain (mocked)."""
import asyncio
import json
import sys

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.server import create_app

from .conftest import FIXTURES, untrusted

H = {"Authorization": "Bearer t"}
DEMO = [str(FIXTURES / "mcp" / "demo_server.py")]
ENVY = [str(FIXTURES / "mcp" / "env_server.py")]


@pytest.fixture
def keychain(monkeypatch):
    """An in-memory stand-in for the macOS Keychain; the real one is never touched."""
    import keyring

    store: dict[tuple[str, str], str] = {}
    monkeypatch.setenv("GDW_NO_KEYCHAIN", "0")
    monkeypatch.setattr(keyring, "set_password", lambda s, a, v: store.__setitem__((s, a), v))
    monkeypatch.setattr(keyring, "get_password", lambda s, a: store.get((s, a)))

    def delete(s, a):
        if (s, a) not in store:
            raise KeyError(a)
        del store[(s, a)]

    monkeypatch.setattr(keyring, "delete_password", delete)
    return store


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "s.db")
    with TestClient(create_app("t", s)) as c:
        yield c, s


def _raw(s, name):
    return s.db.one("SELECT env, headers FROM mcp_servers WHERE name=?", [name])


# ------------------------------------------------------------ shared allowlist


async def test_shared_tool_allowlist(tmp_path):
    s = AppState(db_path=tmp_path / "a.db")
    from gamedevworkstation.features import mcp_feature

    mcp_feature.register(FastAPI(), APIRouter(), s)
    s.db.insert("mcp_servers", {"name": "demo", "transport": "stdio", "command": sys.executable, "args": DEMO,
                                "env": {}, "headers": {}, "enabled_default": 1, "shared": 1})
    sess = s.store.create()
    sess = s.store.update(sess["id"], settings={"shared_tools": True})
    await s.mcp.warm(sess)
    ctx = ToolContext(app=s, session=sess, run_id="main:x")
    s.config.modes["allowlist"] = ["shared_tool:demo__sh*"]
    try:
        # Allowlisted: runs without a card.
        out = await asyncio.wait_for(s.mcp.call(ctx, "mcp__demo__shout", {"text": "hi"}), 30)
        assert untrusted(out.text) == ("mcp:demo.shout", "HI") and not s.approvals.pending(sess["id"])
        # Not covered by the rule: still asks; declining refuses the call.
        task = asyncio.create_task(s.mcp.call(ctx, "mcp__demo__add", {"a": 1, "b": 2}))
        for _ in range(300):
            if pend := s.approvals.pending(sess["id"]):
                break
            await asyncio.sleep(0.01)
        assert pend[0]["kind"] == "shared_tool"
        s.approvals.resolve(pend[0]["id"], "deny")
        assert (await task).is_error
        # A rule for another server doesn't match.
        s.config.modes["allowlist"] = ["shared_tool:other__*"]
        task = asyncio.create_task(s.mcp.call(ctx, "mcp__demo__shout", {"text": "x"}))
        for _ in range(300):
            if pend := s.approvals.pending(sess["id"]):
                break
            await asyncio.sleep(0.01)
        assert pend, "a non-matching rule must not skip the approval"
        s.approvals.resolve(pend[0]["id"], "approve")
        assert untrusted((await task).text) == ("mcp:demo.shout", "X")
    finally:
        s.config.modes["allowlist"] = []
        await s.mcp.aclose()


# --------------------------------------------------------------------- secrets


def test_env_secret_goes_to_keychain_and_resolves_at_connect(env, keychain):
    c, s = env
    body = {"name": "envy", "transport": "stdio", "command": sys.executable, "args": ENVY,
            "env": {"API_TOKEN": "s3cret-value-1234", "MODE": "plain=x:y"}}
    r = c.post("/api/mcp/servers", json=body, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["env"] == {"API_TOKEN": "••••1234", "MODE": "plain=x:y"}
    raw = _raw(s, "envy")
    assert "s3cret" not in raw["env"]
    assert json.loads(raw["env"])["API_TOKEN"]["keychain"] == "mcp:envy:API_TOKEN"
    assert keychain[("GameDevWorkstation", "mcp:envy:API_TOKEN")] == "s3cret-value-1234"
    assert "s3cret" not in c.get("/api/mcp/servers", headers=H).text

    # Resolved when the server starts.
    async def check() -> str:
        sess = s.store.create()
        ctx = ToolContext(app=s, session=sess, run_id="main:x")
        await s.mcp.connect("envy")
        return (await s.mcp.call(ctx, "mcp__envy__getenv", {"name": "API_TOKEN"})).text

    assert untrusted(c.portal.call(check)) == ("mcp:envy.getenv", "s3cret-value-1234")

    # Editing with the masked value keeps the secret; a new value replaces it.
    assert c.post("/api/mcp/servers", json={**body, "env": {"API_TOKEN": "••••1234", "MODE": "m"}},
                  headers=H).status_code == 200
    assert keychain[("GameDevWorkstation", "mcp:envy:API_TOKEN")] == "s3cret-value-1234"
    c.post("/api/mcp/servers", json={**body, "env": {"API_TOKEN": "brand-new-value-9999"}}, headers=H)
    assert keychain[("GameDevWorkstation", "mcp:envy:API_TOKEN")] == "brand-new-value-9999"
    assert untrusted(c.portal.call(check)) == ("mcp:envy.getenv", "brand-new-value-9999")
    # A masked value with nothing stored behind it is refused.
    assert c.post("/api/mcp/servers", json={**body, "env": {"OTHER_KEY": "••••abcd"}}, headers=H).status_code == 400
    # Dropping the variable deletes its Keychain entry; so does removing the server.
    c.post("/api/mcp/servers", json={**body, "env": {"GITHUB_PAT": "ghp_abcdefgh5678"}}, headers=H)
    assert ("GameDevWorkstation", "mcp:envy:API_TOKEN") not in keychain
    assert keychain[("GameDevWorkstation", "mcp:envy:GITHUB_PAT")] == "ghp_abcdefgh5678"
    assert c.delete("/api/mcp/servers/envy", headers=H).status_code == 200
    assert not keychain


def test_header_secret_and_missing_entry(env, keychain):
    c, s = env
    r = c.post("/api/mcp/servers", json={"name": "remote", "transport": "http", "url": "https://example.invalid/mcp",
                                         "headers": {"Authorization": "Bearer abcdefgh1234", "Accept-Language": "en"}},
               headers=H)
    assert r.json()["headers"] == {"Authorization": "••••1234", "Accept-Language": "en"}
    assert "abcdefgh" not in _raw(s, "remote")["headers"]
    assert keychain[("GameDevWorkstation", "mcp:remote:header:Authorization")] == "Bearer abcdefgh1234"
    # A Keychain entry deleted behind our back: a clear error, never a crash or an empty header.
    keychain.clear()
    from gamedevworkstation.features.mcp_feature import resolve_secrets

    with pytest.raises(RuntimeError, match="missing from the Keychain"):
        resolve_secrets(json.loads(_raw(s, "remote")["headers"]))


def test_migrates_plaintext_rows_on_startup(tmp_path, keychain):
    s = AppState(db_path=tmp_path / "m.db")
    s.db.insert("mcp_servers", {"name": "old", "transport": "stdio", "command": "x", "args": [],
                                "env": {"OPENAI_API_KEY": "sk-plaintext-0000", "PATH_EXTRA": "/opt/bin"},
                                "headers": {}, "enabled_default": 1, "shared": 0})
    with TestClient(create_app("t", s)) as c:  # startup runs the migration
        assert c.get("/api/mcp/servers", headers=H).json()[0]["env"] == {"OPENAI_API_KEY": "••••0000",
                                                                          "PATH_EXTRA": "/opt/bin"}
    raw = json.loads(_raw(s, "old")["env"])
    assert raw["PATH_EXTRA"] == "/opt/bin" and raw["OPENAI_API_KEY"]["keychain"] == "mcp:old:OPENAI_API_KEY"
    assert keychain[("GameDevWorkstation", "mcp:old:OPENAI_API_KEY")] == "sk-plaintext-0000"
    assert s.mcp.migrate_secrets() == 0  # idempotent


def test_without_keychain_falls_back_to_sqlite(env, caplog):
    c, s = env  # conftest sets GDW_NO_KEYCHAIN=1
    r = c.post("/api/mcp/servers", json={"name": "dev", "transport": "stdio", "command": "x",
                                         "env": {"SOME_SECRET": "dev-only-secret-4321"}}, headers=H)
    assert r.json()["env"] == {"SOME_SECRET": "••••4321"}  # still masked in the API
    assert json.loads(_raw(s, "dev")["env"]) == {"SOME_SECRET": "dev-only-secret-4321"}
    assert "plain SQLite" in caplog.text
    # The masked value keeps it here too.
    c.post("/api/mcp/servers", json={"name": "dev", "transport": "stdio", "command": "x",
                                     "env": {"SOME_SECRET": "••••4321"}}, headers=H)
    assert json.loads(_raw(s, "dev")["env"]) == {"SOME_SECRET": "dev-only-secret-4321"}


def test_rejected_edit_keeps_the_stored_secrets(env, keychain):
    c, s = env
    body = {"name": "keep", "transport": "http", "url": "https://example.invalid/mcp",
            "env": {"API_TOKEN": "s3cret-value-1234"}, "headers": {"Authorization": "Bearer abcdefgh1234"}}
    assert c.post("/api/mcp/servers", json=body, headers=H).status_code == 200
    before = _raw(s, "keep")
    # env drops API_TOKEN, but the headers are invalid: nothing may change, the Keychain included.
    bad = {**body, "env": {}, "headers": {"X-Other-Token": "••••abcd"}}
    assert c.post("/api/mcp/servers", json=bad, headers=H).status_code == 400
    assert keychain[("GameDevWorkstation", "mcp:keep:API_TOKEN")] == "s3cret-value-1234"
    assert keychain[("GameDevWorkstation", "mcp:keep:header:Authorization")] == "Bearer abcdefgh1234"
    assert _raw(s, "keep") == before
    # A valid edit drops the unused entries once the row is saved.
    assert c.post("/api/mcp/servers", json={**body, "env": {}, "headers": {}}, headers=H).status_code == 200
    assert not keychain and json.loads(_raw(s, "keep")["env"]) == {}


def test_secret_helpers_never_touch_the_keychain_when_disabled(monkeypatch):
    import keyring

    from gamedevworkstation import config

    def boom(*a):
        raise AssertionError("the real Keychain was touched")

    for fn in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, fn, boom)
    monkeypatch.setenv("GDW_NO_KEYCHAIN", "1")
    assert config.get_secret("mcp:x:API_TOKEN") is None
    config.delete_secret("mcp:x:API_TOKEN")
    with pytest.raises(RuntimeError, match="disabled"):
        config.set_secret("mcp:x:API_TOKEN", "v")
