#!/usr/bin/env python3
"""One version for the whole app.

`VERSION` at the repo root is the source of truth. This script keeps every other place
that carries the version in step with it:

    python scripts/version.py show
    python scripts/version.py bump patch|minor|major
    python scripts/version.py set 1.2.3
    python scripts/version.py next patch     # print what bump would give, change nothing
    python scripts/version.py check          # exit 1 if any file disagrees with VERSION
    python scripts/version.py build-info     # write backend/workspace/_build_info.json

`--root DIR` runs it against another checkout (the tests use a temp copy).
Standard library only, so it runs with any Python 3.11+.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def _sub_once(pattern: str, repl: str, text: str, what: str) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    if n != 1:
        raise SystemExit(f"version.py: couldn't find the version in {what}")
    return new


# Each target: (relative path, required, updater(text, version) -> text, reader(text) -> version)
def _pyproject(text: str, v: str) -> str:
    # The first `version = ` after [project].
    head, sep, rest = text.partition("[project]")
    if not sep:
        raise SystemExit("version.py: pyproject.toml has no [project] table")
    return head + sep + _sub_once(r'^version = "[^"]*"', f'version = "{v}"', rest, "pyproject.toml")


def _read_pyproject(text: str) -> str | None:
    m = re.search(r'\[project\][^\[]*?^version = "([^"]*)"', text, re.M | re.S)
    return m.group(1) if m else None


def _json_first(text: str, v: str, what: str) -> str:
    return _sub_once(r'^(\s*)"version": "[^"]*"', rf'\g<1>"version": "{v}"', text, what)


def _read_json_version(text: str) -> str | None:
    try:
        return json.loads(text).get("version")
    except ValueError:
        return None


def _package_lock(text: str, v: str) -> str:
    data = json.loads(text)
    data["version"] = v
    if "" in data.get("packages", {}):
        data["packages"][""]["version"] = v
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _read_package_lock(text: str) -> str | None:
    data = json.loads(text)
    root = data.get("packages", {}).get("", {}).get("version")
    return data.get("version") if root in (None, data.get("version")) else f"{data.get('version')} / {root}"


def _cargo_toml(text: str, v: str) -> str:
    head, sep, rest = text.partition("[package]")
    if not sep:
        raise SystemExit("version.py: Cargo.toml has no [package] table")
    return head + sep + _sub_once(r'^version = "[^"]*"', f'version = "{v}"', rest, "Cargo.toml")


def _read_cargo_toml(text: str) -> str | None:
    m = re.search(r'\[package\][^\[]*?^version = "([^"]*)"', text, re.M | re.S)
    return m.group(1) if m else None


def _lock_entry(name: str):
    pat = rf'(^\[\[package\]\]\nname = "{re.escape(name)}"\nversion = ")[^"]*(")'

    def upd(text: str, v: str) -> str:
        return _sub_once(pat, rf"\g<1>{v}\g<2>", text, f"the lock entry for {name}")

    def read(text: str) -> str | None:
        m = re.search(rf'^\[\[package\]\]\nname = "{re.escape(name)}"\nversion = "([^"]*)"', text, re.M)
        return m.group(1) if m else None

    return upd, read


def _init_py(text: str, v: str) -> str:
    if re.search(r'^__version__ = "[^"]*"', text, re.M):
        return _sub_once(r'^__version__ = "[^"]*"', f'__version__ = "{v}"', text, "__init__.py")
    return f'__version__ = "{v}"\n' + text


def _read_init_py(text: str) -> str | None:
    m = re.search(r'^__version__ = "([^"]*)"', text, re.M)
    return m.group(1) if m else None


_uv_upd, _uv_read = _lock_entry("workspace")
_cargo_upd, _cargo_read = _lock_entry("workspace-app")

TARGETS = [
    ("pyproject.toml", True, _pyproject, _read_pyproject),
    ("uv.lock", False, _uv_upd, _uv_read),
    ("backend/workspace/__init__.py", True, _init_py, _read_init_py),
    ("frontend/package.json", True, lambda t, v: _json_first(t, v, "frontend/package.json"), _read_json_version),
    ("frontend/package-lock.json", False, _package_lock, _read_package_lock),
    ("src-tauri/tauri.conf.json", True, lambda t, v: _json_first(t, v, "src-tauri/tauri.conf.json"), _read_json_version),
    ("src-tauri/Cargo.toml", True, _cargo_toml, _read_cargo_toml),
    ("src-tauri/Cargo.lock", False, _cargo_upd, _cargo_read),
]


def parse(v: str) -> tuple[int, int, int, str | None]:
    m = SEMVER.match(v.strip())
    if not m:
        raise SystemExit(f"version.py: '{v}' isn't a version like 1.2.3")
    return int(m[1]), int(m[2]), int(m[3]), m[4]


def bumped(v: str, part: str) -> str:
    major, minor, patch, pre = parse(v)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch}" if pre else f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"version.py: bump what? patch, minor or major (got '{part}')")


def current(root: Path) -> str:
    f = root / "VERSION"
    if not f.exists():
        raise SystemExit(f"version.py: {f} is missing")
    return f.read_text().strip()


def set_version(root: Path, v: str) -> list[str]:
    parse(v)
    changed = []
    (root / "VERSION").write_text(v + "\n")
    for rel, required, upd, _ in TARGETS:
        p = root / rel
        if not p.exists():
            if required:
                raise SystemExit(f"version.py: {rel} is missing")
            continue
        old = p.read_text()
        new = upd(old, v)
        if new != old:
            p.write_text(new)
            changed.append(rel)
    return changed


def check(root: Path) -> list[str]:
    v = current(root)
    bad = []
    for rel, _required, _, read in TARGETS:
        p = root / rel
        if p.exists() and (found := read(p.read_text())) != v:
            bad.append(f"{rel}: {found}")
    return bad


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def build_info(root: Path) -> dict:
    info = {
        "version": current(root),
        "git_commit": _git(root, "rev-parse", "--short", "HEAD") or None,
        "git_dirty": bool(_git(root, "status", "--porcelain")),
        "built_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    }
    out = root / "backend" / "workspace" / "_build_info.json"
    out.write_text(json.dumps(info, indent=2) + "\n")
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="version.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    b = sub.add_parser("bump")
    b.add_argument("part", choices=["patch", "minor", "major"])
    nx = sub.add_parser("next")
    nx.add_argument("part", choices=["patch", "minor", "major"])
    s = sub.add_parser("set")
    s.add_argument("version")
    sub.add_parser("check")
    sub.add_parser("build-info")
    a = ap.parse_args(argv)
    root = a.root.resolve()

    if a.cmd == "show":
        print(current(root))
    elif a.cmd == "next":
        print(bumped(current(root), a.part))
    elif a.cmd in ("bump", "set"):
        v = bumped(current(root), a.part) if a.cmd == "bump" else a.version.strip().removeprefix("v")
        changed = set_version(root, v)
        print(v)
        if changed:
            print("updated: " + ", ".join(changed), file=sys.stderr)
    elif a.cmd == "check":
        bad = check(root)
        if bad:
            print(f"VERSION is {current(root)} but:\n  " + "\n  ".join(bad), file=sys.stderr)
            return 1
        print(f"{current(root)} everywhere")
    elif a.cmd == "build-info":
        print(json.dumps(build_info(root)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
