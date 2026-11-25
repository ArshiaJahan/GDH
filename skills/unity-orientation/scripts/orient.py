#!/usr/bin/env python3
"""Map a Unity project for a new session in one cheap, read-only pass.

    orient.py [<folder>] [--refresh] [--json] [--max-todos 12]

Finds the Unity project (the folder or one up to 3 levels below), its docs and handoff notes (read
by heading, not whole), its tools (graphify graph, MCP for Unity, tests, CI), Unity facts (through
project-memory's project_snapshot.py when it is installed), git state, and the open to-dos:
BACKLOG.md stories in progress, then to do; next steps in handoff docs; unchecked TODO.md items.

The map is cached in <project>/.gdw/orientation.json with a fingerprint (git HEAD, working-tree
changes, the docs' sizes and mtimes). A repeat run prints `CACHED`, and lists only the docs that
changed since the last orientation, so a session re-reads just those. Prints markdown (or --json)
and a last line `RESULT: OK todos=N changed_docs=N cached=yes|no`. Python 3.9+ standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CACHE_VERSION = 3
DOC_FOLDERS = {"HandOffDocs", "docs", "Docs", "design", "production"}
MAX_TRACKED_DOCS = 60
MAX_FOLDER_DOCS = 6
SKIP_DIRS = {"Library", "Temp", "Logs", "obj", "Build", "Builds", "UserSettings", "node_modules", ".git", ".gdw",
             "PackageCache", "MemoryCaptures", "Recordings", "builds"}
# Docs in the order a session should read them (first match wins per row). Globs relative to the root.
DOC_ROWS = [
    ("rules", ["AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md", ".cursorrules", ".github/copilot-instructions.md"]),
    ("handoff", ["HandOffDocs/README.md", "HANDOFF.md", "HANDOFF*.md", "docs/HANDOFF*.md", "docs/handoff*.md",
                 "claude-progress.txt", "PROGRESS.md", "progress.md"]),
    ("central", ["PROJECT_OVERVIEW.md", "*OVERVIEW*.md", "ARCHITECTURE.md", "docs/README.md", "docs/index.md",
                 "Docs/README.md", "Docs/index.md"]),
    ("session log", ["HandOffDocs/SESSION-LOG.md", "SESSION-LOG.md", "docs/SESSION-LOG.md"]),
    ("project memory", ["PROJECT.md"]),
    ("backlog", ["BACKLOG.md", "docs/BACKLOG.md"]),
    ("todo", ["TODO.md", "docs/TODO.md"]),
    ("design", ["GDD.md", "*GDD*.md", "design/*.md", "docs/design/*.md", "docs/GDD*.md"]),
    ("taste", ["TASTE.md"]),
    ("postmortems", ["POSTMORTEMS.md"]),
    ("readme", ["README.md", "Readme.md", "readme.md"]),
    ("changelog", ["CHANGELOG.md"]),
]
NEXT_HEADING = re.compile(r"^#{1,4}\s*(next steps?|todo|to do|to-do|open (items|tasks|questions)|what'?s next|"
                          r"remaining|backlog|up next|pending)\b", re.I)
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[( |x|X)\]\s+)?(.*\S)")
STORY = re.compile(r"^###\s+(M\d+-S\d+)\s+(.*)$")
MILESTONE = re.compile(r"^##\s+(M\d+)\s+(.*)$")
STATUS = re.compile(r"^\s*-?\s*Status:\s*(\w+)", re.I)


def run(cmd: list[str], cwd: Path, timeout: float = 5.0) -> str:
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def read(p: Path, limit: int = 400_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def is_unity(p: Path) -> bool:
    return (p / "ProjectSettings" / "ProjectVersion.txt").is_file()


def find_projects(folder: Path, depth: int = 3) -> list[Path]:
    if is_unity(folder):
        return [folder]
    found, frontier = [], [folder]
    for _ in range(depth):
        nxt = []
        for d in frontier:
            try:
                subs = [s for s in d.iterdir() if s.is_dir() and s.name not in SKIP_DIRS and not s.name.startswith(".")]
            except OSError:
                continue
            for s in subs:
                (found if is_unity(s) else nxt).append(s)
        frontier = nxt
    return sorted(found)


# ------------------------------------------------------------------ docs


def headings(text: str, limit: int = 8) -> list[str]:
    out = [ln.lstrip("#").strip() for ln in text.splitlines() if re.match(r"^#{1,3}\s", ln)]
    return out[:limit]


def docs(root: Path) -> tuple[list[dict], dict[str, dict]]:
    # Use directory entries so case-insensitive filesystems report each folder once.
    folders = {}
    for folder in sorted(root.iterdir()):
        if folder.name in DOC_FOLDERS and folder.is_dir():
            folders[folder.name] = [
                p.relative_to(root) for p in sorted(folder.rglob("*.md"))
                if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(folder).parts)
            ]
    folder_paths = {p for paths in folders.values() for p in paths}
    by_casefold = {str(p).casefold(): p for p in sorted(folder_paths)}
    candidates = {}
    for kind, globs in DOC_ROWS:
        for g in globs:
            for p in sorted(root.glob(g)):
                rel = p.relative_to(root)
                if not p.is_file() or SKIP_DIRS.intersection(rel.parts):
                    continue
                if rel not in folder_paths:
                    actual = by_casefold.get(str(rel).casefold())
                    if actual is not None and p.samefile(root / actual):
                        rel = actual
                candidates.setdefault(rel, kind)
            if kind in candidates.values() and kind not in ("design", "handoff", "rules", "central"):
                break

    # Track top-level docs before the nested inventory. Prefer recognized docs within each group.
    visible = {p for p in candidates if p.parts[0] not in folders}
    for folder, paths in folders.items():
        top_level = [p for p in candidates if p.parts[0] == folder and len(p.parts) == 2]
        top_level.extend(p for p in paths if len(p.parts) == 2 and p not in candidates)
        visible.update(top_level[:MAX_FOLDER_DOCS])
    for p in sorted(folder_paths, key=lambda p: (len(p.parts) > 2, p)):
        candidates.setdefault(p, f"{p.parts[0]}/")

    out = []
    for p in sorted(candidates, key=lambda p: p not in visible):
        try:
            st = (root / p).stat()
            data = (root / p).read_bytes()
        except OSError:
            continue
        kind = candidates[p]
        doc_text = data[:400_000].decode("utf-8", errors="replace") if not kind.endswith("/") else ""
        out.append({"kind": kind, "path": str(p), "lines": doc_text.count("\n") + 1 if doc_text else None,
                    "bytes": st.st_size, "mtime": st.st_mtime_ns, "headings": headings(doc_text),
                    "sha": hashlib.sha1(data).hexdigest()[:12], "listed": p in visible})
        if len(out) >= MAX_TRACKED_DOCS:
            break

    listed = {d["path"] for d in out if d["listed"]}
    summaries = {}
    for folder, paths in folders.items():
        hidden = [p for p in paths if str(p) not in listed]
        if hidden:
            prefix = os.path.commonpath([str(p.parent) for p in hidden])
            subs: dict[str, int] = {}
            for h in hidden:
                if len(h.parts) > 2:
                    subs[h.parts[1]] = subs.get(h.parts[1], 0) + 1
            top = sorted(subs.items(), key=lambda kv: -kv[1])[:6]
            summaries[folder] = {"prefix": prefix, "count": len(hidden), "subfolders": top}
    return out, summaries


def last_log_entry(root: Path, rel: str) -> str:
    text = read(root / rel)
    parts = re.split(r"(?m)^(?=#{1,3}\s)", text)
    entries = [p.strip() for p in parts if p.strip().startswith("#")]
    if not entries:
        return ""
    # Logs are appended at the bottom (most do) or prepended at the top: take the newest-looking one.
    dated = [(re.search(r"20\d\d-\d\d-\d\d", e.splitlines()[0]), e) for e in entries]
    with_dates = [(m.group(0), e) for m, e in dated if m]
    entry = max(with_dates)[1] if with_dates else entries[-1]
    lines = entry.splitlines()
    return "\n".join(lines[:12]) + ("\n…" if len(lines) > 12 else "")


# ------------------------------------------------------------------ to-dos


def backlog_todos(root: Path, rel: str) -> tuple[list[dict], list[dict], str]:
    text = read(root / rel)
    todos, blocked, active, milestone, story = [], [], "", "", None
    lines = text.splitlines()
    for i, ln in enumerate(lines, 1):
        if m := MILESTONE.match(ln):
            milestone, story = m.group(1), None
            for nxt in lines[i:i + 4]:
                if (s := STATUS.match(nxt)) and s.group(1).lower() == "active":
                    active = f"{m.group(1)} {m.group(2).strip()}"
            continue
        if m := STORY.match(ln):
            story = {"id": m.group(1), "title": m.group(2).strip(), "milestone": milestone, "source": f"{rel}:{i}"}
            continue
        if story and (s := STATUS.match(ln)):
            st = s.group(1).lower()
            story = {**story, "status": st}
            if st in ("doing", "todo", "active"):
                todos.append(story)
            elif st == "blocked":
                blocked.append(story)
            story = None
    act = active.split()[0] if active else ""
    todos.sort(key=lambda t: (t["status"] != "doing", t["milestone"] != act, t["milestone"], t["id"]))
    return todos, blocked, active


def section_bullets(root: Path, rel: str, limit: int = 10) -> list[dict]:
    """Bullets under 'Next steps' / 'TODO' style headings, skipping checked boxes."""
    out, inside, level = [], False, 0
    for i, ln in enumerate(read(root / rel).splitlines(), 1):
        h = re.match(r"^(#{1,6})\s", ln)
        if h:
            inside, level = bool(NEXT_HEADING.match(ln)), len(h.group(1))
            continue
        if inside and (b := BULLET.match(ln)) and (b.group(1) or " ") == " ":
            out.append({"title": b.group(2)[:160], "source": f"{rel}:{i}", "status": "todo"})
            if len(out) >= limit:
                break
    return out


def unchecked(root: Path, rel: str, limit: int = 10) -> list[dict]:
    out = []
    for i, ln in enumerate(read(root / rel).splitlines(), 1):
        if (b := BULLET.match(ln)) and b.group(1) == " ":
            out.append({"title": b.group(2)[:160], "source": f"{rel}:{i}", "status": "todo"})
            if len(out) >= limit:
                break
    return out


def code_todos(root: Path) -> tuple[int, list[str]]:
    assets = root / "Assets"
    if not assets.is_dir():
        return 0, []
    # The project's own code: third-party folders' markers aren't this project's to-dos.
    out = run(["git", "grep", "-I", "-w", "-c", "-E", "TODO|FIXME|HACK", "--", "Assets/*.cs",
               ":(exclude,glob)**/ThirdParty/**", ":(exclude,glob)**/Plugins/**", ":(exclude,glob)**/Samples/**",
               ":(exclude,glob)Assets/TextMesh Pro/**"], root)
    rows = []
    for ln in out.splitlines():
        path, _, n = ln.rpartition(":")
        if n.isdigit():
            rows.append((int(n), path))
    rows.sort(reverse=True)
    return sum(n for n, _ in rows), [f"{p} ({n})" for n, p in rows[:3]]


# ------------------------------------------------------------------ project facts


def unity_facts(root: Path) -> dict:
    snap = Path(__file__).resolve().parents[2] / "project-memory" / "scripts" / "project_snapshot.py"
    if snap.is_file():
        out = run([sys.executable, "-I", str(snap), "--project", str(root), "--json"], root, timeout=20)
        if out:
            try:
                f = json.loads(out[: out.rfind("}") + 1])
                return {"unity": f.get("unity", ""), "product": f.get("product", ""), "input": f.get("input", ""),
                        "pipeline": (f.get("pipeline") or {}).get("default") or "Built-in",
                        "renderers": [r.get("kind") for r in (f.get("pipeline") or {}).get("renderers", [])],
                        "packages": [p["name"] for p in f.get("packages", []) if not p["name"].startswith("com.unity.modules")],
                        "scenes": f.get("scenes") or f.get("build_scenes") or [],
                        "asmdefs": len(f.get("asmdefs", [])), "source": "project_snapshot.py"}
            except (ValueError, KeyError, TypeError):
                pass
    ver = re.search(r"m_EditorVersion:\s*(\S+)", read(root / "ProjectSettings" / "ProjectVersion.txt"))
    try:
        pkgs = sorted(json.loads(read(root / "Packages" / "manifest.json")).get("dependencies", {}))
    except ValueError:
        pkgs = []
    scenes = re.findall(r"(?m)^\s*path:[ \t]*(.+?\.unity)[ \t]*$",
                        read(root / "ProjectSettings" / "EditorBuildSettings.asset"))
    return {"unity": ver.group(1) if ver else "?", "packages": [p for p in pkgs if not p.startswith("com.unity.modules")],
            "scenes": scenes, "asmdefs": len(list((root / "Assets").rglob("*.asmdef"))) if (root / "Assets").is_dir() else 0,
            "source": "manifest + ProjectSettings"}


def layout(root: Path, limit: int = 12) -> list[str]:
    assets = root / "Assets"
    rows = []
    if not assets.is_dir():
        return rows
    for d in sorted(p for p in assets.iterdir() if p.is_dir() and not p.name.startswith(".")):
        cs = scenes = prefabs = 0
        for p in d.rglob("*"):
            s = p.suffix
            cs += s == ".cs"
            scenes += s == ".unity"
            prefabs += s == ".prefab"
        if cs or scenes or prefabs:
            rows.append((cs + scenes + prefabs, f"{d.name}/ ({cs} cs, {scenes} scenes, {prefabs} prefabs)"))
    rows.sort(reverse=True)
    return [r for _n, r in rows[:limit]]


def tools(root: Path, facts: dict) -> list[str]:
    out = []
    graph = next((p for p in (root / "graphify-out", root.parent / "graphify-out") if p.is_dir()), None)
    if graph:
        age = int((time.time() - max((f.stat().st_mtime for f in graph.iterdir() if f.is_file()), default=0)) / 86400)
        out.append(f"graphify graph at {graph if graph.parent != root else 'graphify-out/'} ({age} d old): use graphify "
                   "query/path/explain for targeted lookups before reading files")
    pk = set(facts.get("packages", []))
    if "com.coplaydev.unity-mcp" in pk:
        out.append("MCP for Unity package installed (editor control when the editor is open)")
    if "com.unity.test-framework" in pk:
        tests = [p for p in (root / "Assets").rglob("*.asmdef") if "test" in p.name.lower()] if (root / "Assets").is_dir() else []
        out.append(f"Unity Test Framework; {len(tests)} test assemblies")
    if (root / ".github" / "workflows").is_dir():
        out.append("CI: .github/workflows/" + ", ".join(sorted(p.name for p in (root / ".github" / "workflows").glob("*.y*ml"))[:4]))
    if (root / ".claude").is_dir():
        kinds = [k for k in ("skills", "agents", "commands", "hooks") if (root / ".claude" / k).exists()]
        out.append(".claude/ (" + (", ".join(kinds) or "settings") + ")")
    if (root / ".gamedevworkstation" / "campaigns").is_dir():
        out.append("GDW campaigns: " + ", ".join(p.stem for p in (root / ".gamedevworkstation" / "campaigns").glob("*.md"))[:120])
    if (root / "Temp" / "UnityLockfile").exists():
        out.append("Temp/UnityLockfile exists: the editor may have the project open (no batchmode)")
    if "lfs" in read(root / ".gitattributes"):
        out.append("Git LFS in .gitattributes")
    return out


def git_state(root: Path) -> dict:
    if not run(["git", "rev-parse", "--is-inside-work-tree"], root):
        return {}
    dirty = run(["git", "--no-optional-locks", "status", "--porcelain"], root).splitlines()
    return {"branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root),
            "head": run(["git", "rev-parse", "--short", "HEAD"], root), "dirty": len(dirty),
            "recent": run(["git", "log", "-5", "--format=%ad %s", "--date=short"], root).splitlines()}


# ------------------------------------------------------------------ cache


def fingerprint(root: Path, doc_list: list[dict]) -> str:
    h = hashlib.sha1()
    h.update(run(["git", "rev-parse", "HEAD"], root).encode())
    h.update(run(["git", "--no-optional-locks", "status", "--porcelain"], root).encode())
    for rel in ("Packages/manifest.json", "ProjectSettings/EditorBuildSettings.asset", "ProjectSettings/ProjectVersion.txt"):
        try:
            st = (root / rel).stat()
            h.update(f"{rel}:{st.st_size}:{int(st.st_mtime)}".encode())
        except OSError:
            pass
    for d in doc_list:
        h.update(f"{d['path']}:{d['sha']}".encode())
    return h.hexdigest()[:16]


def orient(folder: Path, refresh: bool = False, max_todos: int = 12, write: bool = True) -> dict:
    projects = find_projects(folder)
    if not projects:
        return {"error": f"no Unity project (ProjectSettings/ProjectVersion.txt) in {folder} or 3 levels below"}
    root = projects[0]
    cache_file = root / ".gdw" / "orientation.json"
    try:
        old = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.is_file() else None
    except ValueError:
        old = None
    doc_list, doc_summaries = docs(root)
    fp = fingerprint(root, doc_list)
    if old and old.get("version") == CACHE_VERSION and old.get("fingerprint") == fp and not refresh:
        return {**old, "docs": doc_list, "doc_summaries": doc_summaries, "cached": True, "changed_docs": [],
                "other_projects": [str(p) for p in projects[1:]]}
    prev = {d["path"]: d["sha"] for d in (old or {}).get("docs", [])}
    changed = [d["path"] for d in doc_list if prev.get(d["path"]) != d["sha"]] if old else []
    facts = unity_facts(root)
    todos, blocked, active = [], [], ""
    for d in doc_list:
        if d["kind"] == "backlog" and not todos:
            todos, blocked, active = backlog_todos(root, d["path"])
    for d in doc_list:
        if d["kind"] in ("handoff", "central", "project memory", "session log", "HandOffDocs/"):
            todos += section_bullets(root, d["path"])
        if d["kind"] == "todo":
            todos += unchecked(root, d["path"])
    seen, uniq = set(), []
    for t in todos:
        key = t.get("id") or t["title"].lower()
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    n_code, code_top = code_todos(root)
    log = next((d["path"] for d in doc_list if d["kind"] == "session log"), "")
    result = {
        "version": CACHE_VERSION, "fingerprint": fp, "at": time.strftime("%Y-%m-%d %H:%M"), "root": str(root),
        "facts": facts, "layout": layout(root), "tools": tools(root, facts), "git": git_state(root),
        "docs": doc_list, "doc_summaries": doc_summaries,
        "active_milestone": active, "todos": uniq[:max_todos], "todos_total": len(uniq),
        "blocked": blocked[:5], "code_todos": n_code, "code_todo_files": code_top,
        "last_session": last_log_entry(root, log) if log else "",
    }
    try:
        if not write:
            raise OSError("--no-write")
        cache_file.parent.mkdir(exist_ok=True)
        cache_file.write_text(json.dumps(result, indent=1), encoding="utf-8")
        ignore = root / ".gdw" / ".gitignore"
        if not ignore.exists():
            ignore.write_text("orientation.json\n", encoding="utf-8")  # a per-machine cache, not project content
    except OSError:
        pass
    return {**result, "cached": False, "changed_docs": changed, "other_projects": [str(p) for p in projects[1:]]}


def render(r: dict) -> str:
    if "error" in r:
        return f"RESULT: FAIL {r['error']}"
    f, g = r["facts"], r.get("git") or {}
    L = [f"# Orientation: {Path(r['root']).name} ({'CACHED, unchanged since ' + r['at'] if r['cached'] else 'fresh scan'})",
         f"root: {r['root']}" + (f"  (other Unity projects: {', '.join(r['other_projects'])})" if r["other_projects"] else ""),
         f"unity: {f.get('unity', '?')} | pipeline: {f.get('pipeline', '?')} {'/'.join(x for x in f.get('renderers', []) if x)}"
         f" | input: {f.get('input', '?')} | asmdefs: {f.get('asmdefs', 0)} | packages: {len(f.get('packages', []))}"]
    scenes = [s["path"] if isinstance(s, dict) else s for s in f.get("scenes", [])]
    if scenes:
        L.append("build scenes: " + ", ".join(Path(s).stem for s in scenes[:8]))
    if g:
        L.append(f"git: {g['branch']} @ {g['head']}, {g['dirty']} uncommitted; last: {(g['recent'] or ['-'])[0]}")
    if r["layout"]:
        L.append("assets: " + "; ".join(r["layout"][:8]))
    if r["tools"]:
        L += ["", "## Tools"] + [f"- {t}" for t in r["tools"]]
    doc_start = len(L)
    doc_rows = []
    changed = set(r["changed_docs"])
    for d in r["docs"]:
        if not d["listed"]:
            continue
        mark = " **CHANGED**" if d["path"] in changed else ""
        if d["kind"].endswith("/"):
            doc_rows.append(f"- {d['path']}{mark}")
            continue
        hs = f": {' / '.join(d['headings'][:5])}" if d["headings"] else ""
        doc_rows.append(f"- [{d['kind']}] {d['path']}{mark}{hs}"[:220])
    hidden_changes = {
        Path(d["path"]).parts[0] for d in r["docs"] if not d["listed"] and d["path"] in changed
    }
    summaries = []
    for folder, summary in r["doc_summaries"].items():
        mark = " **CHANGED**" if folder in hidden_changes else ""
        subs = ", ".join(f"{n}/ {c}" for n, c in summary.get("subfolders", []))
        summaries.append(f"- {summary['prefix']}/ (+{summary['count']} more .md{': ' + subs if subs else ''}){mark}")
    if r["last_session"]:
        L += ["", "## Last session (newest log entry)", r["last_session"]]
    L += ["", f"## Open to-dos ({r['todos_total']}{', active milestone ' + r['active_milestone'] if r['active_milestone'] else ''})"]
    for i, t in enumerate(r["todos"], 1):
        L.append(f"{i}. {(t.get('id', '') + ' ').lstrip()}{t['title']} [{t['status']}] ({t['source']})")
    if not r["todos"]:
        L.append("- none found in BACKLOG.md, handoff docs or TODO.md")
    if r["blocked"]:
        L.append("blocked: " + "; ".join(f"{b['id']} {b['title']}" for b in r["blocked"]))
    if r["code_todos"]:
        L.append(f"code TODO/FIXME/HACK: {r['code_todos']} (top: {', '.join(r['code_todo_files'])})")
    L.append(f"RESULT: OK todos={r['todos_total']} changed_docs={len(r['changed_docs'])} cached={'yes' if r['cached'] else 'no'}")
    space = max(1, 58 - sum(len(line.splitlines()) or 1 for line in L) - len(summaries))
    if len(doc_rows) > space:
        omitted = len(doc_rows) - space + 1
        doc_rows = doc_rows[:space - 1] + [f"- {omitted} more docs in --json"]
    L[doc_start:doc_start] = ["", "## Docs"] + (doc_rows + summaries or ["- none found"])
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", nargs="?", default=".", type=Path)
    ap.add_argument("--refresh", action="store_true", help="rescan even when nothing changed")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-todos", type=int, default=12)
    ap.add_argument("--no-write", action="store_true", help="don't write the cache (read-only run)")
    a = ap.parse_args(argv)
    r = orient(a.folder.expanduser().resolve(), a.refresh, a.max_todos, write=not a.no_write)
    print(json.dumps(r, indent=1) if a.json else render(r))
    return 0 if "error" not in r else 1


if __name__ == "__main__":
    sys.exit(main())
