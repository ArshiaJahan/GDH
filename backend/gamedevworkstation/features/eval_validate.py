"""Grader validation: does the grader tell a correct solution from a flawed one?

The reference solution must pass. Then flawed solutions made from it must fail:
- no-op         the start state, unchanged
- partial       the reference with one hunk left out (a fix that's only partly done)
- mutant        the reference with one small semantic change on an added line (flipped comparison, off-by-one
                constant, swapped boolean, return value dropped, and/or swapped, sign flipped)
- tamper        no fix, but the hidden tests deleted or rewritten to pass: the grader must lay the originals
                back and still fail it

A flawed solution that passes "survives": the grader can't see that flaw. The report gives the kill rate and
lists every survivor, so a task with a weak grader is visible before anyone trusts its scores. Some mutants are
equivalent (they don't change behaviour); a survivor is a reason to look, not proof of a bad grader.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import tokenize
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import eval_grade
from .eval_task import LoadedTask

REPORT_FILE = "validation.json"

# (pattern on an added line, replacement, label). Applied one at a time, first match on the line.
MUTATIONS: tuple[tuple[str, str, str], ...] = (
    (r"(?<=\s)==(?=\s)", "!=", "== to !="),
    (r"(?<=\s)!=(?=\s)", "==", "!= to =="),
    (r"(?<=\s)<=(?=\s)", "<", "<= to <"),
    (r"(?<=\s)>=(?=\s)", ">", ">= to >"),
    (r"(?<=\s)<(?=\s)", "<=", "< to <="),     # spaced only: not generics, tags or arrows
    (r"(?<=\s)>(?=\s)", ">=", "> to >="),
    (r"\bTrue\b", "False", "True to False"),
    (r"\bFalse\b", "True", "False to True"),
    (r"\btrue\b", "false", "true to false"),
    (r"\bfalse\b", "true", "false to true"),
    (r"\band\b", "or", "and to or"),
    (r"&&", "||", "&& to ||"),
    (r"\bor\b", "and", "or to and"),
    (r"\|\|", "&&", "|| to &&"),
    (r"(?<![\w.])(\d+)(?![\w.])", None, "constant +1"),
    (r"(\breturn\s+)(?!None\b|null\b|;)([^;\n]+)", r"\1None", "return value dropped"),
    (r"(?<=[\w)\]])\s*\+\s*(?=[\w(])", " - ", "+ to -"),
    (r"(?<=[\w)\]])\s+-\s+(?=[\w(])", " + ", "- to +"),
)
# Flawed solutions are made from code only: leaving out a README or CI hunk, or flipping a YAML value, isn't a flaw
# the task's tests are meant to catch, and counting it would make every grader look weak.
CODE_EXT = (".py", ".cs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cc",
            ".cpp", ".h", ".hpp", ".rb", ".php", ".lua", ".gd", ".shader", ".hlsl", ".cginc")
_SKIP_LINE = re.compile(r"^\s*(#|//|/\*|\*|import |from |using |\"\"\"|'''|$)")


@dataclass
class Candidate:
    id: str
    kind: str          # reference | noop | partial | mutant | tamper
    description: str
    patch: str
    tamper: str = ""   # "", "delete" or "skip"


@dataclass
class Outcome:
    id: str
    kind: str
    description: str
    passed: bool
    environment_failure: bool
    tampered: list[str]
    failed_steps: list[str]


@dataclass
class Report:
    task: str
    validated_at: str
    reference_passed: bool
    flawed: int
    killed: int
    kill_rate: float
    survivors: list[Outcome] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    reference_steps: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.reference_passed and self.flawed > 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


# ------------------------------------------------------------------ patch surgery


def split_hunks(patch: str) -> list[tuple[str, list[str]]]:
    """[(file header, [hunk text, ...]), ...] for a unified diff (binary file sections keep no hunks)."""
    files: list[tuple[str, list[str]]] = []
    header: list[str] = []
    hunks: list[list[str]] = []
    in_hunk = False
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if header:
                files.append(("".join(header), ["".join(h) for h in hunks]))
            header, hunks, in_hunk = [line], [], False
        elif line.startswith("@@"):
            hunks.append([line])
            in_hunk = True
        elif in_hunk:
            hunks[-1].append(line)
        else:
            header.append(line)
    if header:
        files.append(("".join(header), ["".join(h) for h in hunks]))
    return files


def join_hunks(files: list[tuple[str, list[str]]]) -> str:
    return "".join(h + "".join(hs) for h, hs in files if hs or "GIT binary patch" in h or "Binary files" in h)


def _path(header: str) -> str:
    m = re.search(r" b/(\S+)", header)
    return m.group(1) if m else ""


def is_code(path: str) -> bool:
    return path.lower().endswith(CODE_EXT)


def partials(patch: str, limit: int) -> list[Candidate]:
    """The reference with one code hunk left out (only when there's more than one hunk to choose from)."""
    files = split_hunks(patch)
    spots = [(fi, hi) for fi, (h, hs) in enumerate(files) if is_code(_path(h)) for hi in range(len(hs))]
    if len(spots) < 2:
        return []
    out = []
    for n, (fi, hi) in enumerate(spots[:limit]):
        kept = [(h, [x for j, x in enumerate(hs) if not (i == fi and j == hi)]) for i, (h, hs) in enumerate(files)]
        name = re.search(r" b/(\S+)", files[fi][0])
        out.append(Candidate(f"partial-{n + 1}", "partial",
                             f"leaves out hunk {hi + 1} of {name.group(1) if name else 'a file'}", join_hunks(kept)))
    return out


def _in_string(text: str, pos: int) -> bool:
    """Whether `pos` is inside a quoted string or after a line comment on this line (a rough, per-line check)."""
    quote = None
    i = 0
    while i < pos:
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c == "#" or text.startswith("//", i):
            return True
        i += 1
    return quote is not None


def _mutate_line(text: str, pattern: str, repl: str | None) -> str | None:
    """The line with the first match of `pattern` that's in code (not in a string or comment) mutated."""
    for m in re.finditer(pattern, text):
        if _in_string(text, m.start()):
            continue
        if repl is None:  # constant +1
            return text[:m.start(1)] + str(int(m.group(1)) + 1) + text[m.end(1):]
        new = text[:m.start()] + m.expand(repl) + text[m.end():]
        return new if new != text else None
    return None


def python_code_lines(source: str) -> set[int] | None:
    """1-based numbers of the lines that hold Python code tokens (not only strings, comments or blank space);
    None when the file doesn't tokenize."""
    rows: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.NAME, tokenize.OP, tokenize.NUMBER):
                rows.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return rows


