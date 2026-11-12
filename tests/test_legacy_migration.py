"""One-time migrations from Workspace 0.4 (legacy.py). Everything runs in tmp folders: the
Keychain is a dict stand-in (the keyring module's functions are patched), HOME-like folders are
tmp_path, and conftest keeps GDW_HOME / GDW_NO_KEYCHAIN / GDW_UPDATES_DIR isolated."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

import pytest

from gamedevworkstation import legacy
from gamedevworkstation.db import DB


def tree_digest(root: Path) -> dict[str, str]:
    """Every file under root with its content hash: proves a folder was left untouched."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = Path(dirpath) / f
            if not p.is_symlink():
                out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ------------------------------------------------------------------- data dir


@pytest.fixture
def old_data(tmp_path):
    """A Workspace 0.4 data dir with a database, media, a subagent record and a worktree."""
    old = tmp_path / "Library" / "Application Support" / "Workspace"
    (old / "media").mkdir(parents=True)
    (old / "media" / "a.png").write_bytes(b"png")
    (old / "config.toml").write_text("# my settings\n")
    (old / "runtime.json").write_text('{"port": 1}')
    (old / "worktrees" / "s1" / "sub_a").mkdir(parents=True)
    (old / "worktrees" / "s1" / "sub_a" / "f.txt").write_text("unit work")
    (old / "subagents").mkdir()
    (old / "subagents" / "sub_a.json").write_text(json.dumps(
        {"worktree": f"{old}/worktrees/s1/sub_a", "transcript": f"{old}/media/a.png"}))
    db = DB(old / "workspace.db")
    db.execute("INSERT INTO sessions (id, created_at, updated_at, model, folder) VALUES ('s1', 1, 1, 'm', '/proj')")
    db.execute("INSERT INTO items (id, session_id, kind, source, path, created_at) VALUES (?, 's1', 'media', 'user', ?, 1)",
               ["i1", f"{old}/media/a.png"])
    db.execute("INSERT INTO items (id, session_id, kind, source, path, size, created_at) "
               "VALUES (?, 's1', 'file', 'agent', ?, 7, 1)", ["i2", f"{old}/worktrees/s1/sub_a/f.txt"])
    db.execute("INSERT INTO messages (id, session_id, role, content, created_at) VALUES ('m1', 's1', 'user', ?, 1)",
               [json.dumps([{"type": "text", "text": f"see {old}/media/a.png"}])])
    db.execute("INSERT INTO hook_trust (project, path, kind, sha256, approved_at) VALUES ('/proj', '.workspace/hooks.toml', 'file', 'abc', 1)")
    db.close()
    return old


def test_data_dir_copied_once_and_old_kept(old_data, tmp_path, caplog):
    new = tmp_path / "Library" / "Application Support" / "GameDevWorkstation"
    before = tree_digest(old_data)
    with caplog.at_level(logging.INFO, logger="gamedevworkstation.legacy"):
        assert legacy.migrate_data_dir(old_data, new) is True
    assert tree_digest(old_data) == before  # the old folder is never changed
    assert "copying" in caplog.text
    assert (new / "gamedevworkstation.db").is_file() and not (new / "workspace.db").exists()
    assert (new / "config.toml").read_text() == (old_data / "config.toml").read_text()
    assert (new / "media" / "a.png").read_bytes() == b"png"
    assert not (new / "runtime.json").exists()  # the old app's live state
    assert not (new / "worktrees").exists()  # a copied git worktree would be broken
    assert json.loads((new / "migration.json").read_text())["from"] == str(old_data)

    db = DB(new / "gamedevworkstation.db")
    try:
        assert db.one("SELECT path FROM items WHERE id='i1'")["path"] == f"{new}/media/a.png"
        # paths into old worktrees keep pointing where the worktree really is
        assert db.one("SELECT path FROM items WHERE id='i2'")["path"] == f"{old_data}/worktrees/s1/sub_a/f.txt"
        assert db.one("SELECT size FROM items WHERE id='i2'")["size"] == 7  # numbers stay numbers
        assert f"{new}/media/a.png" in db.one("SELECT content FROM messages WHERE id='m1'")["content"]
        assert db.one("SELECT path FROM hook_trust")["path"] == ".gamedevworkstation/hooks.toml"
        assert db.one("SELECT folder FROM sessions WHERE id='s1'")["folder"] == "/proj"
    finally:
        db.close()
    sub = json.loads((new / "subagents" / "sub_a.json").read_text())
    assert sub == {"worktree": f"{old_data}/worktrees/s1/sub_a", "transcript": f"{new}/media/a.png"}

    # second start: nothing happens, even if the old folder changed meanwhile
    (old_data / "media" / "b.png").write_bytes(b"later")
    assert legacy.migrate_data_dir(old_data, new) is False
    assert not (new / "media" / "b.png").exists()


