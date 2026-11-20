"""Real-Windows check (runs in the Windows CI job): `claude` started through child_env() sees the user profile.

`claude auth login` saves the login under %USERPROFILE%\\.claude, so a probe whose child can't see USERPROFILE
(or can't start cmd.exe without SystemRoot/ComSpec) reports "not logged in" however many times the user logs in.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

from gamedevworkstation.features import claude_cli as cli

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

FAKE = r"""@echo off
if "%1"=="--version" (echo 9.9.9 ^(Claude Code^) & exit /b 0)
if "%USERPROFILE%"=="" (echo {"loggedIn": false, "authMethod": "none"} & exit /b 1)
if not exist "%USERPROFILE%\" (echo {"loggedIn": false, "authMethod": "none"} & exit /b 1)
echo {"loggedIn": true, "authMethod": "claude.ai"}
"""


def test_probe_child_sees_the_user_profile_and_reports_logged_in(tmp_path, monkeypatch):
    assert os.environ.get("USERPROFILE"), "the runner has a user profile"
    fake = tmp_path / "claude.cmd"
    fake.write_text(FAKE)
    st = asyncio.run(cli.CliProbe(SimpleNamespace(claude_code={"cli_path": str(fake)}))._probe())
    assert st["installed"] and st["version"] == "9.9.9 (Claude Code)", st
    assert st["logged_in"] is True and st["auth_method"] == "claude.ai", st


def test_child_env_keeps_windows_essentials():
    env = {k.upper(): v for k, v in cli.child_env().items()}
    for name in ("PATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP"):
        assert env.get(name), name
