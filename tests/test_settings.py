import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend

from gamedevworkstation.app import AppState
from gamedevworkstation.providers.fake import FakeProvider
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.d = {}

    def get_password(self, service, username):
        return self.d.get((service, username))

    def set_password(self, service, username, password):
        self.d[(service, username)] = password

    def delete_password(self, service, username):
        self.d.pop((service, username), None)


@pytest.fixture
def env(tmp_path, monkeypatch):
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    monkeypatch.delenv("GDW_NO_KEYCHAIN")
    s = AppState(db_path=tmp_path / "s.db")
    s.providers.override("anthropic", "default", FakeProvider())
    with TestClient(create_app("t", s)) as c:
        yield c, s, kr


def test_keys_go_to_keychain_never_back_to_ui(env, tmp_path):
    c, s, kr = env
    r = c.post("/api/settings/keys", json={"provider": "anthropic", "profile": "work", "key": "sk-ant-secret-1234"}, headers=H)
    assert r.json() == {"ok": True, "hint": "…1234"}
    assert kr.d[("GameDevWorkstation", "anthropic:work")] == "sk-ant-secret-1234"
    st = c.get("/api/settings", headers=H).json()
    work = next(a for a in st["accounts"]["anthropic"] if a["profile"] == "work")
    assert work == {"profile": "work", "has_key": True, "hint": "…1234", "source": "keychain"}
    assert "sk-ant-secret" not in r.text + str(st)
    assert "secret" not in (tmp_path / "home" / "config.toml").read_text()
    c.delete("/api/settings/keys/anthropic/work", headers=H)
    assert ("GameDevWorkstation", "anthropic:work") not in kr.d


def test_patch_settings_applies_live(env):
    c, s, _ = env
    c.patch("/api/settings", json={"delegation": {"confirm_over_usd": 2.5}, "tiers": {"claude.deep": "claude-fable-5-1"}}, headers=H)
    assert s.config.delegation["confirm_over_usd"] == 2.5 and s.config.resolve("claude.deep") == "claude-fable-5-1"
    assert s.config.delegation["job_budget_usd"] == 5.0  # untouched keys kept
    assert c.patch("/api/settings", json={"models": {}}, headers=H).status_code == 400
    assert c.patch("/api/settings", json={"orchestrator": {"effort": "max"}}, headers=H).status_code == 400


def test_background_upload(env):
    c, s, _ = env
    r = c.post("/api/settings/background?theme=dark", files={"file": ("bg.mp4", b"\x00\x00\x00 ftypisom", "video/mp4")}, headers=H)
    assert r.json()["dark"]["kind"] == "video" and r.json()["dark"]["fit"] == "cover"
    assert c.post("/api/settings/background?theme=dark", files={"file": ("x.exe", b"MZ", "application/x")}, headers=H).status_code == 400


def test_appearance_patch_keeps_provider_clients(env):
    c, s, kr = env
    calls = []
    real = s.providers.reset
    s.providers.reset = lambda: (calls.append(1), real())[1]
    c.patch("/api/settings", json={"appearance": {"panel_opacity": 0.8}}, headers=H)
    assert calls == [] and s.config.appearance["panel_opacity"] == 0.8
    c.patch("/api/settings", json={"limits": {"session_usd": 5}}, headers=H)
    assert calls == [1]
