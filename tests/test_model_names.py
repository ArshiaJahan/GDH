"""Model display names: config field, fallback for older configs, and the API payloads the UI reads."""
import re

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation import config as config_mod
from gamedevworkstation.app import AppState
from gamedevworkstation.config import derive_display_name, load_config
from gamedevworkstation.providers.fake import FakeProvider
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}

NAMES = {
    "claude-fable-5-1": "Fable 5.1", "claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-haiku-5-5": "Haiku 5.5", "gpt-6-astra": "GPT-6 Astra", "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6.1-terra": "GPT-6.1 Terra", "gpt-6-luna": "GPT-6 Luna",
}
TIERS = {"claude.fast": "claude-haiku-5-5", "claude.standard": "claude-sonnet-5-5", "claude.deep": "claude-opus-5-5",
         "codex.fast": "gpt-6.1-terra", "codex.standard": "gpt-6.1-sol", "codex.cli": "gpt-6.1-sol"}


@pytest.fixture
def client(tmp_path):
    s = AppState(db_path=tmp_path / "s.db")
    s.providers.override("anthropic", "default", FakeProvider())
    with TestClient(create_app("t", s)) as c:
        yield c


def test_default_catalog_has_display_names_and_unchanged_tiers(cfg):
    assert {k: m.display_name for k, m in cfg.models.items()} == NAMES
    assert cfg.tiers == TIERS  # tier keys and routing are untouched
    assert cfg.label("gpt-6.1-sol") == "GPT-6.1 Sol · codex.standard"
    assert cfg.label("gpt-6.1-sol", "codex.cli") == "GPT-6.1 Sol · codex.cli"
    assert cfg.label("claude-opus-5-5") == "Opus 5.5 · claude.deep"
    assert cfg.label("gpt-6-astra") == "GPT-6 Astra"  # no tier routes to it


@pytest.mark.parametrize("mid,name", [
    *NAMES.items(), ("claude-haiku-4-5-20251001", "Haiku 4.5"), ("claude-opus-4-20250514", "Opus 4"),
    ("gpt-5.3-codex", "GPT-5.3 Codex"), ("gpt-5.4-mini", "GPT-5.4 Mini"), ("gpt-6", "GPT-6"), ("eleven_v4", "Eleven v4"),
    ("eleven_v4_turbo", "Eleven v4 Turbo"), ("eleven_flash_v2_5", "Eleven Flash v2.5"),
    ("eleven_multilingual_v2", "Eleven Multilingual v2"), ("scribe_v2", "Scribe v2"), ("music_v2_5", "Music v2.5"),
    ("eleven_text_to_sound_v3", "Sound Effects v3"), ("eleven_multilingual_sts_v2", "Voice Changer v2"),
    ("my-local", "my-local"),
])
def test_derive_display_name(mid, name):
    assert derive_display_name(mid) == name


def test_older_config_without_display_name_falls_back(tmp_path, monkeypatch):
    # A defaults file from before display_name existed, plus a user file adding a custom model.
    old_defaults = tmp_path / "old_default.toml"
    old_defaults.write_text(re.sub(r'(?m)^display_name = ".*"\n', "", config_mod.DEFAULT_CONFIG_PATH.read_text()))
    assert "display_name =" not in old_defaults.read_text()
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_PATH", old_defaults)
    user = tmp_path / "config.toml"
    user.write_text('[models."gpt-5.4-mini"]\nprovider = "openai"\n\n[models."my-local"]\nprovider = "openai"\n')
    cfg = load_config(user)
    for mid, name in NAMES.items():
        assert cfg.models[mid].display_name == name
    assert cfg.models["gpt-5.4-mini"].display_name == "GPT-5.4 Mini"
    assert cfg.models["my-local"].display_name == "my-local"
    assert cfg.model("gpt-9-nova").display_name == "GPT-9 Nova"  # unknown model, not in the catalog


def test_user_display_name_overrides_default(tmp_path):
    user = tmp_path / "config.toml"
    user.write_text('[models."gpt-6.1-sol"]\ndisplay_name = "Sol"\n')
    cfg = load_config(user)
    assert cfg.models["gpt-6.1-sol"].display_name == "Sol"
    assert cfg.models["gpt-6.1-sol"].input == 2.0  # rest of the entry still comes from defaults


def test_api_exposes_display_names_and_tier_map(client):
    st = client.get("/api/state", headers=H).json()
    assert {k: m["display_name"] for k, m in st["models"].items()} == NAMES
    assert st["tiers"] == TIERS
    assert st["tier_models"]["codex.standard"] == {"model": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol", "provider": "openai"}
    assert st["tier_models"]["codex.cli"] == {"model": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol", "provider": "openai"}
    assert st["tier_models"]["codex.fast"]["display_name"] == "GPT-6.1 Terra"
    assert st["tier_models"]["claude.deep"] == {"model": "claude-opus-5-5", "display_name": "Opus 5.5", "provider": "anthropic"}

    env = client.get("/api/environment", headers=H).json()
    by_id = {m["id"]: m for m in env["models"]}
    assert by_id["gpt-6.1-terra"]["display_name"] == "GPT-6.1 Terra" and by_id["gpt-6.1-terra"]["tier"] == "codex.fast"
    assert env["tier_models"] == st["tier_models"]

    s = client.get("/api/settings", headers=H).json()
    assert s["models"]["gpt-6-luna"]["display_name"] == "GPT-6 Luna"
    assert s["tier_models"] == st["tier_models"]
