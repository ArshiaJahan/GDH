"""`gdw eval forge`: turn a merged commit (or PR) into an Eval Forge task.

- start state: the commit's first parent
- grader: the commit's added/changed test files (hidden from the agent) + the command that runs them
- reference solution: the rest of the commit's diff
- prompt: the PR or commit text, run through the leak filter (it drops diffs and code blocks, and replaces the
  names, files and tests that only the solution introduces); optionally a model rewrites it first, through
  the effort gate, and the filter runs again on the rewrite.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Awaitable, Callable

from .eval_task import Forge, Grader, Limits, Source, Task, UnityGrader, write

# Test files: the grader's, never the agent's to see or change.
TEST_GLOBS = ("tests/*", "test/*", "*/tests/*", "*/test/*", "test_*.py", "*_test.py", "*/test_*.py",
              "*.test.ts", "*.test.tsx", "*.spec.ts", "*.test.js", "*/Tests/*", "*Tests.cs", "*Test.cs")
_TRAILER = re.compile(r"^(Co-Authored-By|Signed-off-by|Reviewed-by|Change-Id):.*$", re.I | re.M)
_FENCE = re.compile(r"```.*?```", re.S)
_DIFFLINE = re.compile(r"^(@@ .* @@.*|[+-]{3} [ab]/.*|diff --git .*|index [0-9a-f]+\.\.[0-9a-f]+.*)$", re.M)
# Names a change defines: Python, C#, TS/JS, and UPPER_CASE constants.
_DEFS = re.compile(r"\b(?:def|class|function|interface|enum|struct|record)\s+([A-Za-z_]\w{2,})"
                   r"|\b(?:const|let|var)\s+([A-Za-z_]\w{2,})\s*="
                   r"|^\s*(?:public|private|internal|protected|static|readonly|async|override|virtual|\s)+"
                   r"[\w<>\[\],?]+\s+([A-Z]\w{2,})\s*\("
                   r"|^\s*([A-Z][A-Z0-9_]{2,})\s*[:=]"
                   r"|^\s*public\s+(?:static\s+|readonly\s+|const\s+|override\s+|virtual\s+)*[\w<>\[\],?]+\s+"
                   r"([A-Z]\w{2,})\s*(?:=>|\{|=|;)", re.M)


class ForgeError(RuntimeError):
    pass


def _git(repo: Path, *args: str, binary: bool = False) -> str | bytes:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise ForgeError(f"git {' '.join(args[:3])} failed: {r.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def is_test_path(path: str, globs: tuple[str, ...] = TEST_GLOBS) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch(path, g) or fnmatch(name, g) for g in globs)


@dataclass
class Change:
    commit: str
    parent: str
    message: str
    added: list[str] = field(default_factory=list)       # paths the commit created
    changed: list[str] = field(default_factory=list)     # paths it modified
    deleted: list[str] = field(default_factory=list)

    def paths(self) -> list[str]:
        return self.added + self.changed + self.deleted


def read_change(repo: Path, rev: str) -> Change:
    commit = str(_git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}")).strip()
    parents = str(_git(repo, "rev-list", "--parents", "-n", "1", commit)).split()
    if len(parents) < 2:
        raise ForgeError(f"{commit[:12]} has no parent: there's no state to start from")
    parent = parents[1]
    msg = str(_git(repo, "show", "-s", "--format=%B", commit))
    ch = Change(commit, parent, msg)
    for line in str(_git(repo, "diff", "--name-status", "--no-renames", parent, commit)).splitlines():
        status, _, path = line.partition("\t")
        {"A": ch.added, "D": ch.deleted}.get(status[:1], ch.changed).append(path)
    if not ch.paths():
        raise ForgeError(f"{commit[:12]} changes no files")
    return ch


def _added_lines(patch: str) -> str:
    return "\n".join(l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))


def solution_only_names(repo: Path, parent: str, patch: str) -> list[str]:
    """Names the solution defines that don't exist anywhere in the starting tree."""
    names: set[str] = set()
    for m in _DEFS.finditer(_added_lines(patch)):
        names.update(g for g in m.groups() if g)
    out = []
    for n in sorted(names):
        r = subprocess.run(["git", "-C", str(repo), "grep", "-q", "-w", "-F", n, parent], capture_output=True, timeout=60)
        if r.returncode == 1:  # not found at the parent: the solution introduced it
            out.append(n)
    return out


MIN_DESCRIPTION_WORDS = 12
_STATEMENT = re.compile(r"^(?:return|raise|throw|await|yield|new|else|case|assert|if|elif|while|for|with|del|print)\b")
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".cs", ".rs", ".go")
_MODULE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go")  # the file name is the import (not C#)


