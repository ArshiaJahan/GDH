"""One-time migrations from the app's previous name, Workspace (0.4.x), to GameDevWorkstation.

This is the only backend module that names the old app: the rename script
(workspace-notes/rename/rename.py) leaves it alone and allowlists it. Nothing here deletes or
changes the old data; Workspace.app 0.4 keeps working with it.

- Data dir: `~/Library/Application Support/Workspace` (Linux `~/.local/share/workspace`) is
  copied to the new data dir on the first start, unless the new one is already in use. The
  database is copied with SQLite's backup API (consistent even while Workspace 0.4 runs) and
  renamed to gamedevworkstation.db; absolute paths into the old folder are pointed at the new
  one in the copy. Subagent worktrees are not copied (a copied git worktree is broken): they stay
  where they are, and records pointing at them keep their old paths.
- Keychain: a key missing from service `GameDevWorkstation` is read from service `Workspace` once
  and copied over (the old entry stays). Accounts already checked, saved or deleted in the new
  app are listed in <data dir>/keychain-migration.json, so a deleted key never comes back.
- Projects: `<project>/.workspace/` is renamed to `.gamedevworkstation/` the first time the
  project is used, unless the new folder exists. It is the harness's own folder.
- Updates: when `~/GameDevWorkstationUpdates` is missing and `~/WorkspaceUpdates` exists, the
  releases are copied over (in the background; not the old app's rollback copies or install
  records, which belong to Workspace.app).
- Skills marked `runtime: workspace` count as native, like `runtime: gamedevworkstation`.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LEGACY_NAME = "Workspace"
LEGACY_KEYCHAIN_SERVICE = "Workspace"
LEGACY_PROJECT_DIR = ".workspace"
LEGACY_UPDATES_DIRNAME = "WorkspaceUpdates"
LEGACY_DB_NAME = "workspace.db"
LEGACY_SKILL_RUNTIME = "workspace"

PROJECT_DIR = ".gamedevworkstation"
UPDATES_DIRNAME = "GameDevWorkstationUpdates"
DB_NAME = "gamedevworkstation.db"
MIGRATION_RECORD = "migration.json"  # in the new data dir once its copy is complete
KEYCHAIN_RECORD = "keychain-migration.json"

# Not copied from the old data dir: the old app's live state, its logs (Linux), our own temp
# folders, and git worktrees (a copy would point at the same .git/worktrees entry as the original).
SKIP_TOP = {"runtime.json", "worktrees", "logs", "updates-tmp", LEGACY_DB_NAME, LEGACY_DB_NAME + "-wal",
            LEGACY_DB_NAME + "-shm", LEGACY_DB_NAME + "-journal", "dev-keys.json.tmp"}
SKIP_UPDATES_TOP = {".previous", "installed.json", ".installed.json.lock"}
REWRITE_SUFFIXES = {".json", ".jsonl"}
REWRITE_MAX_BYTES = 50_000_000


# --------------------------------------------------------------------- paths


def legacy_data_dir(home: Path | None = None, platform: str | None = None) -> Path:
    """The old data dir, as Workspace 0.4 computed it (config.data_dir without GDW_HOME)."""
    if (platform or sys.platform) == "darwin":
        return (home or Path.home()) / "Library" / "Application Support" / LEGACY_NAME
    if home is None and os.environ.get("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]) / LEGACY_SKILL_RUNTIME
    return (home or Path.home()) / ".local" / "share" / LEGACY_SKILL_RUNTIME


def legacy_updates_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / LEGACY_UPDATES_DIRNAME


def default_updates_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / UPDATES_DIRNAME


# ------------------------------------------------------------------ data dir


def _copy_missing(src: str, dst: str) -> str:
    """copytree's copy function: never overwrites a file the new app already has."""
    if not os.path.lexists(dst):
        shutil.copy2(src, dst, follow_symlinks=False)
    return dst


def _rewrite(text: str, prefixes: list[tuple[str, str]], keep: list[str]) -> str:
    """Point old absolute paths at the new data dir, except under `keep` (old worktrees)."""
    marks = []
    for i, k in enumerate(keep):
        mark = f"\x00keep{i}\x00"
        text = text.replace(k, mark)
        marks.append((mark, k))
    for old, new in prefixes:
        text = text.replace(old, new)
    for mark, k in marks:
        text = text.replace(mark, k)
    return text


def _prefixes(old: Path, new: Path) -> tuple[list[tuple[str, str]], list[str]]:
    olds = {str(old)}
    try:
        olds.add(str(old.resolve()))
    except OSError:
        pass
    pairs = [(o.rstrip("/") + "/", str(new).rstrip("/") + "/") for o in sorted(olds, key=len, reverse=True)]
    keep = [o + "worktrees/" for o, _ in pairs]
    return pairs, keep