def test_data_dir_not_copied_over_a_new_dir_in_use(old_data, tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    (new / "gamedevworkstation.db").write_bytes(b"")
    assert legacy.migrate_data_dir(old_data, new) is False
    assert not (new / "config.toml").exists()


def test_data_dir_copy_never_overwrites_and_finishes_an_interrupted_copy(old_data, tmp_path):
    new = tmp_path / "new"
    (new / "logs").mkdir(parents=True)  # e.g. created by logging before the migration ran
    (new / "config.toml").write_text("# mine\n")  # an interrupted earlier copy, or the user's
    assert legacy.migrate_data_dir(old_data, new) is True
    assert (new / "config.toml").read_text() == "# mine\n"
    assert (new / "gamedevworkstation.db").is_file()


def test_nothing_to_migrate(tmp_path):
    assert legacy.migrate_data_dir(tmp_path / "missing", tmp_path / "new") is False
    assert not (tmp_path / "new").exists()


def test_legacy_paths(tmp_path):
    assert legacy.legacy_data_dir(tmp_path, "darwin") == tmp_path / "Library" / "Application Support" / "Workspace"
    assert legacy.legacy_data_dir(tmp_path, "linux") == tmp_path / ".local" / "share" / "workspace"
    assert legacy.legacy_updates_dir(tmp_path) == tmp_path / "WorkspaceUpdates"
    assert legacy.default_updates_dir(tmp_path) == tmp_path / "GameDevWorkstationUpdates"


def test_startup_migrations_skip_an_explicit_data_dir(monkeypatch, tmp_path):
    """GDW_HOME (tests, development) means: never look at the real user folders."""
    called = []
    monkeypatch.setattr(legacy, "migrate_data_dir", lambda *a: called.append(a))
    monkeypatch.setattr(legacy, "migrate_updates_dir", lambda *a: called.append(a))
    legacy.run_startup_migrations(background=False)
    assert called == []


def test_startup_migrations_use_home(monkeypatch, tmp_path, old_data):
    """Without GDW_HOME: old -> new data dir and old -> new updates folder, under a tmp HOME."""
    import sys

    monkeypatch.delenv("GDW_HOME")
    monkeypatch.delenv("GDW_UPDATES_DIR")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    (tmp_path / "WorkspaceUpdates" / "0.4.0").mkdir(parents=True)
    (tmp_path / "WorkspaceUpdates" / "latest.json").write_text('{"version": "0.4.0"}')
    from gamedevworkstation import config

    config.get_config.cache_clear()
    legacy.run_startup_migrations(background=False)
    new = tmp_path / "Library" / "Application Support" / "GameDevWorkstation"
    assert (new / "gamedevworkstation.db").is_file() and (new / "migration.json").is_file()
    assert (tmp_path / "GameDevWorkstationUpdates" / "latest.json").is_file()
    config.get_config.cache_clear()


# ------------------------------------------------------------------- keychain


class FakeKeyring:
    """Stands in for the keyring module: the real Keychain is never touched."""

    def __init__(self):
        self.d: dict[tuple[str, str], str] = {}

    def get_password(self, service, account):
        return self.d.get((service, account))

    def set_password(self, service, account, value):
        self.d[(service, account)] = value

    def delete_password(self, service, account):
        self.d.pop((service, account), None)


@pytest.fixture
def kr(monkeypatch):
    import keyring

    fake = FakeKeyring()
    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, getattr(fake, name))
    monkeypatch.setenv("GDW_NO_KEYCHAIN", "0")  # the code path that uses the (patched) keyring
    return fake