def _added_by_file(patch: str) -> list[tuple[str, str]]:
    """[(path, added line)] in patch order."""
    out, path = [], ""
    for line in patch.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("+"):
            out.append((path, line[1:]))
    return out


def files_tests_use(paths: list[str], grader_files: dict[str, bytes]) -> list[str]:
    """The new files the hidden tests reach by path, file name or module name (where the file is the import):
    the tests can't be passed without them, so the task names them."""
    tests = "\n".join(d.decode("utf-8", "replace") for d in grader_files.values())
    out = []
    for path in paths:
        p = Path(path)
        if (path in tests or re.search(rf"(?<![\w.-]){re.escape(p.name)}\b", tests)
                or (p.suffix in _MODULE_SUFFIXES and re.search(rf"\b{re.escape(p.stem)}\b", tests))):
            out.append(path)
    return out


def interface(patch: str, grader_files: dict[str, bytes], limit: int = 20) -> list[tuple[str, str, str]]:
    """[(name, declaration, path)] for definitions the change adds or changes that the hidden tests use: the tests
    can't be passed without them, so the task names them. Declarations only (bodies are cut), in patch order."""
    tests = "\n".join(d.decode("utf-8", "replace") for d in grader_files.values())
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for path, line in _added_by_file(patch):
        if Path(path).suffix not in _CODE_SUFFIXES or _STATEMENT.match(line.strip()):
            continue  # `return Path(x)` or `raise Error(...)` is a call, not a declaration
        m = _DEFS.search(line)
        name = next((g for g in m.groups() if g), None) if m else None
        if m and m.group(2) and line[:1].isspace():
            continue  # a local `const x = ...` inside a function body isn't part of the interface
        if not name or name in seen or not re.search(rf"\b{re.escape(name)}\b", tests):
            continue
        seen.add(name)
        decl = re.split(r"\s*(?:=>|\{)", line.strip(), maxsplit=1)[0].rstrip(";").strip()
        if re.match(r"^[A-Z][A-Z0-9_]{2,}\s*[:=]", decl):
            decl = decl.split("=")[0].split(":")[0].strip()  # a constant's name, not its value
        out.append((name, decl, path))
        if len(out) >= limit:
            break
    return out


def interface_text(api: list[tuple[str, str, str]], used_files: list[str], new_paths: list[str]) -> str:
    """The prompt section that names what the hidden tests use, grouped by file."""
    if not api and not used_files:
        return ""
    new = set(new_paths)
    files = list(dict.fromkeys([p for _, _, p in api] + used_files))
    lines = ["Interface the tests use (declarations only; the change adds or changes these):"]
    for f in files:
        decls = [d for _, d, p in api if p == f]
        lines.append(f"- `{f}`" + (" (new file)" if f in new else "") + (":" if decls else ""))
        lines += [f"  - `{d}`" for d in decls]
    return "\n".join(lines)


def _test_names(grader_files: dict[str, bytes]) -> list[str]:
    names: set[str] = set()
    for data in grader_files.values():
        text = data.decode("utf-8", "replace")
        names.update(re.findall(r"\bdef (test_\w+)", text))
        names.update(re.findall(r"\b(?:it|test)\(\s*[\"']([^\"']{4,80})[\"']", text))
        names.update(m for m in re.findall(r"public\s+(?:void|IEnumerator|async\s+Task)\s+(\w+)\s*\(", text))
    return sorted(names)


