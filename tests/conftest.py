import os
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Captured before isolation so live tests can still find real keys.
REAL_KEYS = {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY")}

UNTRUSTED_BLOCK = re.compile(r'<(untrusted-[0-9a-f]{8}) source="([^"]*)">\n(.*)\n</\1>', re.S)


def untrusted(text: str) -> tuple[str, str] | None:
    """(source, body) of a text that is exactly one wrap_untrusted block (random tag), else None."""
    m = UNTRUSTED_BLOCK.fullmatch(text)
    return (m.group(2), m.group(3)) if m else None


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch, request):
    """Every test gets its own data dir and no keychain / real keys."""
    monkeypatch.setenv("GDW_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GDW_NO_KEYCHAIN", "1")
    monkeypatch.setenv("GDW_UPDATES_DIR", str(tmp_path / "updates"))  # never the real ~/GameDevWorkstationUpdates
    monkeypatch.setenv("GDW_UNITY_CLI_SEARCH", "0")  # never the real Unity CLI: only [unity].cli_path
    monkeypatch.setenv("GDW_CLAUDE_CLI_SEARCH", "0")  # never the real `claude`: only [claude_code].cli_path
    from gamedevworkstation.features import unity_cli

    monkeypatch.setattr(unity_cli, "GLOBAL_EDITOR_LOG", tmp_path / "no-global-editor.log")
    if "live" not in request.keywords:
        for k in REAL_KEYS:
            monkeypatch.delenv(k, raising=False)
    from gamedevworkstation import config

    config.get_config.cache_clear()
    yield
    config.get_config.cache_clear()


@pytest.fixture(autouse=True)
def _no_auto_title(request, monkeypatch):
    """Auto-titling makes one more provider call after a session's first reply, which would eat
    scripted FakeProvider responses meant for later turns. Tests opt in with @pytest.mark.auto_title."""
    if "auto_title" not in request.keywords:
        from gamedevworkstation.features import sessions_mgmt

        monkeypatch.setattr(sessions_mgmt.Titler, "enabled", lambda self: False)


@pytest.fixture
def cfg():
    from gamedevworkstation.config import get_config

    return get_config()