def _rewrite_db(path: Path, old: Path, new: Path) -> None:
    """In the copied database: old data-dir paths -> new (not worktrees), and trusted project hook
    files under the renamed project folder. Snapshots of user files and search indexes (kept in
    sync by triggers) are left alone."""
    pairs, keep = _prefixes(old, new)
    con = sqlite3.connect(path)
    try:
        rows = con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        virtual = [n for n, sql in rows if (sql or "").upper().startswith("CREATE VIRTUAL TABLE")]
        for name, _sql in rows:
            if name.startswith("sqlite_") or name in virtual or name == "snapshots" \
                    or any(name.startswith(v + "_") for v in virtual):
                continue
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{name}")')]
            # keep-paths -> marks, old -> new, marks -> keep-paths: one nested REPLACE per step
            steps: list[tuple[str, str]] = [(k, f"\x01keep{i}\x01") for i, k in enumerate(keep)]
            steps += pairs + [(f"\x01keep{i}\x01", k) for i, k in enumerate(keep)]
            for col in cols:
                expr = f'"{col}"'
                params: list[Any] = []
                for a, b in steps:
                    expr = f"REPLACE({expr}, ?, ?)"
                    params += [a, b]
                where = " OR ".join(f'instr("{col}", ?) > 0' for _ in pairs)
                try:
                    con.execute(f'UPDATE "{name}" SET "{col}" = {expr} WHERE typeof("{col}")=\'text\' AND ({where})',
                                params + [o for o, _ in pairs])
                except sqlite3.DatabaseError as e:
                    log.warning("migration: couldn't update paths in %s.%s: %s", name, col, e)
        try:
            n = len(LEGACY_PROJECT_DIR) + 1
            con.execute(f"UPDATE OR IGNORE hook_trust SET path = ? || substr(path, {n + 1}) "
                        f"WHERE substr(path, 1, {n}) = ?", [PROJECT_DIR + "/", LEGACY_PROJECT_DIR + "/"])
        except sqlite3.DatabaseError:
            pass  # a database from before hook trust existed
        con.commit()
    finally:
        con.close()


def _copy_db(src: Path, dst: Path) -> None:
    """Copy the database to `dst`.migrating. Closed cleanly (no -wal file): a plain file copy, so the
    old folder isn't touched at all. Otherwise (Workspace 0.4 is running, or didn't close cleanly):
    SQLite's online backup, consistent with the WAL; SQLite may then leave its -wal/-shm side
    files next to the old database, as the old app itself does."""
    tmp = dst.with_name(dst.name + ".migrating")
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm"), Path(str(tmp) + "-journal")):
        if p.exists():
            p.unlink()  # our own half-finished copy from an interrupted start
    if not Path(str(src) + "-wal").exists():
        shutil.copy2(src, tmp)
        c = sqlite3.connect(tmp)
        try:
            ok = c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        except sqlite3.DatabaseError:
            ok = False
        finally:
            c.close()
        if ok:
            return
        tmp.unlink()  # changed while we copied: take a proper backup instead
    try:
        s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        s.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError:  # read-only open can fail on a WAL database; a plain one won't
        s = sqlite3.connect(src)
    d = sqlite3.connect(tmp)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def migrate_data_dir(old: Path, new: Path) -> bool:
    """Copy the old data dir into the new one, once. True when a copy was made.

    Skipped when there is nothing to copy, the copy was done before, or the new data dir already
    has a database (it is in use). Files the new dir already has are never overwritten. An
    interrupted copy is finished on the next start: the database is put in place last."""
    if not old.is_dir() or (new / MIGRATION_RECORD).exists() or (new / DB_NAME).exists():
        return False
    if old.resolve() == new.resolve():
        return False
    started = time.monotonic()
    log.info("migration: copying %s to %s (the old folder is kept)", old, new)
    new.mkdir(parents=True, exist_ok=True)
    shutil.copytree(old, new, symlinks=True, dirs_exist_ok=True, copy_function=_copy_missing,
                    ignore=lambda d, names: [n for n in names if Path(d) == old and n in SKIP_TOP])
    pairs, keep = _prefixes(old, new)
    for root, _dirs, files in os.walk(new):
        for f in files:
            p = Path(root) / f
            if p.suffix not in REWRITE_SUFFIXES or p.name == MIGRATION_RECORD or p.is_symlink():
                continue
            try:
                if p.stat().st_size > REWRITE_MAX_BYTES:
                    continue
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            new_text = _rewrite(text, pairs, keep)
            if new_text != text:
                p.write_text(new_text, encoding="utf-8")
    db_src = old / LEGACY_DB_NAME
    if db_src.is_file():
        _copy_db(db_src, new / DB_NAME)
        tmp = new / (DB_NAME + ".migrating")
        _rewrite_db(tmp, old, new)
        os.replace(tmp, new / DB_NAME)
    record = {"from": str(old), "at": time.time(), "worktrees_left_in": str(old / "worktrees")}
    (new / MIGRATION_RECORD).write_text(json.dumps(record, indent=2) + "\n")
    log.info("migration: data copied from %s in %.1fs", old, time.monotonic() - started)
    return True