def test_keychain_falls_back_to_old_service_and_copies(kr):
    from gamedevworkstation import config

    kr.d[("Workspace", "anthropic:default")] = "sk-old-1234"
    assert config.get_key("anthropic") == "sk-old-1234"
    assert kr.d[("GameDevWorkstation", "anthropic:default")] == "sk-old-1234"
    assert kr.d[("Workspace", "anthropic:default")] == "sk-old-1234"  # old entry kept
    # MCP secrets go through the same fallback
    kr.d[("Workspace", "mcp:gh:TOKEN")] = "ghp_1"
    assert config.get_secret("mcp:gh:TOKEN") == "ghp_1"
    assert kr.d[("GameDevWorkstation", "mcp:gh:TOKEN")] == "ghp_1"


def test_keychain_new_service_wins(kr):
    from gamedevworkstation import config

    kr.d[("Workspace", "openai:default")] = "old"
    kr.d[("GameDevWorkstation", "openai:default")] = "new"
    assert config.get_key("openai") == "new"


def test_deleted_key_does_not_come_back_from_old_service(kr):
    from gamedevworkstation import config

    kr.d[("Workspace", "openai:work")] = "sk-old"
    config.delete_key("openai", "work")
    assert config.get_key("openai", "work") is None
    assert ("GameDevWorkstation", "openai:work") not in kr.d
    assert kr.d[("Workspace", "openai:work")] == "sk-old"  # never deleted from the old service
    kr.d[("Workspace", "mcp:x:A")] = "v"
    config.delete_secret("mcp:x:A")
    assert config.get_secret("mcp:x:A") is None


def test_saved_key_is_owned_by_new_service(kr):
    from gamedevworkstation import config

    kr.d[("Workspace", "elevenlabs:default")] = "old"
    config.set_key("elevenlabs", "default", "new")
    config.delete_key("elevenlabs", "default")
    assert config.get_key("elevenlabs") is None


def test_keychain_checked_once(kr, tmp_path):
    record = tmp_path / "k.json"
    assert legacy.keychain_fallback(kr, "GameDevWorkstation", "a:b", record) is None
    kr.d[("Workspace", "a:b")] = "added later in the old app"
    assert legacy.keychain_fallback(kr, "GameDevWorkstation", "a:b", record) is None


def test_keychain_copy_failure_still_returns_key_and_retries(tmp_path):
    class Locked(FakeKeyring):
        def set_password(self, service, account, value):
            raise RuntimeError("locked")

    k = Locked()
    k.d[("Workspace", "a:b")] = "v"
    record = tmp_path / "k.json"
    assert legacy.keychain_fallback(k, "GameDevWorkstation", "a:b", record) == "v"
    assert not record.exists()  # not marked: copied on a later start


def test_no_keychain_mode_never_calls_keyring(monkeypatch):
    """GDW_NO_KEYCHAIN=1 (conftest): neither service is read."""
    import keyring

    def boom(*a, **k):
        raise AssertionError("keyring must not be called with GDW_NO_KEYCHAIN=1")

    monkeypatch.setattr(keyring, "get_password", boom)
    from gamedevworkstation import config

    assert config.get_key("anthropic", "work") is None
    assert config.get_secret("mcp:x:A") is None


# ------------------------------------------------------------------- projects


def test_project_dir_moved_on_first_use(tmp_path, caplog):
    proj = tmp_path / "game"
    (proj / ".workspace" / "discoveries").mkdir(parents=True)
    (proj / ".workspace" / "hooks.toml").write_text("x = 1\n")
    with caplog.at_level(logging.INFO, logger="gamedevworkstation.legacy"):
        assert legacy.migrate_project_dir(proj) is True
    assert "renamed" in caplog.text
    assert (proj / ".gamedevworkstation" / "hooks.toml").read_text() == "x = 1\n"
    assert (proj / ".gamedevworkstation" / "discoveries").is_dir()
    assert not (proj / ".workspace").exists()
    assert legacy.migrate_project_dir(proj) is False


