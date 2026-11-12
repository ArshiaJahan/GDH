#!/usr/bin/env python3
"""Helpers for scripts/release.sh (run with `uv run python`):

    release_tool.py dir                       # print the updates folder from config
    release_tool.py publish --version X --app PATH [--notes-file F] [--commit SHA] [--force]
    release_tool.py prune [--keep N]

`publish` copies the app into `<dir>/.<version>.partial/`, writes release.json there,
renames the folder to `<dir>/<version>/`, and only then writes latest.json (atomically),
so the running app never sees a half-copied build.
"""
from __future__ import annotations

import argparse
import datetime as dt
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from gamedevworkstation.config import get_config
from gamedevworkstation.features.updates import (APP_NAME, bundle_info, history, installed_versions, parse_version, prune,
                                        read_json, updates_dir, write_json_atomic)


def _installed_versions(d: Path) -> set[str]:
    """Versions that may be in use right now: never prune these."""
    out = installed_versions(d)  # every app bundle that has run and still exists
    for app in (Path("/Applications") / APP_NAME, Path.home() / "Applications" / APP_NAME):
        try:
            with (app / "Contents" / "Info.plist").open("rb") as f:
                if v := plistlib.load(f).get("CFBundleShortVersionString"):
                    out.add(str(v))
        except (OSError, ValueError):
            pass
    return out


def cmd_publish(a: argparse.Namespace, d: Path) -> int:
    v = a.version.removeprefix("v")
    if parse_version(v) is None:
        sys.exit(f"'{v}' isn't a version like 1.2.3")
    app = Path(a.app).resolve()
    info = bundle_info(app)
    if not info or info.get("version") != v:
        sys.exit(f"{app} is version {info and info.get('version')}, expected {v}")
    d.mkdir(parents=True, exist_ok=True)
    final = d / v
    if final.exists() and not a.force:
        sys.exit(f"{final} already exists (use FORCE=1 to replace it)")
    partial = d / f".{v}.partial"
    if partial.exists():
        shutil.rmtree(partial)
    partial.mkdir()
    subprocess.run(["ditto", str(app), str(partial / APP_NAME)], check=True)
    notes = Path(a.notes_file).read_text().strip() if a.notes_file else ""
    rel = {"version": v, "built_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
           "git_commit": a.commit or None, "notes": notes}
    write_json_atomic(partial / "release.json", rel)
    # Replace an existing folder only once the new copy is complete (FORCE=1).
    trash = d / f".{v}.old"
    if final.exists():
        if trash.exists():
            shutil.rmtree(trash)
        final.rename(trash)
    partial.rename(final)
    if trash.exists():
        shutil.rmtree(trash)
    # Advertise last. Never move latest.json backwards (e.g. re-publishing an older version).
    cur = read_json(d / "latest.json")
    if not cur or parse_version(cur.get("version")) is None or parse_version(v) >= parse_version(cur["version"]):
        write_json_atomic(d / "latest.json", {**rel, "app": f"{v}/{APP_NAME}"})
    print(final / APP_NAME)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="release_tool.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dir")
    p = sub.add_parser("publish")
    p.add_argument("--version", required=True)
    p.add_argument("--app", required=True)
    p.add_argument("--notes-file")
    p.add_argument("--commit")
    p.add_argument("--force", action="store_true")
    pr = sub.add_parser("prune")
    pr.add_argument("--keep", type=int)
    a = ap.parse_args()
    cfg = get_config()
    d = updates_dir(cfg)
    if a.cmd == "dir":
        print(d)
        return 0
    if a.cmd == "publish":
        return cmd_publish(a, d)
    keep = a.keep if a.keep is not None else int(cfg.updates.get("keep", 3))
    protect = _installed_versions(d)
    removed = prune(d, keep, protect)
    kept = [r["version"] for r in history(d)]
    print(f"kept {', '.join(kept) or 'none'}" + (f"; removed {', '.join(removed)}" if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
