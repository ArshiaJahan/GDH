"""Several key profiles per provider: each session picks one per provider (settings.accounts),
and every call site (main loop, subagents, Codex CLI, harnesses, ElevenLabs) uses it."""
import asyncio
import json
import os
import stat
import subprocess
import time

import httpx
import keyring
import pytest
import respx
from fastapi.testclient import TestClient

from workspace.agent.tools import ToolContext
from workspace.app import AppState
from workspace.config import Config, save_config_patch
from workspace.features.elevenlabs_feature import ElevenLabsService, _register_tools
from workspace.features.status import StatusChecker
from workspace.providers.fake import FakeProvider
from workspace.server import create_app

from .test_settings import MemoryKeyring

H = {"Authorization": "Bearer t"}
TWO = {"anthropic": ["default", "work"], "openai": ["default", "work"], "elevenlabs": ["default", "second"]}

FAKE_CODEX = r"""#!/usr/bin/env python3
import json, sys, os
args = sys.argv[1:]
sys.stdin.read()
open(os.environ["FAKE_CODEX_LOG"], "a").write(json.dumps({"key": os.environ.get("CODEX_API_KEY")}) + "\n")
def emit(o): print(json.dumps(o), flush=True)
emit({"type": "thread.started", "thread_id": "thr_1"})
emit({"type": "item.completed", "item": {"id": "i3", "type": "agent_message", "text": "done"}})
emit({"type": "turn.completed", "usage": {"input_tokens": 20, "cached_input_tokens": 0, "output_tokens": 3}})
"""


def wait_idle(c, sid):
    for _ in range(300):
        if not c.get(f"/api/sessions/{sid}", headers=H).json()["running"]:
            return
        time.sleep(0.03)
    raise TimeoutError


@pytest.fixture
def two(tmp_path, monkeypatch):
    """An app with two profiles per provider and a FakeProvider for each (provider, profile)."""
    s = AppState(config=save_config_patch({"accounts": TWO}), db_path=tmp_path / "a.db")
    fakes = {}
    for prov in ("anthropic", "openai"):
        for prof in TWO[prov]:
            fakes[(prov, prof)] = FakeProvider(prov)
            s.providers.override(prov, prof, fakes[(prov, prof)])
    checks: list = []

    async def fake_check_all(self, only=None):  # no network; record what was re-checked
        checks.append(only)
        return []

    monkeypatch.setattr(StatusChecker, "check_all", fake_check_all)
    with TestClient(create_app("t", s)) as c:
        yield c, s, fakes, checks


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "codex"
    exe.write_text(FAKE_CODEX)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "codex.log"
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-default-dummy")
    monkeypatch.setenv("WORKSPACE_KEY_OPENAI_WORK", "sk-openai-work-dummy")
    return log


def test_profile_for_fallbacks():
    c = Config(accounts={k: list(v) for k, v in TWO.items()})
    # New-style: per-provider choices in settings.accounts.
    s = {"account": "default", "settings": {"accounts": {"anthropic": "work", "openai": "work"}}}
    assert c.profile_for(s, "anthropic") == "work" and c.profile_for(s, "openai") == "work"
    assert c.profile_for(s, "elevenlabs") == "default"  # missing → the provider's first profile
    # Legacy sessions: the account column is the Anthropic profile; others get their default.
    legacy = {"account": "work", "settings": {}}
    assert c.session_accounts(legacy) == {"anthropic": "work", "openai": "default", "elevenlabs": "default"}
    # A profile that no longer exists falls back to the default.
    gone = {"account": "old", "settings": {"accounts": {"openai": "old"}}}
    assert c.session_accounts(gone) == {"anthropic": "default", "openai": "default", "elevenlabs": "default"}
    # The default is the first listed profile.
    c.accounts["openai"] = ["work", "default"]
    assert c.profile_for(None, "openai") == "work" and c.profile_for({"settings": {}}, "openai") == "work"
    assert Config().profile_for(None, "openai") == "default"  # no [accounts] at all


def test_new_session_defaults_and_patch(two):
    c, s, _, _ = two
    s.config.accounts["openai"] = ["work", "default"]
    ses = c.post("/api/sessions", json={}, headers=H).json()
    assert ses["settings"]["accounts"] == {"anthropic": "default", "openai": "work", "elevenlabs": "default"}
    sid = ses["id"]
    r = c.patch(f"/api/sessions/{sid}", json={"accounts": {"elevenlabs": "second"}}, headers=H).json()
    assert r["settings"]["accounts"] == {"anthropic": "default", "openai": "work", "elevenlabs": "second"}
    r = c.patch(f"/api/sessions/{sid}", json={"accounts": {"anthropic": "work"}}, headers=H).json()
    assert r["account"] == "work" and r["settings"]["accounts"]["elevenlabs"] == "second"  # merged, column mirrored
    r = c.patch(f"/api/sessions/{sid}", json={"account": "default"}, headers=H).json()  # old clients
    assert r["settings"]["accounts"]["anthropic"] == "default"
    assert c.patch(f"/api/sessions/{sid}", json={"accounts": {"openai": "nope"}}, headers=H).status_code == 400
    assert c.patch(f"/api/sessions/{sid}", json={"accounts": {"foo": "default"}}, headers=H).status_code == 400