# ------------------------------------------------------------------ keychain


def _keychain_record(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text())
        return {str(a) for a in data.get("accounts", [])} if isinstance(data, dict) else set()
    except (OSError, ValueError):
        return set()


def keychain_mark(record: Path, account: str) -> None:
    """The new app owns `account` from now on: never look it up under the old service again."""
    done = _keychain_record(record)
    if account in done:
        return
    record.parent.mkdir(parents=True, exist_ok=True)
    tmp = record.with_name(record.name + ".tmp")
    tmp.write_text(json.dumps({"accounts": sorted(done | {account})}, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, record)


def keychain_fallback(kr: Any, service: str, account: str, record: Path) -> str | None:
    """`account` is missing from `service`: read it from the old service once and copy it over
    (the old entry stays, for Workspace 0.4). `kr` is the keyring module (or a stand-in)."""
    if account in _keychain_record(record):
        return None
    try:
        v = kr.get_password(LEGACY_KEYCHAIN_SERVICE, account)
    except Exception:  # no keychain backend, or access refused
        return None
    if v:
        try:
            kr.set_password(service, account, v)
            log.info("migration: copied Keychain entry %s from service %s to %s", account,
                     LEGACY_KEYCHAIN_SERVICE, service)
        except Exception as e:  # still usable this time; try copying again next time
            log.warning("migration: couldn't copy Keychain entry %s to %s: %s", account, service, e)
            return v
    keychain_mark(record, account)
    return v or None


# ------------------------------------------------------------------ projects

_projects_lock = threading.Lock()


def migrate_project_dir(folder: str | Path | None) -> bool:
    """Rename `<folder>/.workspace` to `.gamedevworkstation` unless the new folder exists.
    True when it was moved. Never raises."""
    if not folder:
        return False
    try:
        root = Path(folder).expanduser()
        old, new = root / LEGACY_PROJECT_DIR, root / PROJECT_DIR
        with _projects_lock:
            if os.path.lexists(new) or old.is_symlink() or not old.is_dir():
                return False
            os.rename(old, new)
        log.info("migration: renamed %s to %s (the harness's project folder)", old, new)
        return True
    except OSError as e:
        log.warning("migration: couldn't rename %s/%s: %s", folder, LEGACY_PROJECT_DIR, e)
        return False


# ------------------------------------------------------------------- updates


def migrate_updates_dir(old: Path, new: Path) -> bool:
    """Copy the old updates folder's releases into a missing new one. True when copied.
    Copies into a hidden sibling first, so a half copy never looks like the updates folder."""
    if os.path.lexists(new) or not old.is_dir():
        return False
    stage = new.with_name("." + new.name + ".migrating")
    log.info("migration: copying releases from %s to %s (the old folder is kept)", old, new)
    shutil.copytree(old, stage, symlinks=True, dirs_exist_ok=True, copy_function=_copy_missing,
                    ignore=lambda d, names: [n for n in names if Path(d) == old and n in SKIP_UPDATES_TOP])
    if os.path.lexists(new):  # created meanwhile: leave both as they are
        return False
    os.rename(stage, new)
    log.info("migration: releases copied to %s", new)
    return True


# ------------------------------------------------------------------- startup


def run_startup_migrations(background: bool = True) -> None:
    """Before the backend opens its data: copy the old data dir, then (in the background) the old
    updates folder. Skipped with GDW_HOME (an explicit data dir: development and tests)."""
    if os.environ.get("GDW_HOME"):
        return
    from .config import data_dir

    try:
        migrate_data_dir(legacy_data_dir(), data_dir())
    except Exception:
        log.exception("migration: copying the old data folder failed; starting with what is there")

    if os.environ.get("GDW_UPDATES_DIR"):
        return
    try:
        from .config import get_config
        from .features.updates import updates_dir

        target = updates_dir(get_config())
    except Exception:
        log.exception("migration: couldn't read the updates folder setting")
        return
    if target != default_updates_dir():
        return  # a folder chosen in config.toml is used as it is

    def copy() -> None:
        try:
            migrate_updates_dir(legacy_updates_dir(), target)
        except Exception:
            log.exception("migration: copying the old updates folder failed")

    if background:
        threading.Thread(target=copy, name="migrate-updates", daemon=True).start()
    else:
        copy()
