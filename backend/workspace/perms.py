"""Owner-only permissions for the app's own data: the database (chat history, approvals), config,
runtime.json (port and token) and logs.

At startup the data and log folders become 0700 and those files 0600. A folder at 0700 also
covers everything created inside it later (media, transcripts, tool outputs), whatever its own
mode. There is no process-wide umask: commands, terminals and MCP servers inherit the backend's
umask and must keep creating files in the user's projects with normal permissions.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import stat
from pathlib import Path

log = logging.getLogger("workspace.perms")

PRIVATE_FILES = ("workspace.db", "workspace.db-*", "*.db", "*.db-wal", "*.db-shm", "config.toml", "config.toml.*",
                 "runtime.json", "*.log", "*.log.*")


def _chmod(p: Path, mode: int) -> None:
    try:
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode) or stat.S_IMODE(st.st_mode) == mode:
            return
        os.chmod(p, mode)
    except OSError as e:
        log.warning("couldn't restrict %s: %s", p, e)


def harden(*folders: Path) -> None:
    """chmod each folder 0700 and the app's own files directly inside it 0600 (not recursive:
    subagent worktrees hold the user's code, whose modes must stay as they are)."""
    for d in folders:
        if not d.is_dir():
            continue
        _chmod(d, 0o700)
        for f in d.iterdir():
            if f.is_file() and not f.is_symlink() and any(fnmatch.fnmatch(f.name, pat) for pat in PRIVATE_FILES):
                _chmod(f, 0o600)


def harden_app_dirs() -> None:
    from .config import data_dir, logs_dir

    harden(data_dir(), logs_dir())