def test_project_dir_left_alone_when_new_exists(tmp_path):
    proj = tmp_path / "game"
    (proj / ".workspace").mkdir(parents=True)
    (proj / ".workspace" / "notes.md").write_text("old")
    (proj / ".gamedevworkstation").mkdir()
    assert legacy.migrate_project_dir(proj) is False
    assert (proj / ".workspace" / "notes.md").read_text() == "old"
    assert legacy.migrate_project_dir(None) is False
    assert legacy.migrate_project_dir(tmp_path / "missing") is False


def test_project_dir_symlink_not_followed(tmp_path):
    proj, elsewhere = tmp_path / "game", tmp_path / "elsewhere"
    proj.mkdir()
    elsewhere.mkdir()
    (proj / ".workspace").symlink_to(elsewhere)
    assert legacy.migrate_project_dir(proj) is False
    assert (proj / ".workspace").is_symlink()


def test_turn_moves_project_dir(tmp_path):
    """A turn in a session whose folder still has the old project folder moves it first."""
    from fastapi.testclient import TestClient

    from gamedevworkstation.app import AppState
    from gamedevworkstation.providers.fake import FakeProvider
    from gamedevworkstation.server import create_app

    proj = tmp_path / "game"
    (proj / ".workspace").mkdir(parents=True)
    (proj / ".workspace" / "notes.md").write_text("n")
    s = AppState(db_path=tmp_path / "s.db")
    s.providers.override("anthropic", "default", FakeProvider())
    h = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", s)) as c:
        sid = c.post("/api/sessions", json={"folder": str(proj)}, headers=h).json()["id"]
        c.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}, headers=h)
        import time

        for _ in range(100):
            if (proj / ".gamedevworkstation").exists():
                break
            time.sleep(0.05)
    assert (proj / ".gamedevworkstation" / "notes.md").read_text() == "n"
    assert not (proj / ".workspace").exists()


def test_skill_runtime_old_name_is_native():
    from gamedevworkstation.skills import is_native

    assert is_native("x", {"runtime": "workspace"})
    assert is_native("x", {"runtime": "gamedevworkstation"})
    assert not is_native("x", {"runtime": "claude-code"})


# ------------------------------------------------------------------- updates


def test_updates_folder_copied_when_new_missing(tmp_path):
    old, new = tmp_path / "WorkspaceUpdates", tmp_path / "GameDevWorkstationUpdates"
    (old / "0.4.0" / "Workspace.app" / "Contents").mkdir(parents=True)
    (old / "0.4.0" / "release.json").write_text('{"version": "0.4.0"}')
    (old / "latest.json").write_text('{"version": "0.4.0"}')
    (old / "installed.json").write_text('{"installs": {}}')
    (old / ".previous" / "Workspace-0.3.0.app").mkdir(parents=True)
    before = tree_digest(old)
    assert legacy.migrate_updates_dir(old, new) is True
    assert tree_digest(old) == before
    assert (new / "0.4.0" / "release.json").is_file() and (new / "latest.json").is_file()
    assert not (new / "installed.json").exists() and not (new / ".previous").exists()
    assert not (tmp_path / ".GameDevWorkstationUpdates.migrating").exists()
    (old / "0.5.0").mkdir()
    assert legacy.migrate_updates_dir(old, new) is False  # once only
    assert not (new / "0.5.0").exists()


def test_updates_folder_not_touched_when_new_exists_or_old_missing(tmp_path):
    old, new = tmp_path / "WorkspaceUpdates", tmp_path / "GameDevWorkstationUpdates"
    assert legacy.migrate_updates_dir(old, new) is False and not new.exists()
    old.mkdir()
    (old / "latest.json").write_text("{}")
    new.mkdir()
    assert legacy.migrate_updates_dir(old, new) is False
    assert list(new.iterdir()) == []


def test_db_copy_is_consistent_while_old_app_writes(tmp_path):
    """The old app may still run: the copy comes from SQLite's backup API, WAL included."""
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    con = sqlite3.connect(old / "workspace.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES ('in the wal')")
    con.commit()  # still open: the row may only be in workspace.db-wal
    try:
        assert legacy.migrate_data_dir(old, new) is True
    finally:
        con.close()
    assert (old / "workspace.db").exists()
    c2 = sqlite3.connect(new / "gamedevworkstation.db")
    assert c2.execute("SELECT v FROM t").fetchall() == [("in the wal",)]
    c2.close()