def code_line_map(repo: Path, commit: str, patch: str) -> dict[str, set[int]]:
    """{path: code line numbers} for the patch's Python files as they are after the change."""
    out: dict[str, set[int]] = {}
    for header, _ in split_hunks(patch):
        path = _path(header)
        if not path.endswith(".py"):
            continue
        r = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], capture_output=True, timeout=60)
        if r.returncode == 0 and (rows := python_code_lines(r.stdout.decode("utf-8", "replace"))) is not None:
            out[path] = rows
    return out


def mutants(patch: str, limit: int, code_map: dict[str, set[int]] | None = None) -> list[Candidate]:
    """One mutation per candidate, on added code lines, spread across the patch (each line used once).

    With `code_map` (path -> code line numbers after the change), a Python line is only mutated when it holds
    code, so prose in a docstring or a multi-line string whose quotes sit outside the hunk is left alone."""
    lines = patch.splitlines(keepends=True)
    out: list[Candidate] = []
    used_lines: set[int] = set()
    code_lines: set[int] = set()
    current, in_doc, new_no = "", False, 0
    for i, line in enumerate(lines):
        if line.startswith("diff --git "):
            current, in_doc = _path(line), False
            continue
        if line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            new_no = int(m.group(1)) if m else 0
            continue
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("-"):
            continue
        row, new_no = new_no, new_no + 1
        if not is_code(current) or not line.startswith("+"):
            continue
        body = line[1:]
        fences = body.count('"""') + body.count("'''")
        known = (code_map or {}).get(current)
        if known is not None:
            if row in known and not fences:
                code_lines.add(i)
        elif not in_doc and not fences:
            code_lines.add(i)
        if fences % 2:  # a Python docstring opens or closes on this line
            in_doc = not in_doc
    for pattern, repl, label in MUTATIONS:
        for i, line in enumerate(lines):
            if len(out) >= limit:
                return out
            if i in used_lines or i not in code_lines or not line.startswith("+") or line.startswith("+++"):
                continue
            body = line[1:]
            if _SKIP_LINE.match(body) or "\"" in body and pattern.startswith(r"(?<![\w.])(\d"):
                continue
            new = _mutate_line(body, pattern, repl)
            if new is None:
                continue
            used_lines.add(i)
            mutated = lines[:i] + ["+" + new] + lines[i + 1:]
            out.append(Candidate(f"mutant-{len(out) + 1}", "mutant", f"{label} in: {body.strip()[:80]}",
                                 "".join(mutated)))
            break
    return out


