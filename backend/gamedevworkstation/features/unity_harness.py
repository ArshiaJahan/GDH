"""The headless-ops harness editor scripts (HarnessCli) in a Unity project: status, install /
upgrade, uninstall (research notes §2.6, option B "on demand").

Batch jobs that need more than the official Unity CLI offers (a forced recompile, asset import,
a menu item, development builds, Harness.Headless.HarnessCli.* methods) run through headless-ops
`unity.sh`, which needs three editor scripts in the project. The harness never adds them on its
own: an op that needs them returns a `needs_harness` result and the user installs them with the
install_harness action (an approval card). Then:
- the shipped templates (skills/headless-ops/templates/Editor/) are copied to
  Assets/Harness/Headless/Editor/, with .meta files whose GUIDs are fixed (derived from the path),
  so a reinstall keeps the same GUIDs; an existing .meta is never rewritten;
- when the project is in a git work tree, `.git/info/exclude` (local, never committed) gets the
  harness paths once, so nothing tracked changes. Only our own folder is excluded
  (`/Assets/Harness/Headless/`), not all of `Assets/Harness/`: other skills (game-feel-pass,
  play-verify, build-ship, …) put project code there that the user may want tracked;
- a file whose content matches no shipped version was edited by the user: it is never
  overwritten or removed;
- an older shipped version (`// harness-version: N` first line of HarnessCli.cs; none = 1) is
  replaced only with consent (allow_upgrade=True, given by the approval card).
Uninstall removes only our files (and folders left empty by that), never an edited one.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

HARNESS_DIR = "Assets/Harness/Headless/Editor"
FILES = ("HarnessCli.cs", "HarnessArgs.cs", "Harness.Headless.Editor.asmdef")
VERSION_FILE = "HarnessCli.cs"
MARKER = "Assets/Harness/Headless/.gdw-harness.json"
# Folders we may create, outermost first (each gets a folder .meta when it has none).
FOLDERS = ("Assets/Harness", "Assets/Harness/Headless", "Assets/Harness/Headless/Editor")
# sha256 (CRLF → LF) of earlier shipped versions, per file: those may be replaced on upgrade and
# removed on uninstall. Add the old hash here whenever a template changes.
PREVIOUS: dict[str, set[str]] = {
    # harness-version 1 (no marker line; before MenuItem and -buildOutput)
    "HarnessCli.cs": {"46a5acc318daed2733610213a48a510426d851241740941fea858be93ec1999f"},
}
EXCLUDE_HEADER = "# GameDevWorkstation: headless-ops harness editor scripts (local only)"
_VERSION = re.compile(rb"\A(?:\xef\xbb\xbf)?//\s*harness-version:\s*(\d+)")
_GLOB_SPECIAL = re.compile(r"([\\*?\[\]])")


def templates_dir() -> Path:
    from ..skills import builtin_skills_dir

    return builtin_skills_dir() / "headless-ops" / "templates" / "Editor"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _shipped() -> dict[str, bytes]:
    d = templates_dir()
    return {n: (d / n).read_bytes() for n in FILES}


def version_of(data: bytes | None) -> int | None:
    """The `// harness-version: N` of a HarnessCli.cs (1 when it has no marker)."""
    if data is None:
        return None
    m = _VERSION.match(data)
    return int(m.group(1)) if m else 1


def guid_for(rel: str) -> str:
    """A fixed Unity GUID (32 hex) for one of our paths, the same on every install."""
    return hashlib.sha256(f"gamedevworkstation/harness/{rel}".encode()).hexdigest()[:32]


def meta_text(rel: str, *, folder: bool = False) -> str:
    head = f"fileFormatVersion: 2\nguid: {guid_for(rel)}\n"
    tail = "  userData: \n  assetBundleName: \n  assetBundleVariant: \n"
    if folder:
        return head + "folderAsset: yes\nDefaultImporter:\n  externalObjects: {}\n" + tail
    if rel.endswith(".asmdef"):
        return head + "AssemblyDefinitionImporter:\n  externalObjects: {}\n" + tail
    return head + ("MonoImporter:\n  externalObjects: {}\n  serializedVersion: 2\n  defaultReferences: []\n"
                   "  executionOrder: 0\n  icon: {instanceID: 0}\n") + tail


def harness_status(project: Path | str) -> dict[str, Any]:
    """{"installed", "complete", "version", "current_version", "outdated", "modified", "missing",
    "files", "path"}. files: name -> missing | current | older | modified (matches no shipped
    version). installed: our HarnessCli.cs is there; outdated: an older shipped version that may
    be upgraded (nothing edited)."""
    root = Path(project).expanduser()
    d = root / HARNESS_DIR
    shipped = _shipped()
    files: dict[str, str] = {}
    data: dict[str, bytes] = {}
    for name in FILES:
        p = d / name
        try:
            data[name] = p.read_bytes()
        except OSError:
            files[name] = "missing"
            continue
        h = _digest(data[name])
        files[name] = ("current" if h == _digest(shipped[name]) else
                       "older" if h in PREVIOUS.get(name, set()) else "modified")
    modified = [n for n, v in files.items() if v == "modified"]
    missing = [n for n, v in files.items() if v == "missing"]
    installed = files[VERSION_FILE] != "missing"
    return {"installed": installed, "complete": not missing, "version": version_of(data.get(VERSION_FILE)),
            "current_version": version_of(shipped[VERSION_FILE]),
            "outdated": installed and not modified and any(v == "older" for v in files.values()),
            "modified": modified, "missing": missing, "files": files, "path": str(d)}


def harness_present(project: Path | str) -> bool:
    """Whether the project has a HarnessCli unity.sh can use: ours, or any `class HarnessCli` in a
    .cs file under Assets/ or Packages/ (unity.sh's own check)."""
    root = Path(project).expanduser()
    install_dir = root / HARNESS_DIR
    if (install_dir / VERSION_FILE).is_file() or _find_class(install_dir):
        return True
    return external_harness(root) is not None


def external_harness(project: Path | str) -> str | None:
    """The relative path of the first HarnessCli class outside our install directory, if any."""
    root = Path(project).expanduser()
    for top in ("Assets", "Packages"):
        if p := _find_class(root / top, skip=root / HARNESS_DIR):
            return p.relative_to(root).as_posix()
    return None


def _find_class(directory: Path, *, skip: Path | None = None) -> Path | None:
    for dirpath, dirnames, filenames in os.walk(directory):
        if Path(dirpath) == skip:
            dirnames[:] = []
            continue
        dirnames[:] = [n for n in dirnames if not n.startswith(".")]
        for name in filenames:
            p = Path(dirpath) / name
            if name.endswith(".cs") and _has_class(p):
                return p
    return None


def _has_class(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            return b"class HarnessCli" in f.read(64 * 1024)
    except OSError:
        return False


def _write(p: Path, data: bytes) -> None:
    tmp = p.with_name(f".{p.name}.gdw-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)


def install_problem(project: Path, st: dict) -> str | None:
    """Preflight shared by the installer and its approval action; no project writes."""
    if not (project / "Assets").is_dir():
        return "Not installing: this project has no Assets directory."
    if not st["installed"] and (other := external_harness(project)):
        return (f"Not installing: {other} already defines class HarnessCli outside {HARNESS_DIR}. "
                "Installing another HarnessCli would create a duplicate type.")
    return None


def _install_marker(root: Path) -> dict:
    try:
        data = json.loads((root / MARKER).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def install_harness(project: Path | str, *, exclude_from_git: bool = True, allow_upgrade: bool = False) -> dict:
    """Copy the harness editor scripts into Assets/Harness/Headless/Editor/ (see the module doc).
    Returns {"ok", "status": installed | upgraded | up_to_date | modified | needs_upgrade_consent | error,
    "written", "message", "harness": status, "git_exclude"}; never overwrites an edited file and
    replaces an older shipped version only with allow_upgrade."""
    root = Path(project).expanduser().resolve()
    st = harness_status(root)
    base = {"path": st["path"], "harness": st}
    if problem := install_problem(root, st):
        return {**base, "ok": False, "status": "error", "written": [], "message": problem}
    if st["modified"]:
        return {**base, "ok": False, "status": "modified", "written": [],
                "message": (f"Not installing: {', '.join(st['modified'])} in {HARNESS_DIR} was changed in this project "
                            "(it matches no shipped version). Merge the changes by hand, or move the file away first.")}
    older = [n for n, v in st["files"].items() if v == "older"]
    if older and not allow_upgrade:
        return {**base, "ok": False, "status": "needs_upgrade_consent", "written": [],
                "message": f"The harness editor scripts are version {st['version']}; version "
                           f"{st['current_version']} replaces {', '.join(older)} (needs consent)."}
    if st["complete"] and not older:
        return {**base, "ok": True, "status": "up_to_date", "written": [], "git_exclude": None,
                "message": f"The harness editor scripts are installed and current (version {st['version']})."}
    created_harness = (_install_marker(root).get("created_harness") is True
                       or not (root / FOLDERS[0]).exists())
    shipped = _shipped()
    written: list[str] = []
    for rel in FOLDERS:
        (root / rel).mkdir(exist_ok=True)
        meta = root / f"{rel}.meta"
        if not meta.exists():
            _write(meta, meta_text(rel, folder=True).encode())
            written.append(f"{rel}.meta")
    for name in FILES:
        rel = f"{HARNESS_DIR}/{name}"
        if st["files"][name] in ("missing", "older"):
            _write(root / rel, shipped[name])
            written.append(rel)
        meta = root / f"{rel}.meta"
        if not meta.exists():
            _write(meta, meta_text(rel).encode())
            written.append(f"{rel}.meta")
    _write(root / MARKER, json.dumps({"created_harness": created_harness}).encode())
    excl = git_exclude(root, add=True, harness_meta=created_harness) if exclude_from_git else {"status": "off"}
    status = "upgraded" if older else "installed"
    after = harness_status(root)
    return {**base, "harness": after, "ok": True, "status": status, "written": written, "git_exclude": excl,
            "message": (f"Harness editor scripts {status} (version {after['version']}) in {HARNESS_DIR}"
                        + ("; kept out of git via .git/info/exclude" if excl.get("status") in ("added", "present") else "")
                        + ". Unity compiles them the next time it opens or refreshes the project.")}


def uninstall_harness(project: Path | str) -> dict:
    """Remove our files (and their .meta), then the harness folders left empty; an edited file
    stays (listed in "kept"). Our .git/info/exclude lines go once our folder is gone."""
    root = Path(project).expanduser().resolve()
    for rel in FOLDERS:
        if (root / rel).is_symlink():
            return {"ok": False, "removed": [], "kept": [rel], "git_exclude": {"status": "kept"},
                    "message": f"Not uninstalling: {rel} is a symlink; remove the harness manually."}
    st = harness_status(root)
    created_harness = _install_marker(root).get("created_harness") is True
    removed: list[str] = []
    kept: list[str] = []
    for name in FILES:
        rel = f"{HARNESS_DIR}/{name}"
        state = st["files"][name]
        if state == "missing":
            continue
        if state == "modified":
            kept.append(rel)
            continue
        (root / rel).unlink()
        removed.append(rel)
        meta = root / f"{rel}.meta"
        if meta.is_file():
            meta.unlink()
            removed.append(f"{rel}.meta")
    # Keep the ownership record until Headless can be removed, including after a partial uninstall.
    headless = root / "Assets/Harness/Headless"
    for rel in reversed(FOLDERS):
        d = root / rel
        if d.is_symlink() or not d.is_dir() or (rel == FOLDERS[0] and not created_harness):
            continue
        if d == headless and all(p.name in (".gdw-harness.json", ".DS_Store") for p in d.iterdir()):
            (root / MARKER).unlink(missing_ok=True)
        rest = [p for p in d.iterdir() if p.name != ".DS_Store"]
        if rest:
            continue
        for p in d.iterdir():
            p.unlink()
        d.rmdir()
        removed.append(rel + "/")
        meta = root / f"{rel}.meta"
        if meta.is_file():
            meta.unlink()
            removed.append(f"{rel}.meta")
    excl = (git_exclude(root, add=False, harness_meta=created_harness and not (root / FOLDERS[0]).exists())
            if not headless.exists() else {"status": "kept"})
    return {"ok": True, "removed": removed, "kept": kept, "git_exclude": excl,
            "message": (f"Removed {len([r for r in removed if not r.endswith('.meta')])} harness item(s)"
                        + (f"; kept {', '.join(kept)} (changed in this project)" if kept else "") + ".")}


# ------------------------------------------------------------------- git


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def exclude_lines(prefix: str, *, harness_meta: bool) -> list[str]:
    p = _GLOB_SPECIAL.sub(r"\\\1", prefix)
    lines = [f"{p}/Assets/Harness/Headless/", f"{p}/Assets/Harness/Headless.meta"]
    if harness_meta:
        lines.append(f"{p}/Assets/Harness.meta")
    return lines


def git_exclude(project: Path, *, add: bool, harness_meta: bool = False) -> dict:
    """Add (once) or remove our lines in the repository's info/exclude when `project` is in a git
    work tree. Patterns are relative to the work tree root (a project in a subfolder gets its
    prefix). {"status": added | present | removed | absent | not_git | error, "file", "lines"}."""
    root = Path(project).expanduser().resolve()
    if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
        return {"status": "not_git"}
    top = _git(root, "rev-parse", "--show-toplevel")
    path = _git(root, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    if not top or not path:
        return {"status": "error", "message": "couldn't locate the git work tree"}
    rel = os.path.relpath(root, Path(top).resolve())
    if rel.startswith(".."):
        return {"status": "error", "message": "the project isn't inside its git work tree"}
    prefix = "" if rel == "." else "/" + rel.replace(os.sep, "/")
    f = Path(path)
    try:
        text = f.read_text(encoding="utf-8") if f.is_file() else ""
    except OSError as e:
        return {"status": "error", "message": str(e)}
    have = text.splitlines()
    if add:
        want = exclude_lines(prefix, harness_meta=harness_meta)
        missing = [ln for ln in want if ln not in have]
        if not missing:
            return {"status": "present", "file": str(f), "lines": want}
        block = ([EXCLUDE_HEADER] if EXCLUDE_HEADER not in have else []) + missing
        new = text + ("" if not text or text.endswith("\n") else "\n") + "\n".join(block) + "\n"
    else:
        ours = set(exclude_lines(prefix, harness_meta=harness_meta))
        if not ours & set(have):
            return {"status": "absent", "file": str(f)}
        remaining = [ln for ln in have if ln not in ours]
        if EXCLUDE_HEADER in remaining:
            start = remaining.index(EXCLUDE_HEADER) + 1
            if not any(ln.strip() for ln in remaining[start:]):
                remaining.remove(EXCLUDE_HEADER)
        new = "".join(ln + "\n" for ln in remaining)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        _write(f, new.encode("utf-8"))
    except OSError as e:
        return {"status": "error", "message": str(e)}
    return {"status": "added" if add else "removed", "file": str(f),
            "lines": exclude_lines(prefix, harness_meta=harness_meta) if add else []}


__all__ = ["FILES", "HARNESS_DIR", "PREVIOUS", "external_harness", "git_exclude", "guid_for", "harness_present",
           "harness_status", "install_harness", "install_problem", "meta_text", "templates_dir", "uninstall_harness",
           "version_of"]
