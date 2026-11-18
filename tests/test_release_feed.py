"""Updates from GitHub Releases (release_feed.py) and automatic installs: the feed downloads the
asset for this platform into the updates folder, Windows releases are installers, and the
updater installs a pending version by itself at most once."""
import asyncio
import io
import json
import os
import plistlib
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.features import release_feed as F
from gamedevworkstation.features import updates as U
from gamedevworkstation.server import create_app


def _zipped_app(version: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("GameDevWorkstation.app/Contents/Info.plist", plistlib.dumps(
            {"CFBundleShortVersionString": version, "CFBundleIdentifier": U.BUNDLE_ID, "CFBundleExecutable": "GameDevWorkstation"}))
        z.writestr("GameDevWorkstation.app/Contents/MacOS/GameDevWorkstation", "#!/bin/bash\n")
    return buf.getvalue()


def _fake_github(version: str, files: dict[str, bytes], **extra):
    calls: list[str] = []
    release = {"tag_name": f"v{version}", "body": "- New things", "published_at": "2026-11-18T00:00:00Z",
               "target_commitish": "abcdef1234", "draft": False, "prerelease": False,
               "assets": [{"name": n, "size": len(b), "browser_download_url": f"https://dl/{n}"} for n, b in files.items()],
               **extra}

    def fetch(url: str) -> bytes:
        calls.append(url)
        if url == F.API.format(repo="me/repo"):
            return json.dumps(release).encode()
        return files[url.removeprefix("https://dl/")]
    return fetch, calls


def test_asset_names():
    assert F.asset_name("1.2.3", "darwin") == "GameDevWorkstation-1.2.3-macos-arm64.zip"
    assert F.asset_name("1.2.3", "win32") == "GameDevWorkstation-1.2.3-x64-setup.exe"
    assert F.asset_name("1.2.3", "linux") is None


def test_latest_release_ignores_drafts_prereleases_and_errors():
    fetch, _ = _fake_github("9.0.0", {}, prerelease=True)
    assert F.latest_release("me/repo", fetch) is None

    def boom(url):
        raise OSError("offline")
    assert F.latest_release("me/repo", boom) is None
    fetch, _ = _fake_github("9.0.0", {"a.zip": b"x"})
    rel = F.latest_release("me/repo", fetch)
    assert rel["version"] == "9.0.0" and rel["assets"]["a.zip"]["size"] == 1 and rel["git_commit"] == "abcdef1"


def test_mac_release_is_unpacked_into_the_updates_folder(tmp_path):
    name = F.asset_name("99.0.0", "darwin")
    fetch, calls = _fake_github("99.0.0", {name: _zipped_app("99.0.0")})
    feed = F.ReleaseFeed("me/repo", 3600, fetch)
    rec = feed.poll(tmp_path, "0.1.0", is_newer=U.is_newer, write_json=U.write_json_atomic, platform="darwin")
    assert rec["app"] == "99.0.0/GameDevWorkstation.app" and rec["source"] == "github"
    latest = U.validate_release(tmp_path, U.read_json(tmp_path / "latest.json"))
    assert latest["version"] == "99.0.0" and latest["notes"] == "- New things"
    assert U.bundle_info(Path(latest["app_path"]))["version"] == "99.0.0"
    assert not list((tmp_path / ".download").glob("*"))  # the zip and .part are gone
    assert not feed.due()
    # Already downloaded: the next poll asks GitHub but doesn't download again.
    feed.poll(tmp_path, "0.1.0", is_newer=U.is_newer, write_json=U.write_json_atomic, platform="darwin")
    assert sum(c.startswith("https://dl/") for c in calls) == 1


def test_windows_release_is_an_installer(tmp_path):
    name = F.asset_name("99.0.0", "win32")
    fetch, _ = _fake_github("99.0.0", {name: b"MZ fake installer"})
    rec = F.ReleaseFeed("me/repo", 3600, fetch).poll(tmp_path, "0.1.0", is_newer=U.is_newer,
                                                      write_json=U.write_json_atomic, platform="win32")
    assert rec["installer"] == f"99.0.0/{name}"
    latest = U.validate_release(tmp_path, U.read_json(tmp_path / "latest.json"))
    assert latest["app_path"].endswith(name) and Path(latest["app_path"]).read_bytes() == b"MZ fake installer"
    # An installer path that leaves the folder, or isn't an .exe, is refused.
    assert U.validate_release(tmp_path, {"version": "99.0.0", "installer": "../evil.exe"}) is None
    assert U.validate_release(tmp_path, {"version": "99.0.0", "installer": "99.0.0/release.json"}) is None


def test_not_newer_or_wrong_size_downloads_nothing(tmp_path):
    name = F.asset_name("0.0.1", "win32")
    fetch, calls = _fake_github("0.0.1", {name: b"x"})
    assert F.ReleaseFeed("me/repo", 3600, fetch).poll(tmp_path, "0.1.0", is_newer=U.is_newer,
                                                       write_json=U.write_json_atomic, platform="win32") is None
    assert calls == [F.API.format(repo="me/repo")]
    name = F.asset_name("99.0.0", "win32")
    fetch, _ = _fake_github("99.0.0", {name: b"short"})
    real = fetch

    def lying(url):
        data = real(url)
        if url.startswith("https://api"):
            d = json.loads(data)
            d["assets"][0]["size"] = 999
            return json.dumps(d).encode()
        return data
    feed = F.ReleaseFeed("me/repo", 3600, lying)
    assert feed.poll(tmp_path, "0.1.0", is_newer=U.is_newer, write_json=U.write_json_atomic, platform="win32") is None
    assert "999" in feed.last_error and not (tmp_path / "latest.json").exists()


def test_windows_helper_script_quotes_paths():
    s = U.windows_helper_script(app_pid=12, backend_pid=34, installer=Path("C:/Users/O'Neil/x-setup.exe"),
                                app_exe=Path("C:/Apps/GameDevWorkstation.exe"))
    assert "$AppPid = 12" in s and "$BackendPid = 34" in s
    assert "'C:/Users/O''Neil/x-setup.exe'" in s and "-ArgumentList '/S' -Wait" in s
    assert "Start-Process -FilePath $AppExe" in s


def test_feed_is_off_for_local_builds_and_on_when_configured(tmp_path):
    s = AppState(db_path=tmp_path / "t.db")
    assert U.Updater(s).feed is None  # from source: no channel
    s.config.updates["github"] = True
    s.config.updates["github_repo"] = "me/repo"
    up = U.Updater(s)
    assert up.feed is not None and up.feed.repo == "me/repo" and up.feed.interval_s == 3600


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "t.db")
    with TestClient(create_app("t", s)):
        yield s, Path(os.environ["GDW_UPDATES_DIR"])


