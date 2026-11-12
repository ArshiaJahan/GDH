"""App updates from a local folder.

`make release` builds each version into `<dir>/<version>/Workspace.app` with a
`release.json`, then writes `<dir>/latest.json` last (tmp file + rename), so a half-copied
build is never advertised. This module:

- polls cheaply: one stat() of latest.json every `check_interval_s`; it parses only when
  the file changed, so an idle app costs next to nothing;
- when latest is newer than the running version, publishes `update.available` (once per
  version), shows it in /api/state and posts a macOS notification (frozen app only);
- installs: validates the new bundle, copies it next to the running one, then hands over to
  a small shell helper that runs outside the app's process group (the app kills its whole
  backend group on quit). The helper quits the app, swaps the bundles, keeps the old one in
  `<dir>/.previous/` and opens the new one; if anything fails it puts the old one back.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException

from .. import __version__
from ..buildinfo import frozen, version_info
from ..config import data_dir, logs_dir

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)

BUNDLE_ID = "dev.local.workspace"  # src-tauri/tauri.conf.json "identifier"
APP_NAME = "Workspace.app"
PREVIOUS = ".previous"
FROM_SOURCE = ("Running from source, so there's no app bundle to replace: your edits are live when you restart "
               "`uv run workspace`, or instantly with `make live`. `make release` builds an installable version.")

# ------------------------------------------------------------------- versions

_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def parse_version(v: Any) -> tuple | None:
    """Sortable key for a semver string, or None. A release sorts after its pre-releases."""
    m = _SEMVER.match(str(v or "").strip())
    if not m:
        return None
    pre = m.group(4)
    pre_key: tuple = (1,) if pre is None else (0, *((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")))
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), pre_key


def is_newer(a: Any, b: Any) -> bool:
    pa, pb = parse_version(a), parse_version(b)
    return pa is not None and pb is not None and pa > pb


# ------------------------------------------------------------------- folder


def updates_dir(cfg: Any = None) -> Path:
    """`WORKSPACE_UPDATES_DIR` (tests, experiments) wins over config `[updates] dir`."""
    if env := os.environ.get("WORKSPACE_UPDATES_DIR"):
        return Path(env).expanduser()
    conf = getattr(cfg, "updates", None) or {}
    return Path(conf.get("dir") or "~/WorkspaceUpdates").expanduser()


def read_json(p: Path) -> dict | None:
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json_atomic(p: Path, data: dict) -> None:
    """Readers see the old file or the new one, never half of one."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def bundle_info(app: Path) -> dict | None:
    """Version and identifier from an app bundle's Info.plist."""
    try:
        with (app / "Contents" / "Info.plist").open("rb") as f:
            pl = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    return {"version": pl.get("CFBundleShortVersionString"), "identifier": pl.get("CFBundleIdentifier"),
            "executable": pl.get("CFBundleExecutable")}


def release_app(d: Path, rel: dict) -> Path | None:
    """The bundle a release points at; must stay inside the updates folder."""
    app = rel.get("app") or f"{rel.get('version')}/{APP_NAME}"
    try:
        p = (d / str(app)).resolve()
        if d.resolve() not in p.parents:
            return None
    except OSError:
        return None
    return p


def validate_release(d: Path, rel: dict | None) -> dict | None:
    """A usable release record (latest.json or release.json), or None."""
    if not rel or parse_version(rel.get("version")) is None:
        return None
    app = release_app(d, rel)
    if app is None or not (app / "Contents" / "Info.plist").is_file():
        return None
    return {"version": str(rel["version"]).removeprefix("v"), "built_at": rel.get("built_at"),
            "git_commit": rel.get("git_commit"), "notes": str(rel.get("notes") or ""), "app_path": str(app)}


def history(d: Path) -> list[dict]:
    """Every release in the folder, newest first."""
    out = []
    try:
        entries = list(d.iterdir())
    except OSError:
        return []
    for sub in entries:
        if not sub.is_dir() or parse_version(sub.name) is None:
            continue
        rel = validate_release(d, read_json(sub / "release.json"))
        if rel and rel["version"] == sub.name:
            out.append(rel)
    out.sort(key=lambda r: parse_version(r["version"]), reverse=True)
    return out


