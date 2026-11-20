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


PI_DEFAULTS = {"enabled": True, "max_questions": 3, "model": "claude.fast", "effort": "low", "builtin_enabled": True,
               "claude_code_enabled": True, "max_calls": 2, "max_input_tokens": 4096, "max_output_tokens": 2048,
               "timeout_s": 30, "budget_usd": 0.03, "breaker_failures": 2, "breaker_pause_s": 600}


def test_prompt_improver_defaults(env):
    c, s, _ = env
    assert c.get("/api/settings", headers=H).json()["prompt_improver"] == PI_DEFAULTS
    assert s.config.prompt_improver == PI_DEFAULTS


@pytest.mark.parametrize("patch", [
    {"enabled": "yes"}, {"builtin_enabled": 1}, {"claude_code_enabled": None},
    {"model": ""}, {"model": 5},
    {"effort": "xhigh"}, {"effort": "max"}, {"effort": "turbo"},
    {"max_questions": 0}, {"max_questions": 4}, {"max_questions": 2.5}, {"max_questions": True},
    {"max_calls": 0}, {"max_calls": 3},
    {"max_input_tokens": 0}, {"max_output_tokens": -5}, {"timeout_s": 0},
    {"breaker_failures": 0}, {"breaker_failures": -1}, {"breaker_failures": 1.5}, {"breaker_failures": True},
    {"breaker_pause_s": 0}, {"breaker_pause_s": "600"},
    {"budget_usd": 0}, {"budget_usd": 1.5}, {"budget_usd": "0.02"},
])
def test_prompt_improver_patch_rejects_invalid(env, patch):
    c, s, _ = env
    r = c.patch("/api/settings", json={"prompt_improver": patch}, headers=H)
    assert r.status_code == 400
    assert s.config.prompt_improver == PI_DEFAULTS


def test_prompt_improver_patch_round_trips(env):
    c, s, _ = env
    r = c.patch("/api/settings", json={"prompt_improver": {"enabled": False, "max_questions": 2, "effort": "high",
                                                            "max_calls": 1, "budget_usd": 1,
                                                            "breaker_failures": 3, "breaker_pause_s": 60}}, headers=H)
    assert r.status_code == 200
    want = {**PI_DEFAULTS, "enabled": False, "max_questions": 2, "effort": "high", "max_calls": 1, "budget_usd": 1,
            "breaker_failures": 3, "breaker_pause_s": 60}
    assert r.json()["prompt_improver"] == want
    assert c.get("/api/settings", headers=H).json()["prompt_improver"] == want
    assert s.config.prompt_improver == want


def test_prompt_improver_load_drops_out_of_range(tmp_path):
    from gamedevworkstation.config import load_config

    p = tmp_path / "config.toml"
    p.write_text('[prompt_improver]\nmax_questions = 9\neffort = "max"\nenabled = false\n')
    cfg = load_config(p)
    assert cfg.prompt_improver["max_questions"] == 3 and cfg.prompt_improver["effort"] == "low"
    assert cfg.prompt_improver["enabled"] is False
