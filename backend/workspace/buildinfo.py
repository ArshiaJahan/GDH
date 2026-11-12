"""What version is running: version, git commit and build time.

The app build writes `_build_info.json` next to this file (scripts/version.py build-info, run
by scripts/build_mac.sh); PyInstaller bundles it as package data. From source the commit
comes from git directly, so a stale file left by an earlier build never misleads.
"""
from __future__ import annotations

import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from . import __version__

BUILD_INFO = Path(__file__).resolve().parent / "_build_info.json"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


@lru_cache(maxsize=1)
def version_info() -> dict:
    info: dict = {"version": __version__, "git_commit": None, "git_dirty": False, "built_at": None,
                  "frozen": frozen()}
    if frozen():
        try:
            data = json.loads(BUILD_INFO.read_text())
            info.update({k: data.get(k) for k in ("git_commit", "git_dirty", "built_at")})
        except (OSError, ValueError):
            pass
        return info
    from .features.worktrees import GIT_SAFE  # no hooks or fsmonitor: this checkout may be a session folder

    repo = Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(["git", *GIT_SAFE, "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True,
                             text=True, timeout=3)
        if out.returncode == 0:
            info["git_commit"] = out.stdout.strip() or None
            dirty = subprocess.run(["git", *GIT_SAFE, "status", "--porcelain", "--untracked-files=no"], cwd=repo,
                                   capture_output=True, text=True, timeout=3)
            info["git_dirty"] = bool(dirty.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return info