def leak_filter(text: str, *, names: list[str], paths: list[str], tests: list[str]) -> tuple[str, list[str]]:
    """The task text without the solution in it. Returns (text, what was removed).

    Drops code blocks, diff lines and commit trailers; replaces names and new file paths only the solution
    has, and the hidden tests' names and paths. Names are replaced whole-word, longest first."""
    removed: list[str] = []
    out = _TRAILER.sub("", text)
    if _FENCE.search(out):
        removed.append("code block")
        out = _FENCE.sub("", out)
    if _DIFFLINE.search(out):
        removed.append("diff lines")
        out = _DIFFLINE.sub("", out)
    for label, items, repl in (("test", tests, "[hidden test]"), ("path", paths, "[new file]"),
                               ("name", names, "[new name]")):
        for item in sorted(set(items), key=len, reverse=True):
            pat = re.compile(re.escape(item) if label != "name" else rf"\b{re.escape(item)}\b")
            if pat.search(out):
                removed.append(f"{label}: {item}")
                out = pat.sub(repl, out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, removed


def default_command(tests: list[str]) -> str:
    py = [t for t in tests if t.endswith(".py") and not t.endswith(("__init__.py", "conftest.py"))]
    js = [t for t in tests if re.search(r"\.(test|spec)\.[jt]sx?$", t)]
    if py:
        return "python -m pytest -q " + " ".join(shlex.quote(t) for t in py)
    if js:
        return "npx vitest run " + " ".join(shlex.quote(t) for t in js)
    return ""


def pr_text(slug: str, number: int) -> tuple[str, str, str]:
    """(title + body, merge commit, repo slug) for a merged GitHub PR, through `gh`."""
    r = subprocess.run(["gh", "pr", "view", str(number), "-R", slug, "--json", "title,body,mergeCommit,state"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        raise ForgeError(f"gh pr view {number} failed: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    if d.get("state") != "MERGED" or not (d.get("mergeCommit") or {}).get("oid"):
        raise ForgeError(f"PR #{number} isn't merged")
    return f"{d.get('title') or ''}\n\n{d.get('body') or ''}", d["mergeCommit"]["oid"], slug


Rewrite = Callable[[str], Awaitable[str]]

REWRITE_SYSTEM = (
    "You turn a pull request description into a task for a coding agent. Write what the change must do and why, "
    "as a request a teammate would make, in plain words. Never say how it was implemented: no code, no function "
    "or class names that don't exist yet, no file names of new files, no test names. Keep every requirement and "
    "constraint. Reply with the task text only.")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:48].rstrip("-") or "task")


async def forge(repo: Path, rev: str, out_root: Path, *, task_id: str | None = None, command: str | None = None,
                text: str | None = None, pr: int | None = None, source_repo: str | None = None,
                test_globs: tuple[str, ...] = TEST_GLOBS, rewrite: Rewrite | None = None,
                rewritten_by: str = "", kind: str = "code", unity_replay: str = "", tags: list[str] | None = None,
                setup: str = "") -> Path:
    """Write one task directory under out_root and return it."""
    repo = Path(repo).resolve()
    ch = read_change(repo, rev)
    tests = [p for p in ch.added + ch.changed if is_test_path(p, test_globs)]
    source_paths = [p for p in ch.paths() if not is_test_path(p, test_globs)]
    if not tests and not command and kind != "unity":
        raise ForgeError(f"{ch.commit[:12]} adds or changes no tests, so there's nothing to grade with "
                         "(pass --command or pick a commit with tests)")
    if not source_paths:
        raise ForgeError(f"{ch.commit[:12]} only changes tests: there's no solution to ask for")
    grader_files = {p: bytes(_git(repo, "show", f"{ch.commit}:{p}", binary=True)) for p in tests}
    solution = str(_git(repo, "diff", "--binary", "--no-renames", ch.parent, ch.commit, "--", *source_paths))
    body = text if text is not None else ch.message
    api = interface(solution, grader_files)
    needed = {n for n, _, _ in api}
    names = [n for n in solution_only_names(repo, ch.parent, solution) if n not in needed]
    new_paths = [p for p in ch.added if p in source_paths]
    used_files = files_tests_use(new_paths, grader_files)
    new_paths = [p for p in new_paths if p not in used_files]  # named in the interface, so not hidden
    hidden = _test_names(grader_files) + tests
    prompt, removed = leak_filter(body, names=names, paths=new_paths, tests=hidden)
    if rewrite is not None:
        prompt, more = leak_filter(await rewrite(prompt), names=names, paths=new_paths, tests=hidden)
        removed += [r for r in more if r not in removed]
    if not prompt.strip():
        raise ForgeError("the task text is empty after the leak filter; pass --text with a description")
    if len(prompt.split()) < MIN_DESCRIPTION_WORDS:
        # A title alone can't specify what the hidden tests check (2026-11-20: a one-line commit had 71 tests).
        raise ForgeError(f"the task text is only a title (under {MIN_DESCRIPTION_WORDS} words); "
                         "pass --text with what the change must do")
    section = interface_text(api, used_files, [p for p in ch.added if p in source_paths])
    if section:
        prompt += "\n\n" + section
    title = body.strip().splitlines()[0][:120] if body.strip() else ch.commit[:12]
    tid = task_id or f"{_slug(title)}-{ch.commit[:7]}"
    task = Task(
        id=tid, title=title, kind=kind, tags=list(tags or []),  # type: ignore[arg-type]
        source=Source(repo=source_repo or str(repo), commit=ch.commit, parent=ch.parent, pr=pr, title=title),
        grader=Grader(command=command if command is not None else default_command(tests), tests=tests,
                      setup=setup, unity=UnityGrader(replay=unity_replay) if kind == "unity" else None),
        limits=Limits(),
        forge=Forge(removed=removed, rewritten_by=rewritten_by,
                    forged_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    return write(task, Path(out_root) / tid, prompt=prompt, solution=solution, grader_files=grader_files)
