"""Install the embedded Unity package `com.gdw.replay` into a project's Packages folder.

Modelled on unity_harness.install_harness: shipped-file hashes and fixed meta GUIDs, a dry-run
plan, refusal to overwrite edited files or downgrade dependencies, and an install marker. Project
changes still need the existing setup consent; nothing here launches Unity.

The package templates live in skills/replay/templates/com.gdw.replay/ (tasks B/C own them);
this module works with or without them, creating a minimal package.json from built-in defaults
when the templates are absent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

PACKAGE_NAME = "com.gdw.replay"
PACKAGE_VERSION = "0.1.1"
PACKAGE_DIR = "Packages/com.gdw.replay"
VERSION_FILE = "package.json"
MARKER = f"{PACKAGE_DIR}/.gdw-installed.json"

# Files we ship (name → expected bytes when templates_dir exists); the fallback creates only package.json.
SHIPPED_FILES = ("package.json", "Runtime/Gdw.Replay.Runtime.asmdef", "Runtime/GdwRandom.cs",
                 "Runtime/SeededRng.cs", "Runtime/ReplaySession.cs", "Runtime/ReplayClock.cs",
                 "Runtime/ReplayLoop.cs", "Runtime/ReplayRegistry.cs", "Runtime/ReplayIdentity.cs",
                 "Runtime/StateWriter.cs", "Runtime/ReplayArchive.cs", "Runtime/ReplayContracts.cs",
                 "InputSystem/InputTraceAdapter.cs", "InputSystem/Gdw.Replay.InputSystem.asmdef",
                 "Editor/ReplayCommands.cs", "Editor/Gdw.Replay.Editor.asmdef")

PACKAGE_JSON = {
    "name": PACKAGE_NAME,
    "version": PACKAGE_VERSION,
    "displayName": "GDW Replay",
    "description": "Deterministic record/replay for Unity gameplay sessions",
    "unity": "6000.3",
    "dependencies": {
        "com.unity.inputsystem": "1.20.1",
    },
}

_GLOB_SPECIAL = re.compile(r"([\\*?\[\]])")


def templates_dir() -> Path:
    """The shipped package templates directory, if it exists."""
    from ..skills import builtin_skills_dir
    return builtin_skills_dir() / "replay" / "templates" / PACKAGE_NAME


def _shipped() -> dict[str, bytes]:
    """Read shipped template files; fall back to built-in package.json if templates missing."""
    td = templates_dir()
    if td.is_dir():
        out: dict[str, bytes] = {}
        for rel in SHIPPED_FILES:
            p = td / rel
            if p.is_file():
                out[rel] = p.read_bytes()
        if out:
            return out
    return {"package.json": json.dumps(PACKAGE_JSON, indent=2).encode("utf-8")}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def guid_for(rel: str) -> str:
    """A fixed Unity GUID (32 hex) for one of our paths, the same on every install."""
    return hashlib.sha256(f"gamedevworkstation/replay/{rel}".encode()).hexdigest()[:32]


def meta_text(rel: str, *, folder: bool = False) -> str:
    head = f"fileFormatVersion: 2\nguid: {guid_for(rel)}\n"
    tail = "  userData: \n  assetBundleName: \n  assetBundleVariant: \n"
    if folder:
        return head + "folderAsset: yes\nDefaultImporter:\n  externalObjects: {}\n" + tail
    if rel.endswith(".asmdef"):
        return head + "AssemblyDefinitionImporter:\n  externalObjects: {}\n" + tail
    return head + ("MonoImporter:\n  externalObjects: {}\n  serializedVersion: 2\n  defaultReferences: []\n"
                   "  executionOrder: 0\n  icon: {instanceID: 0}\n") + tail


# Project dependencies the PlayMode verification test needs. Existing pins are preserved.
MANIFEST_DEPENDENCIES = {
    "com.unity.test-framework": "1.6.0",
    "com.unity.inputsystem": "1.20.1",
    "com.unity.modules.physics": "1.0.0",
    "com.unity.modules.physics2d": "1.0.0",
}
TESTABLE = PACKAGE_NAME


def _version_tuple(version: str | None) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(version or ""))
    return tuple(int(p) for p in parts[:4]) or (0,)


def _package_file_status(root: Path, shipped: dict[str, bytes], installed_version: str | None) -> dict[str, str]:
    """Check each shipped file: missing | current | older | modified.

    `older`: the installed package is an older version and this file differs from the shipped one
    (a safe upgrade). `modified`: the installed package is this version (or newer, or unreadable)
    and the file differs — a local edit that is never overwritten."""
    d = root / PACKAGE_DIR
    # An unreadable package.json means we can't prove the files are ours: treat them as modified.
    older_package = installed_version is not None and _version_tuple(installed_version) < _version_tuple(PACKAGE_VERSION)
    files: dict[str, str] = {}
    for name in shipped:
        p = d / name
        try:
            data = p.read_bytes()
        except OSError:
            files[name] = "missing"
            continue
        if _digest(data) == _digest(shipped[name]):
            files[name] = "current"
        else:
            files[name] = "older" if older_package else "modified"
    return files


def replay_package_status(project: str | Path) -> dict:
    """Report installed files, versions, modified files and whether an upgrade is available.

    Returns {"installed", "complete", "version", "current_version", "outdated",
             "modified", "older", "missing", "missing_dependencies", "needs_upgrade_consent",
             "files", "path"}."""
    root = Path(project).expanduser()
    d = root / PACKAGE_DIR
    shipped = _shipped()
    installed = (d / VERSION_FILE).is_file()
    version = _read_version(d / VERSION_FILE) if installed else None
    files = _package_file_status(root, shipped, version)
    modified = sorted(n for n, v in files.items() if v == "modified")
    older = sorted(n for n, v in files.items() if v == "older")
    missing = sorted(n for n, v in files.items() if v == "missing")
    current = PACKAGE_VERSION
    outdated = installed and _version_tuple(version) < _version_tuple(current)
    return {"installed": installed, "complete": not missing,
            "version": version, "current_version": current,
            "outdated": outdated, "modified": modified, "older": older, "missing": missing,
            "missing_dependencies": [dep for dep in MANIFEST_DEPENDENCIES if dep not in _manifest_dependencies(root)],
            "needs_upgrade_consent": bool(older and not modified),
            "files": files, "path": str(d)}


def _read_version(pkg_json: Path) -> str | None:
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
        return str(data.get("version", "")) or None
    except (OSError, ValueError):
        return None


def _manifest_dependencies(root: Path) -> dict[str, str]:
    try:
        manifest = json.loads((root / "Packages" / "manifest.json").read_text(errors="replace", encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    deps = manifest.get("dependencies") if isinstance(manifest, dict) else None
    return {str(k): str(v) for k, v in deps.items()} if isinstance(deps, dict) else {}


def _ensure_manifest(root: Path, *, write: bool) -> dict:
    """Add com.unity.test-framework, the Input System and physics modules that are missing,
    preserving every existing pin, and make com.gdw.replay testable. Never suffixes versions."""
    manifest_path = root / "Packages" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(errors="replace", encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "message": f"cannot read manifest.json: {e}", "added": []}
    if not isinstance(manifest, dict):
        return {"ok": False, "message": "manifest.json is not an object", "added": []}
    deps = manifest.setdefault("dependencies", {})
    if not isinstance(deps, dict):
        return {"ok": False, "message": "manifest.json dependencies is not an object", "added": []}
    added = []
    for dep, version in MANIFEST_DEPENDENCIES.items():
        if dep not in deps:
            deps[dep] = version
            added.append(dep)
    testables = manifest.get("testables")
    if not isinstance(testables, list):
        testables = []
    if TESTABLE not in testables:
        testables.append(TESTABLE)
        manifest["testables"] = testables
        added.append("testables:" + TESTABLE)
    if not added:
        return {"ok": True, "message": "manifest already has the replay test dependencies", "added": []}
    if not write:
        return {"ok": True, "message": "would add " + ", ".join(added) + " to manifest.json", "added": added}
    try:
        _write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())
    except OSError as e:
        return {"ok": False, "message": f"cannot write manifest.json: {e}", "added": []}
    return {"ok": True, "message": "added " + ", ".join(added) + " to manifest.json", "added": added}


def install_replay_package(project: str | Path, *, allow_upgrade: bool = False, dry_run: bool = False,
                           allow_dependencies: bool = False) -> dict:
    """Install/upgrade the replay package; returns {ok, status, written, message, package}.

    Statuses: installed | upgraded | up_to_date | modified | needs_upgrade_consent | error.
    dry_run=True reports the plan and writes nothing. allow_upgrade=True is required to replace
    files of an older installed version; local edits are never overwritten. allow_dependencies=True
    (the caller's setup consent) lets it add the PlayMode test dependencies to Packages/manifest.json.
    Raises ValueError when `project` isn't a Unity project.
    """
    root = Path(project).expanduser().resolve()
    if not (root / "ProjectSettings" / "ProjectVersion.txt").is_file():
        raise ValueError(f"Not a Unity project (no ProjectSettings/ProjectVersion.txt): {root}")
    st = replay_package_status(root)
    shipped = _shipped()
    base = {"path": st["path"], "package": st}

    installed = bool(st.get("installed"))
    if installed and _version_tuple(st.get("version")) > _version_tuple(PACKAGE_VERSION):
        return {**base, "ok": True, "status": "up_to_date", "written": [],
                "message": (f"Version {st.get('version')} of {PACKAGE_NAME} is installed; "
                            f"not downgrading to {PACKAGE_VERSION}.")}

    if st.get("modified"):
        return {**base, "ok": False, "status": "modified", "written": [],
                "message": (f"Not installing: {', '.join(st['modified'])} in {PACKAGE_DIR} "
                            "was changed in this project (it matches no shipped version). "
                            "Merge the changes by hand, or move the file away first.")}

    upgrade = bool(st.get("outdated"))
    if upgrade and not allow_upgrade:
        return {**base, "ok": False, "status": "needs_upgrade_consent", "written": [],
                "message": (f"{PACKAGE_NAME} {st.get('version')} is installed and {PACKAGE_VERSION} "
                            f"would replace {len(st.get('older') or [])} file(s). Ask the user before upgrading.")}

    missing = st.get("missing", [])
    writes_package = bool(missing or upgrade)
    manifest_plan = bool(_ensure_manifest(root, write=False).get("added"))
    if not writes_package and not manifest_plan:
        return {**base, "ok": True, "status": "up_to_date", "written": [],
                "message": f"The replay package is already installed (version {st['version']})."}

    planned = sorted(set(missing + (st.get("older", []) if allow_upgrade else [])))
    if dry_run:
        what = planned + (["Packages/manifest.json (" + ", ".join(_ensure_manifest(root, write=False)["added"]) + ")"]
                          if manifest_plan and allow_dependencies else [])
        return {**base, "ok": True, "status": "would_upgrade" if upgrade and allow_upgrade else "would_install",
                "written": what,
                "message": ("Would update " if upgrade else "Would install ") + f"{len(planned)} file(s) into "
                           f"{PACKAGE_DIR}/" + (": " + ", ".join(planned) if planned else ".")}

    written: list[str] = []
    dirs_to_create = sorted({str(Path(name).parent) for name in shipped if "/" in name})
    for rel in sorted(set(["Packages", PACKAGE_DIR] + [f"{PACKAGE_DIR}/{d}" for d in dirs_to_create])):
        (root / rel).mkdir(parents=True, exist_ok=True)
        meta = root / f"{rel}.meta"
        if not meta.exists():
            _write(meta, meta_text(rel, folder=True).encode())
            written.append(f"{rel}.meta")

    for name, data in shipped.items():
        rel = f"{PACKAGE_DIR}/{name}"
        p = root / rel
        if not p.exists() or (allow_upgrade and st.get("files", {}).get(name) == "older"):
            _write(p, data)
            written.append(rel)
        meta = root / f"{rel}.meta"
        if not meta.exists():
            _write(meta, meta_text(rel).encode())
            written.append(f"{rel}.meta")

    _write(root / MARKER, json.dumps({"version": PACKAGE_VERSION}).encode())

    manifest_note = ""
    if allow_dependencies:
        res = _ensure_manifest(root, write=True)
        if not res.get("ok"):
            return {**base, "ok": False, "status": "error", "written": written,
                    "message": f"Package installed, but the manifest couldn't be updated: {res.get('message')}"}
        if res.get("added"):
            written.append("Packages/manifest.json (" + ", ".join(res["added"]) + ")")
    elif manifest_plan:
        manifest_note = " The manifest still needs the PlayMode test dependencies (consent required)."

    after = replay_package_status(root)
    if installed and upgrade and allow_upgrade:
        status = "upgraded"
    elif not installed or writes_package:
        status = "installed"
    else:
        status = "up_to_date"
    verb = "updated to" if status == "upgraded" else "installed"
    return {**base, "package": after, "ok": True, "status": status, "written": written,
            "message": (f"Replay package {PACKAGE_NAME} {PACKAGE_VERSION} {verb} "
                        f"({len(written)} file(s)) into {PACKAGE_DIR}/.{manifest_note}")}


def _write(p: Path, data: bytes) -> None:
    tmp = p.with_name(f".{p.name}.gdw-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