def test_openai_session_uses_its_openai_profile(two):
    c, s, fakes, _ = two
    sid = c.post("/api/sessions", json={"model": "gpt-6.1-sol"}, headers=H).json()["id"]
    # The Anthropic profile is "default", so the old code (account column) would have used openai:default.
    c.patch(f"/api/sessions/{sid}", json={"accounts": {"openai": "work"}}, headers=H)
    c.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}, headers=H)
    wait_idle(c, sid)
    assert len(fakes[("openai", "work")].calls) == 1 and not fakes[("openai", "default")].calls
    u = s.db.one("SELECT provider, profile FROM usage_records WHERE session_id=? AND role='main'", [sid])
    assert u == {"provider": "openai", "profile": "work"}


def test_subagent_units_use_session_profiles(two):
    c, s, fakes, _ = two
    sess = s.store.create()
    sess = s.store.update(sess["id"], accounts={"openai": "work", "anthropic": "work"})

    async def go():
        ctx = ToolContext(app=s, session=sess, run_id=f"main:{sess['id']}")
        a = await s.tools.run(ctx, "spawn_subagent", {"name": "o", "tier": "codex.standard", "instructions": "x",
                                                       "run_in_background": False})
        b = await s.tools.run(ctx, "spawn_subagent", {"name": "c", "tier": "claude.fast", "instructions": "y",
                                                       "run_in_background": False})
        return a, b

    a, b = asyncio.run(go())
    assert not a.is_error and not b.is_error, (a.text, b.text)
    assert fakes[("openai", "work")].calls and not fakes[("openai", "default")].calls
    assert fakes[("anthropic", "work")].calls and not fakes[("anthropic", "default")].calls
    rows = s.db.all("SELECT provider, profile FROM usage_records WHERE role='subagent' ORDER BY provider")
    assert rows == [{"provider": "anthropic", "profile": "work"}, {"provider": "openai", "profile": "work"}]


def test_codex_cli_unit_and_harness_get_session_openai_key(two, fake_codex, tmp_path):
    c, s, _, _ = two
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x=1\n")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"]):
        subprocess.run(cmd, cwd=repo, check=True)
    s.config.modes["allowlist"] = ["codex_cli:*"]
    sess = s.store.create(folder=str(repo), mode="accept_edits")
    sess = s.store.update(sess["id"], accounts={"openai": "work"})

    async def go():
        ctx = ToolContext(app=s, session=sess, run_id=f"main:{sess['id']}")
        return await s.tools.run(ctx, "spawn_subagent", {"name": "fix", "tier": "codex.cli", "instructions": "fix",
                                                          "run_in_background": False})

    out = asyncio.run(go())
    assert "done" in out.text, out.text
    assert json.loads(fake_codex.read_text().splitlines()[0])["key"] == "sk-openai-work-dummy"
    u = s.db.one("SELECT profile FROM usage_records WHERE role='subagent'")
    assert u["profile"] == "work"

    # The Codex CLI harness for a session on the default profile gets the default key.
    sid = c.post("/api/sessions", json={"folder": str(repo), "mode": "accept_edits"}, headers=H).json()["id"]
    c.patch(f"/api/sessions/{sid}", json={"harness": "codex_cli"}, headers=H)
    c.post(f"/api/sessions/{sid}/messages", json={"text": "go"}, headers=H)
    wait_idle(c, sid)
    assert json.loads(fake_codex.read_text().splitlines()[1])["key"] == "sk-openai-default-dummy"
    # …and the work key once the session picks "work".
    c.patch(f"/api/sessions/{sid}", json={"accounts": {"openai": "work"}}, headers=H)
    c.post(f"/api/sessions/{sid}/messages", json={"text": "again"}, headers=H)
    wait_idle(c, sid)
    assert json.loads(fake_codex.read_text().splitlines()[2])["key"] == "sk-openai-work-dummy"
    rows = s.db.all("SELECT profile FROM usage_records WHERE session_id=? ORDER BY ts", [sid])
    assert [r["profile"] for r in rows] == ["default", "work"]