def _pending(monkeypatch, up):
    monkeypatch.setattr(up, "pending_update", lambda: {"latest": "99.0.0", "install_supported": True})


def test_auto_install_waits_for_idle_and_tries_each_version_once(env, monkeypatch):
    s, _ = env
    up = U.Updater(s)
    _pending(monkeypatch, up)
    calls: list = []

    async def install(version, rollback=False):
        calls.append(version)
        raise HTTPException(400, "the signature doesn't verify")
    monkeypatch.setattr(up, "install", install)
    run = lambda: asyncio.run(up.maybe_auto_install())  # noqa: E731
    assert run() is None and calls == []  # just started
    up.started_at = time.time() - 120
    monkeypatch.setattr(up, "busy", lambda: 1)
    assert run() is None and calls == []  # a session is running
    monkeypatch.setattr(up, "busy", lambda: 0)
    assert run() is None and calls == ["99.0.0"]  # tried, failed
    assert run() is None and calls == ["99.0.0"]  # never again for this version
    assert U.Updater(s).auto_install_enabled()


def test_auto_install_can_be_turned_off(env, monkeypatch):
    s, _ = env
    s.config.updates["auto_install"] = False
    up = U.Updater(s)
    up.started_at = 0
    _pending(monkeypatch, up)
    monkeypatch.setattr(up, "install", lambda *a, **k: pytest.fail("installed"))
    assert asyncio.run(up.maybe_auto_install()) is None
    assert up.status()["auto_install"] is False and up.status()["github"] is None