def flawed_candidates(task: LoadedTask, *, max_partials: int = 6, max_mutants: int = 12,
                      repo: Path | None = None) -> list[Candidate]:
    c = [Candidate("noop", "noop", "no change: the start state", "")]
    c += partials(task.solution, max_partials)
    try:
        code_map = code_line_map(eval_grade.resolve_repo(task, repo), task.task.source.commit, task.solution)
    except eval_grade.GradeError:
        code_map = None
    c += mutants(task.solution, max_mutants, code_map)
    if task.task.grader.tests:
        c.append(Candidate("tamper-delete", "tamper", "no fix; deletes the hidden tests", "", tamper="delete"))
        c.append(Candidate("tamper-skip", "tamper", "no fix; rewrites the hidden tests to pass", "", tamper="skip"))
    return c


def _tamper(task: LoadedTask, how: str):
    def prepare(tree: Path) -> None:
        for rel in task.task.grader.tests:
            p = tree / rel
            if how == "delete":
                p.unlink(missing_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                stub = ("def test_ok():\n    assert True\n" if rel.endswith(".py")
                        else "// tests rewritten by a candidate\n")
                p.write_text(stub, encoding="utf-8")
    return prepare


# ------------------------------------------------------------------ run


async def validate(task: LoadedTask, *, repo: Path | None = None, unity_replay=None, rubric=None,
                   max_partials: int = 6, max_mutants: int = 12, write_report: bool = True) -> Report:
    ref = await eval_grade.grade_patch(task, task.solution, repo=repo, unity_replay=unity_replay, rubric=rubric)
    outcomes: list[Outcome] = []
    for cand in flawed_candidates(task, max_partials=max_partials, max_mutants=max_mutants, repo=repo):
        g = await eval_grade.grade_patch(task, cand.patch, repo=repo, unity_replay=unity_replay, rubric=rubric,
                                         prepare=_tamper(task, cand.tamper) if cand.tamper else None)
        outcomes.append(Outcome(cand.id, cand.kind, cand.description, g.passed, g.environment_failure, g.tampered,
                                [s.name for s in g.steps if not s.passed]))
    # A flawed candidate that only failed because the environment broke wasn't really caught.
    counted = [o for o in outcomes if not o.environment_failure]
    killed = [o for o in counted if not o.passed]
    rep = Report(task=task.task.id, validated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 reference_passed=ref.passed, flawed=len(counted), killed=len(killed),
                 kill_rate=round(len(killed) / len(counted), 3) if counted else 0.0,
                 survivors=[o for o in counted if o.passed], outcomes=outcomes,
                 reference_steps=[asdict(s) for s in ref.steps])
    if write_report:
        (task.dir / REPORT_FILE).write_text(json.dumps(rep.to_dict(), indent=1) + "\n", encoding="utf-8")
    return rep


def render_markdown(reports: list[Report]) -> str:
    lines = ["| Task | Reference | Flawed caught | Kill rate | Survivors |", "|---|---|---|---|---|"]
    for r in reports:
        lines.append(f"| {r.task} | {'pass' if r.reference_passed else '**FAIL**'} | {r.killed}/{r.flawed} | "
                     f"{r.kill_rate:.0%} | {'; '.join(o.description for o in r.survivors[:3]) or '-'} |")
    return "\n".join(lines)