@respx.mock
async def test_elevenlabs_uses_session_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-default-dummy")
    monkeypatch.setenv("WORKSPACE_KEY_ELEVENLABS_SECOND", "el-second-dummy")
    a = AppState(db_path=tmp_path / "e.db")
    a.config.accounts = {k: list(v) for k, v in TWO.items()}
    svc = ElevenLabsService(a)
    a.extensions["elevenlabs"] = svc
    _register_tools(a, svc)
    route = respx.post(url__regex=r"https://api.elevenlabs.io/v1/text-to-speech/v1.*").mock(
        return_value=httpx.Response(200, content=b"ID3x", headers={"character-cost": "5"}))
    respx.get(url__regex=r"https://api.elevenlabs.io/v2/voices.*").mock(
        return_value=httpx.Response(200, json={"voices": [], "has_more": False, "total_count": 0}))
    s = a.store.create()
    s = a.store.update(s["id"], accounts={"elevenlabs": "second"})
    ctx = ToolContext(app=a, session=s, run_id="main:x")
    out = await a.tools.run(ctx, "tts", {"text": "Hello", "voice_id": "v1"})
    assert not out.is_error, out.text
    assert route.calls[-1].request.headers["xi-api-key"] == "el-second-dummy"
    assert a.db.one("SELECT profile FROM usage_records WHERE provider='elevenlabs'")["profile"] == "second"
    # The ElevenLabs page can pick a profile explicitly; an unknown one falls back to the session's.
    await svc.tts("Hi", session_id=None, source="user", voice_id="v1", profile="default")
    assert route.calls[-1].request.headers["xi-api-key"] == "el-default-dummy"
    await svc.tts("Hi", session_id=s["id"], source="user", voice_id="v1", profile="bogus")
    assert route.calls[-1].request.headers["xi-api-key"] == "el-second-dummy"


def test_delete_profile_and_remove_key(two, monkeypatch):
    c, s, _, checks = two
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    monkeypatch.delenv("WORKSPACE_NO_KEYCHAIN")
    el = s.extensions["elevenlabs"]
    reset_calls = []
    monkeypatch.setattr(s.providers, "reset", lambda: reset_calls.append(1))
    sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
    c.patch(f"/api/sessions/{sid}", json={"accounts": {"openai": "work", "elevenlabs": "second"}}, headers=H)

    # Removing a key re-runs that provider's auth check and drops cached clients.
    assert c.post("/api/settings/keys", json={"provider": "elevenlabs", "profile": "second",
                                              "key": "el-second-key-dummy"}, headers=H).status_code == 200
    el.client_for("second")
    checks.clear()
    reset_calls.clear()
    assert c.delete("/api/settings/keys/elevenlabs/second", headers=H).json() == {"ok": True}
    assert ("Workspace", "elevenlabs:second") not in kr.d
    assert checks == ["elevenlabs"] and reset_calls and el.clients == {}

    # Deleting a profile deletes its key, re-checks, and sessions on it fall back to the default.
    c.post("/api/settings/keys", json={"provider": "openai", "profile": "work", "key": "sk-work-key-dummy"}, headers=H)
    s.db.insert("auth_status", {"provider": "openai", "profile": "work", "status": "online", "error": None,
                                "models": "[]", "extra": "{}", "checked_at": 1.0}, replace=True)
    checks.clear()
    st = c.delete("/api/settings/accounts/openai/work", headers=H).json()
    assert [p["profile"] for p in st["accounts"]["openai"]] == ["default"]
    assert ("Workspace", "openai:work") not in kr.d and s.config.profiles("openai") == ["default"]
    assert not s.db.one("SELECT 1 FROM auth_status WHERE provider='openai' AND profile='work'")
    assert checks == ["openai"]
    assert s.config.profile_for(s.store.get(sid), "openai") == "default"
    assert s.config.profile_for(s.store.get(sid), "elevenlabs") == "second"  # other providers untouched
    # The last profile of a provider can't be deleted; unknown ones 404.
    assert c.delete("/api/settings/accounts/openai/default", headers=H).status_code == 400
    assert c.delete("/api/settings/accounts/openai/nope", headers=H).status_code == 404

    # Reorder (set default) and add a profile without a key.
    st = c.post("/api/settings/accounts/elevenlabs", json={"profiles": ["second", "default", "spare"]}, headers=H).json()
    assert [p["profile"] for p in st["accounts"]["elevenlabs"]] == ["second", "default", "spare"]
    assert s.config.profile_for(None, "elevenlabs") == "second"
    assert c.post("/api/settings/accounts/elevenlabs", json={"profiles": ["bad name"]}, headers=H).status_code == 400
    assert c.post("/api/settings/accounts/elevenlabs", json={"profiles": []}, headers=H).status_code == 400