def previous_bundle(d: Path) -> dict | None:
    """The bundle kept by the last install (for rollback)."""
    prev = d / PREVIOUS
    try:
        apps = sorted(prev.glob("Workspace-*.app"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for app in apps:
        info = bundle_info(app)
        if info and info.get("version"):
            return {"version": info["version"], "app_path": str(app)}
    return None


def prune(d: Path, keep: int, protect: set[str] = frozenset()) -> list[str]:
    """Delete release folders beyond the newest `keep`, never the newest or a protected one.
    Only folders named like a version and holding a release.json are ever touched."""
    rels = history(d)
    keep_set = {r["version"] for r in rels[:max(1, keep)]} | set(protect)
    latest = validate_release(d, read_json(d / "latest.json"))
    if latest:
        keep_set.add(latest["version"])
    removed = []
    for r in rels:
        if r["version"] in keep_set:
            continue
        folder = d / r["version"]
        if folder.is_dir() and (folder / "release.json").is_file():
            shutil.rmtree(folder)
            removed.append(r["version"])
    return removed


# ------------------------------------------------------------- installed.json
# {"installs": {"/Applications/Workspace.app": {"version": "0.2.0", "at": 1730000000.0}, ...}}
# One entry per bundle path that has run, so a test or dev build launched from dist/ can't hide
# the version the user really runs. Entries whose bundle is gone are ignored (and dropped on write).

INSTALLED = "installed.json"


def _parse_installs(data: dict | None) -> dict[str, dict]:
    """Both formats: the current {"installs": {bundle: {version, at}}} and the old single
    {"version", "bundle", "at"} record."""
    if not data:
        return {}
    out: dict[str, dict] = {}
    if isinstance(data.get("installs"), dict):
        for bundle, rec in data["installs"].items():
            if isinstance(bundle, str) and isinstance(rec, dict) and rec.get("version"):
                out[bundle] = {"version": str(rec["version"]), "at": rec.get("at")}
    elif isinstance(data.get("bundle"), str) and data.get("version"):
        out[data["bundle"]] = {"version": str(data["version"]), "at": data.get("at")}
    return out


def _bundle_alive(bundle: str) -> bool:
    return (Path(bundle) / "Contents" / "Info.plist").is_file()


def read_installs(d: Path) -> dict[str, dict]:
    """Live installs only: bundle path -> {version, at}. The version comes from the bundle itself
    when readable (it may have been replaced since it last started)."""
    out = {}
    for bundle, rec in _parse_installs(read_json(d / INSTALLED)).items():
        if not _bundle_alive(bundle):
            continue
        v = (bundle_info(Path(bundle)) or {}).get("version")
        out[bundle] = {**rec, "version": str(v or rec["version"])}
    return out


def installed_versions(d: Path) -> set[str]:
    return {rec["version"] for rec in read_installs(d).values()}


class _FileLock:
    """Short advisory lock (flock) around a read-modify-write. Gives up after `timeout` seconds and
    carries on unlocked: the write itself is still atomic, so the worst case is a lost entry that the
    other app re-adds on its next start, never a corrupt file."""

    def __init__(self, path: Path, timeout: float = 2.0):
        self.path, self.timeout, self.fd = path, timeout, None

    def __enter__(self) -> "_FileLock":
        import fcntl
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return self
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    log.warning("couldn't lock %s; writing without it", self.path)
                    return self
                time.sleep(0.02)

    def __exit__(self, *exc: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)  # releases the flock
            self.fd = None


def record_install(d: Path, bundle: Path | str, version: str, at: float | None = None) -> dict[str, dict]:
    """Add or refresh `bundle`'s entry, drop entries whose bundle is gone, write atomically."""
    d.mkdir(parents=True, exist_ok=True)
    with _FileLock(d / f".{INSTALLED}.lock"):
        installs = {b: r for b, r in _parse_installs(read_json(d / INSTALLED)).items() if _bundle_alive(b)}
        installs[str(bundle)] = {"version": str(version), "at": time.time() if at is None else at}
        write_json_atomic(d / INSTALLED, {"installs": installs})
    return installs


# ------------------------------------------------------------- running app


def running_bundle() -> Path | None:
    """Frozen backend: …/Workspace.app/Contents/Resources/backend/workspace-backend."""
    if not frozen():
        return None
    for p in Path(sys.executable).resolve().parents:
        if p.suffix == ".app":
            return p
    return None


def app_pid() -> int | None:
    v = os.environ.get("WORKSPACE_PARENT_PID", "")
    return int(v) if v.isdigit() else None


def install_support() -> tuple[bool, str | None]:
    if sys.platform != "darwin":
        return False, "Install & restart works in the macOS app only."
    if not frozen():
        return False, FROM_SOURCE
    bundle = running_bundle()
    if bundle is None:
        return False, "Couldn't find the app bundle this backend runs from."
    if app_pid() is None:
        return False, "The backend was started without --parent-pid, so it can't restart the app."
    if not os.access(bundle.parent, os.W_OK):
        return False, f"Can't write to {bundle.parent}, so the app can't replace itself there."
    return True, None


def verify_bundle(app: Path, expect_version: str | None) -> dict:
    """Raise ValueError unless `app` is a signed Workspace bundle of the expected version."""
    if not (app / "Contents" / "Info.plist").is_file():
        raise ValueError(f"{app} isn't an app bundle (no Contents/Info.plist).")
    info = bundle_info(app) or {}
    if info.get("identifier") not in (None, BUNDLE_ID):
        raise ValueError(f"{app} is {info.get('identifier')}, not Workspace.")
    if expect_version and info.get("version") != expect_version:
        raise ValueError(f"{app} says it's version {info.get('version')}, expected {expect_version}.")
    if shutil.which("codesign"):
        r = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], capture_output=True, text=True,
                           timeout=180)
        if r.returncode != 0:
            raise ValueError(f"The signature of {app} doesn't verify: {(r.stderr or r.stdout).strip()[:300]}")
    return info


