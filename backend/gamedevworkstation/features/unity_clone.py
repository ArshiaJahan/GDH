"""Batch Unity jobs on a copy of the project while the Editor holds it ([unity].clone_when_open,
research notes §2.5 action 3).

The copy lives in the user's cache folder (~/Library/Caches/GameDevWorkstation/unity-clones/
<sha1(project)[:12]>/; tests and dev runs with GDW_HOME use <GDW_HOME>/cache/unity-clones, and
GDW_UNITY_CLONES overrides both). The first run makes it with `cp -cR` (an APFS clone: instant
and no extra disk until files change, Library/ included so the batch import is warm); later runs
bring only Assets/, Packages/ and ProjectSettings/ up to date with `rsync -a --delete`. The copy
is what's on disk: unsaved Editor changes aren't in it, and results say so (CLONE_NOTE).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

CLONE_ENV = "GDW_UNITY_CLONES"
SYNC_DIRS = ("Assets", "Packages", "ProjectSettings")
MARKER = ".gdw-clone.json"
CLONE_NOTE = "on a copy of the files on disk (unsaved Editor changes not included)"
CP = "/bin/cp"
RSYNC = "/usr/bin/rsync"


class CloneError(RuntimeError):
    pass


def clones_root() -> Path:
    if env := os.environ.get(CLONE_ENV):
        return Path(env).expanduser()
    if env := os.environ.get("GDW_HOME"):
        return Path(env) / "cache" / "unity-clones"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "GameDevWorkstation" / "unity-clones"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "gamedevworkstation" / "unity-clones"


def clone_dir(project: Path | str) -> Path:
    src = str(Path(project).expanduser().resolve())
    return clones_root() / hashlib.sha1(src.encode()).hexdigest()[:12]


_LOCKS: dict[str, asyncio.Lock] = {}


def lock(project: Path | str) -> asyncio.Lock:
    """One sync + job at a time per clone."""
    key = str(clone_dir(project))
    if key not in _LOCKS:
        _LOCKS[key] = asyncio.Lock()
    return _LOCKS[key]


async def _exec(argv: list[str], timeout_s: float) -> tuple[int | None, str]:
    """Run argv (no shell); (exit code or None on timeout, output tail). Tests replace this."""
    try:
        p = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                 stdin=asyncio.subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return 127, str(e)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout_s)
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        await p.wait()
        if isinstance(e, asyncio.CancelledError):
            raise
        return None, f"timed out after {timeout_s:.0f}s"
    return p.returncode, out.decode(errors="replace")[-4000:]


def _inside_root(p: Path) -> bool:
    try:
        return p.resolve().parent == clones_root().resolve()
    except OSError:
        return False


def _check_symlinks(src: Path, dst: Path) -> None:
    """Refuse links that could let a job or sync write outside its copy; never follow directories."""
    def refuse(path: Path, root: Path) -> None:
        raise CloneError(f"project uses symlinks ({path.relative_to(root)}): "
                         "running on a copy could write into the linked folder")

    for name in SYNC_DIRS:
        source = src / name
        if source.is_symlink():
            refuse(source, src)
        if (dst / name).is_symlink():
            refuse(dst / name, dst)
        for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
            for name in (*dirnames, *filenames):
                p = Path(dirpath) / name
                if p.is_symlink() and not p.resolve().is_relative_to(src):
                    refuse(p, src)


async def sync_clone(project: Path | str, *, timeout_s: float = 1800) -> dict:
    """Make or refresh the copy. {"clone": path, "first": bool, "commands": [argv, …]}; raises
    CloneError. The caller holds lock(project)."""
    src = Path(project).expanduser().resolve()
    dst = clone_dir(src)
    cmds: list[list[str]] = []
    await asyncio.to_thread(_check_symlinks, src, dst)
    try:
        marker = json.loads((dst / MARKER).read_text())
    except (OSError, ValueError):
        marker = None
    first = not isinstance(marker, dict)
    if first:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if os.stat(src).st_dev != os.stat(dst.parent).st_dev:
            raise CloneError("the project is on a different volume than the clone cache, "
                             "so an APFS clone would be a full copy")
        if dst.exists():  # a copy that never finished: it's ours (inside the clones folder), start over
            if not _inside_root(dst):
                raise CloneError(f"unexpected clone folder {dst}")
            await asyncio.to_thread(shutil.rmtree, dst, True)
        argv = [CP, "-cR", str(src), str(dst)]
        cmds.append(argv)
        code, out = await _exec(argv, timeout_s)
        if code != 0:
            if dst.exists() and _inside_root(dst):
                await asyncio.to_thread(shutil.rmtree, dst, True)
            raise CloneError(f"`cp -cR` failed ({'timeout' if code is None else f'exit {code}'}): {out.strip()[-300:]}")
        # The Editor's lockfile and scratch files came along; a batch Unity on the copy needs neither.
        await asyncio.to_thread(shutil.rmtree, dst / "Temp", True)
    else:
        for d in SYNC_DIRS:
            if not (src / d).is_dir():
                continue
            argv = [RSYNC, "-a", "--delete", f"{src / d}/", f"{dst / d}/"]
            cmds.append(argv)
            code, out = await _exec(argv, timeout_s)
            if code != 0:
                raise CloneError(f"`rsync` of {d}/ failed ({'timeout' if code is None else f'exit {code}'}): "
                                 f"{out.strip()[-300:]}")
    try:
        meta = {"source": str(src), "created": time.time() if first else marker.get("created"), "synced": time.time()}
        (dst / MARKER).write_text(json.dumps(meta))
    except (OSError, ValueError) as e:
        raise CloneError(f"couldn't write {MARKER}: {e}") from e
    return {"clone": str(dst), "first": first, "commands": cmds}


__all__ = ["CLONE_NOTE", "CloneError", "SYNC_DIRS", "clone_dir", "clones_root", "lock", "sync_clone"]