def stage_path(bundle: Path) -> Path:
    """Where the new version is copied before the swap: next to the bundle, same volume."""
    return bundle.parent / f".{bundle.name}.updating"


def copy_bundle(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    if shutil.which("ditto"):  # keeps symlinks, xattrs and the code signature intact
        r = subprocess.run(["ditto", str(src), str(dst)], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            shutil.rmtree(dst, ignore_errors=True)
            raise OSError(f"ditto failed: {r.stderr.strip()[:300]}")
    else:
        shutil.copytree(src, dst, symlinks=True)


def helper_script(*, app_pid: int, bundle: Path, stage: Path, backup: Path, backend_pid: int = 0,
                  bundle_id: str = BUNDLE_ID) -> str:
    """The swap-and-relaunch script. Values are baked in; tools can be stubbed via env
    (WS_OSASCRIPT, WS_OPEN, WS_XATTR) and timings shortened (WS_START_DELAY, WS_QUIT_TIMEOUT,
    WS_BACKEND_WAIT, WS_LAUNCH_TIMEOUT, WS_LAUNCH_SETTLE) so tests can run it against a fake bundle.

    It never deletes the running app: the current bundle is only ever moved to BACKUP, and
    every move checks that its destination is free first."""
    q = shlex.quote
    return f"""#!/bin/bash
# Workspace update helper (generated by the backend). Runs detached from the app.
set -u
APP_PID={int(app_pid)}
BACKEND_PID={int(backend_pid)}
BUNDLE={q(str(bundle))}
STAGE={q(str(stage))}
BACKUP={q(str(backup))}
BACKUP_DIR={q(str(backup.parent))}
BUNDLE_ID={q(bundle_id)}
OSASCRIPT="${{WS_OSASCRIPT:-/usr/bin/osascript}}"
OPEN="${{WS_OPEN:-/usr/bin/open}}"
XATTR="${{WS_XATTR:-/usr/bin/xattr}}"
QUIT_TIMEOUT="${{WS_QUIT_TIMEOUT:-30}}"
BACKEND_WAIT="${{WS_BACKEND_WAIT:-15}}"
LAUNCH_TIMEOUT="${{WS_LAUNCH_TIMEOUT:-20}}"
LAUNCH_SETTLE="${{WS_LAUNCH_SETTLE:-3}}"

log() {{ echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }}
alive() {{ kill -0 "$APP_PID" 2>/dev/null; }}
bundle_ok() {{ [ -f "$1/Contents/Info.plist" ] && [ -n "$(ls -A "$1/Contents/MacOS" 2>/dev/null)" ]; }}
# True while a process runs from $BUNDLE/Contents/MacOS/ (path passed via env so awk can't match itself).
launched() {{ ps -axww -o command= | P="$BUNDLE/Contents/MacOS/" awk 'index($0, ENVIRON["P"]) {{ f = 1 }} END {{ exit !f }}'; }}
wait_launched() {{
  local i=0
  while [ "$i" -lt $((LAUNCH_TIMEOUT * 10)) ]; do launched && break; sleep 0.1; i=$((i + 1)); done
  launched || return 1
  sleep "$LAUNCH_SETTLE"
  launched
}}
reopen_current() {{ "$OPEN" "$BUNDLE" || log "ERROR: couldn't reopen $BUNDLE"; }}

log "update: $STAGE -> $BUNDLE (app pid $APP_PID)"
if ! bundle_ok "$STAGE"; then log "ERROR: the staged copy is missing; nothing changed"; exit 1; fi
sleep "${{WS_START_DELAY:-1}}"  # let the backend answer the request first

# 1. Quit the app: politely (its quit handler stops the backend and everything it started),
#    then TERM, then KILL. The request runs in the background because it can block (a
#    permission prompt, a busy app); the wait is bounded by QUIT_TIMEOUT either way.
if alive; then
  log "asking the app to quit"
  "$OSASCRIPT" -e "tell application id \\"$BUNDLE_ID\\" to quit" >/dev/null 2>&1 &
  OSA_PID=$!
  OSA_DONE=0
  LIMIT=$((QUIT_TIMEOUT * 10))
  i=0
  while alive && [ "$i" -lt "$LIMIT" ]; do
    if [ "$OSA_DONE" = 0 ] && ! kill -0 "$OSA_PID" 2>/dev/null; then
      OSA_DONE=1
      if ! wait "$OSA_PID"; then
        # Apps often exit before replying, so a failed request may still be a quit in progress.
        log "quit request failed; waiting briefly before stopping the process"
        [ $((i + 100)) -lt "$LIMIT" ] && LIMIT=$((i + 100))
      fi
    fi
    sleep 0.1; i=$((i + 1))
  done
  kill "$OSA_PID" 2>/dev/null
fi
if alive; then
  log "still running; sending TERM"; kill -TERM "$APP_PID" 2>/dev/null
  i=0; while alive && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
fi
if alive; then log "sending KILL"; kill -KILL "$APP_PID" 2>/dev/null; sleep 0.5; fi
# The backend exits with the app (or within ~2 s of it via its parent watcher).
if [ "$BACKEND_PID" -gt 0 ]; then
  i=0; while kill -0 "$BACKEND_PID" 2>/dev/null && [ "$i" -lt $((BACKEND_WAIT * 10)) ]; do sleep 0.1; i=$((i + 1)); done
  kill -0 "$BACKEND_PID" 2>/dev/null && log "note: the old backend (pid $BACKEND_PID) is still running"
fi
sleep 0.5

# 2. Swap: current -> backup, staged -> current.
mkdir -p "$BACKUP_DIR" 2>/dev/null
rm -rf "${{BACKUP:?}}"
if [ -e "$BACKUP" ] || ! mv "$BUNDLE" "$BACKUP"; then
  log "ERROR: couldn't move the current app aside to $BACKUP; reopening it"
  rm -rf "${{STAGE:?}}"
  reopen_current
  exit 1
fi
if [ ! -e "$BUNDLE" ] && mv "$STAGE" "$BUNDLE" && bundle_ok "$BUNDLE"; then
  "$XATTR" -cr "$BUNDLE" 2>/dev/null || true
  log "opening the new version"
  if "$OPEN" "$BUNDLE" && wait_launched; then
    for old in "$BACKUP_DIR"/Workspace-*.app; do
      [ -e "$old" ] && [ "$old" != "$BACKUP" ] && rm -rf "$old"
    done
    log "done; previous version kept at $BACKUP"
    exit 0
  fi
  log "ERROR: the new version didn't start"
else
  log "ERROR: couldn't put the new version in place"
fi

# 3. Something failed after the swap began: put the old app back and open it.
log "restoring the previous version"
pkill -f "$BUNDLE/Contents/MacOS/" 2>/dev/null
i=0; while launched && [ "$i" -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
rm -rf "${{BUNDLE:?}}" "${{STAGE:?}}"
if [ ! -e "$BUNDLE" ] && mv "$BACKUP" "$BUNDLE"; then
  reopen_current
else
  log "ERROR: couldn't restore; the previous version is at $BACKUP"
fi
exit 1
"""


def _clean_env() -> dict[str, str]:
    """The helper must not inherit PyInstaller's loader variables."""
    drop = ("_PYI", "_MEI", "DYLD_", "PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


def launch_helper(script: str, log_path: Path) -> int:
    """Start the helper in its own session (own process group), so quitting the app,
    which kills the backend's whole group, doesn't kill it."""
    d = data_dir() / "updates-tmp"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"install-{int(time.time())}.sh"
    path.write_text(script)
    path.chmod(0o700)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as out:
        p = subprocess.Popen(["/bin/bash", str(path)], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True, close_fds=True, env=_clean_env(), cwd="/")
    return p.pid


def notify_native(title: str, text: str) -> None:
    """macOS notification via osascript; strings go in as argv, so no quoting issues."""
    if sys.platform != "darwin" or not frozen():
        return
    try:
        subprocess.Popen(["/usr/bin/osascript", "-e", "on run argv", "-e",
                          "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run",
                          title, text], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        log.warning("couldn't post the update notification")


# ------------------------------------------------------------------ service


class Updater:
    def __init__(self, app: "AppState"):
        self.app = app
        self._sig: tuple | None = None
        self._latest: dict | None = None
        self._task: asyncio.Task | None = None
        self.installing: dict | None = None

    @property
    def dir(self) -> Path:
        return updates_dir(self.app.config)

    def interval(self) -> float:
        try:
            return max(5.0, float(self.app.config.updates.get("check_interval_s", 30)))
        except (TypeError, ValueError):
            return 30.0

    def check(self, force: bool = False) -> dict | None:
        """Cheap: one stat(); latest.json is read only when its path, mtime or size changed,
        or while it exists but isn't usable yet (e.g. a synced folder delivered it before the app)."""
        p = self.dir / "latest.json"
        try:
            st = p.stat()
            sig: tuple | None = (str(p), st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None
        if force or sig != self._sig or (sig and self._latest is None):
            had = self.pending_update()
            self._sig = sig
            self._latest = validate_release(self.dir, read_json(p)) if sig else None
            upd = self.pending_update()
            if upd:
                self._announce(upd)
            elif had:
                self.app.bus.publish("update.cleared", {"version": had["latest"]})
        return self.pending_update()

    def pending_update(self) -> dict | None:
        rel = self._latest
        if not rel or not is_newer(rel["version"], __version__):
            return None
        # install_supported lets the banner say "Install & restart" only where that works
        # (the frozen macOS app); running from source it reads "Update vX available".
        return {"current": __version__, "latest": rel["version"], "notes": rel["notes"], "built_at": rel["built_at"],
                "git_commit": rel["git_commit"], "install_supported": self.support()[0]}

    def _announce(self, upd: dict) -> None:
        seen = list(self.app.db.kv_get("updates.announced", []) or [])
        if upd["latest"] in seen:
            return
        self.app.db.kv_set("updates.announced", (seen + [upd["latest"]])[-50:])
        self.app.bus.publish("update.available", upd)
        notify_native("Workspace update ready", f"Version {upd['latest']} is built. Open Workspace to install and restart.")

    def support(self) -> tuple[bool, str | None]:
        ok, reason = install_support()
        if ok and not os.access(self.dir if self.dir.is_dir() else self.dir.parent, os.W_OK):
            return False, f"Can't write to {self.dir}, where the current version is kept for rollback."
        return ok, reason

    def status(self) -> dict:
        d = self.dir
        ok, reason = self.support()
        bundle = running_bundle()
        return {
            "current": version_info(), "dir": str(d), "dir_exists": d.is_dir(), "check_interval_s": self.interval(),
            "latest": self._latest, "update": self.pending_update(), "history": history(d),
            "previous": previous_bundle(d), "install_supported": ok, "reason": reason,
            "bundle_path": str(bundle) if bundle else None, "installing": self.installing,
            "installed": read_installs(d).get(str(bundle)) if bundle else None,  # this bundle's own entry
            "busy_sessions": len(getattr(self.app.runner, "running", {}) or {}),
            "log_path": str(logs_dir() / "update.log"),
        }

    # -- install / rollback (blocking parts run in a thread)

    def _prepare(self, src: Path, version: str | None) -> dict:
        ok, reason = self.support()
        if not ok:
            raise HTTPException(400, reason)
        bundle, pid = running_bundle(), app_pid()
        assert bundle is not None and pid is not None
        try:
            info = verify_bundle(src, version)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        stage = stage_path(bundle)
        try:
            copy_bundle(src, stage)
        except OSError as e:
            raise HTTPException(500, f"Couldn't copy the new version next to the app: {e}") from None
        running = (bundle_info(bundle) or {}).get("version") or __version__
        backup = self.dir / PREVIOUS / f"Workspace-{running}.app"
        try:
            backup.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(500, f"Couldn't create {backup.parent}: {e}") from None
        script = helper_script(app_pid=pid, bundle=bundle, stage=stage, backup=backup, backend_pid=os.getpid())
        helper_pid = launch_helper(script, logs_dir() / "update.log")
        return {"ok": True, "version": info.get("version") or version, "from": __version__, "helper_pid": helper_pid,
                "bundle": str(bundle), "backup": str(backup), "log": str(logs_dir() / "update.log")}

    async def install(self, version: Any, *, rollback: bool = False) -> dict:
        inst = self.installing
        if inst and inst.get("launched_at") and time.time() - inst["launched_at"] > 120:
            self.installing = None  # the helper gave up without quitting the app; see update.log
        if self.installing:
            raise HTTPException(409, f"Already installing {self.installing.get('version')}.")
        if version is not None and not isinstance(version, str):
            raise HTTPException(400, "version must be a string like 1.2.3")
        ok, reason = self.support()
        if not ok:
            raise HTTPException(400, reason)
        if rollback:
            prev = previous_bundle(self.dir)
            if not prev:
                raise HTTPException(404, "There's no previous version to roll back to.")
            src, version = Path(prev["app_path"]), prev["version"]
        else:
            self.check()
            rels = {r["version"]: r for r in history(self.dir)}
            if self._latest:
                rels.setdefault(self._latest["version"], self._latest)
            version = version or (self._latest or {}).get("version")
            if not version or version not in rels:
                raise HTTPException(404, f"Version {version} isn't in {self.dir}." if version else "No update to install.")
            src = Path(rels[version]["app_path"])
        self.installing = {"version": version, "rollback": rollback, "started_at": time.time(), "launched_at": None}
        try:
            res = await asyncio.to_thread(self._prepare, src, version)
        except BaseException:
            self.installing = None
            raise
        self.installing["launched_at"] = time.time()  # only now may a stuck install time out
        self.app.bus.publish("update.installing", {"version": version, "from": __version__, "rollback": rollback})
        return res

    def record_installed(self) -> None:
        """Lets `make release` know which versions are in use, so it never prunes them."""
        bundle = running_bundle()
        if bundle and self.dir.is_dir():
            try:
                record_install(self.dir, bundle, __version__)
            except OSError:
                pass

    async def astart(self) -> None:
        self.record_installed()

        async def loop() -> None:
            while True:
                try:
                    self.check()
                except Exception:  # noqa: BLE001 — a bad folder must never take the app down
                    log.exception("update check failed")
                await asyncio.sleep(self.interval())

        self._task = asyncio.create_task(loop())

    async def aclose(self) -> None:
        if self._task:
            self._task.cancel()


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    up = Updater(S)
    S.extensions["updates"] = up

    @api.get("/updates")
    async def get_updates() -> dict:
        return up.status()

    @api.post("/updates/check")
    async def check_now() -> dict:
        up.check(force=True)
        return up.status()

    @api.post("/updates/install")
    async def install(body: dict = Body(default={})) -> dict:
        return await up.install(body.get("version"))

    @api.post("/updates/rollback")
    async def rollback() -> dict:
        return await up.install(None, rollback=True)
