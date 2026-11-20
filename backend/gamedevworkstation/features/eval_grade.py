"""Eval Forge graders: run a task's checks against a candidate work tree.

A candidate is the task's start commit plus a change (the agent's work, the reference solution, or a flawed
variant). Grading lays the hidden test files over the tree first, so a candidate that edited or deleted them
is graded against the originals, and notes that it tried (`tampered`).

Graders, all optional, all must pass:
- command   the task's test command (exit 0)
- checks    named shell checks with an expected exit code
- differential  the same command per input in the reference tree and the candidate's; stdout must match
- unity     a Unity replay must verify with every frame hash matching, and text-asset asserts must hold
- rubric    a model judges the diff against rubric.md (effort gate; never the only grader in v0 tasks)

Every step records whether a failure looks like the environment's (command not found, timeout, setup failed)
rather than the candidate's: failure attribution reads that.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterator

from .eval_task import LoadedTask

# Credentials never reach task code (it runs the candidate's code).
_SECRET_ENV = re.compile(r"TOKEN|SECRET|PASSWORD|API_KEY|_KEY$|CREDENTIAL|AUTH", re.I)
TAIL = 4000


class GradeError(RuntimeError):
    pass


@dataclass
class Step:
    name: str
    kind: str                   # command | check | differential | unity | rubric | setup | apply
    passed: bool
    exit: int | None = None
    duration_s: float = 0.0
    output: str = ""            # the tail of stdout+stderr
    environment: bool = False   # the failure looks like the environment's, not the candidate's
    detail: dict = field(default_factory=dict)


@dataclass
class Grade:
    passed: bool
    steps: list[Step] = field(default_factory=list)
    tampered: list[str] = field(default_factory=list)

    @property
    def environment_failure(self) -> bool:
        return any(s.environment and not s.passed for s in self.steps)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "tampered": self.tampered, "environment_failure": self.environment_failure,
                "steps": [asdict(s) for s in self.steps]}


def task_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    # `python` in a task command is the interpreter running the grader (the one with the test tools).
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_shell(command: str, cwd: Path, timeout_s: float) -> tuple[int | None, str, float, bool]:
    """(exit code or None on timeout, output tail, seconds, timed_out)."""
    t0 = time.monotonic()
    shell = ["bash", "-c", command] if shutil.which("bash") else command
    try:
        r = subprocess.run(shell, cwd=cwd, shell=isinstance(shell, str), env=task_env(), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout_s, stdin=subprocess.DEVNULL)
        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        return r.returncode, out[-TAIL:], time.monotonic() - t0, False
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return None, out[-TAIL:], time.monotonic() - t0, True


def _env_failure(code: int | None, output: str, timed_out: bool) -> bool:
    """Exit 126/127 (can't run / not found) or a missing module/tool: the environment's fault. A test command that
    runs past its time limit is the candidate's: its code hung (the reference finished within the limit)."""
    if code in (126, 127):
        return True
    return bool(re.search(r"command not found|No module named pytest|ModuleNotFoundError: No module named '(pytest|"
                          r"vitest)'|ENOENT|Permission denied|No space left on device|Could not resolve host",
                          output))


# ------------------------------------------------------------------ trees


def _git(repo: Path, *args: str, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(repo), *args], input=input_text, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if check and r.returncode != 0:
        raise GradeError(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[:300]}")
    return r


def resolve_repo(task: LoadedTask, repo: Path | None = None) -> Path:
    """The local git repo holding the task's start commit: `repo` if given, else source.repo when it's a local
    folder, else the current directory (a suite checked into the repo it was forged from)."""
    if repo is not None:
        return Path(repo)
    src = Path(task.task.source.repo).expanduser()
    if src.is_dir():
        return src
    here = Path.cwd()
    r = subprocess.run(["git", "-C", str(here), "cat-file", "-e", f"{task.task.source.parent}^{{commit}}"],
                       capture_output=True, timeout=60)
    if r.returncode == 0:
        return here
    raise GradeError(f"can't find the start commit {task.task.source.parent[:12]} of {task.task.id}: pass --repo "
                     f"(a clone of {task.task.source.repo})")


@contextlib.contextmanager
def checkout(repo: Path, commit: str, *, parent_dir: Path | None = None) -> Iterator[Path]:
    """A throwaway detached worktree of `repo` at `commit`; removed afterwards."""
    base = Path(tempfile.mkdtemp(prefix="gdw-eval-", dir=parent_dir))
    tree = base / "tree"
    _git(Path(repo), "worktree", "add", "--detach", "--quiet", str(tree), commit)
    try:
        yield tree
    finally:
        _git(Path(repo), "worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(base, ignore_errors=True)
        _git(Path(repo), "worktree", "prune", check=False)


def apply_patch(tree: Path, patch: str) -> Step:
    """Apply a unified diff to the tree; a patch that doesn't apply is a failed candidate, not an error."""
    if not patch.strip():
        return Step("apply", "apply", True, detail={"empty": True})
    r = _git(tree, "apply", "--binary", "--whitespace=nowarn", "-", input_text=patch, check=False)
    return Step("apply", "apply", r.returncode == 0, exit=r.returncode, output=r.stderr[-TAIL:])


def tree_diff(tree: Path) -> str:
    """Everything the candidate changed in the tree (tracked and new files), as one diff."""
    _git(tree, "add", "-A", "--intent-to-add", check=False)
    return _git(tree, "diff", "--binary", check=False).stdout


# ------------------------------------------------------------------ Unity


def _unity_cli() -> str | None:
    for c in (shutil.which("unity"), str(Path.home() / ".unity/bin/unity")):
        if c and Path(c).is_file():
            return c
    return None


def unity_cli_replay(project: Path, replay: str, timeout: float) -> dict:
    """Replay `replay` in batch mode with the official Unity CLI and the com.gdw.replay verification test.

    The test fails on any divergent frame or unexpected console error; returns {"status", "message"}."""
    cli = _unity_cli()
    if cli is None:
        raise GradeError("the Unity CLI isn't installed")
    out = project / "Logs" / "harness" / "eval"
    out.mkdir(parents=True, exist_ok=True)
    run_id = "rr_eval" + os.urandom(6).hex()
    request = {"schema": "gdw.replay.request/1", "op": "verify", "run_id": run_id, "replay_path": replay,
               "fixed_dt": {"num": 1, "den": 60}}
    req = out / f"{run_id}.request.json"
    req.write_text(json.dumps(request), encoding="utf-8")
    xml = out / f"{run_id}.xml"
    r = subprocess.run([cli, "test", str(project), "--mode", "PlayMode", "--output", str(xml), "--timeout",
                        str(int(timeout)), "--filter", "Gdw.Replay.Tests.ReplayVerificationTests.LogMatchesCheckpoints",
                        "--format", "json", "--", "-gdwReplayRequest", str(req), "-logFile", str(xml.with_suffix(".log"))],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout + 300)
    try:
        text = xml.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise GradeError(f"the Unity test run wrote no results (exit {r.returncode}): {r.stdout[-300:]}")
    passed = re.search(r'<test-case [^>]*LogMatchesCheckpoints[^>]*result="Passed"', text) is not None
    msg = re.search(r"<message><!\[CDATA\[(.*?)\]\]></message>", text, re.S)
    return {"status": "pass" if passed else "diverged", "message": (msg.group(1).strip()[:500] if msg else "")}


# ------------------------------------------------------------------ graders

UnityReplay = Callable[[Path, str, float], dict]
Rubric = Callable[[str, str], Awaitable[dict]]


def overlay_tests(task: LoadedTask, tree: Path) -> list[str]:
    """Lay the hidden tests over the tree; returns the ones the candidate had changed or deleted."""
    tampered = []
    for rel in task.task.grader.tests:
        src, dst = task.grader_file(rel), tree / rel
        original = src.read_bytes()
        if dst.exists() and dst.read_bytes() != original or (not dst.exists() and _existed_at_start(task, rel)):
            tampered.append(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(original)
    return tampered


def _existed_at_start(task: LoadedTask, rel: str) -> bool:
    try:
        repo = resolve_repo(task)
    except GradeError:
        return False
    r = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{task.task.source.parent}:{rel}"],
                       capture_output=True, timeout=60)
    return r.returncode == 0


def _differential(task: LoadedTask, tree: Path, reference: Path, timeout: float) -> Step:
    d = task.task.grader.differential
    assert d is not None
    mismatches = []
    t0 = time.monotonic()
    for inp in d.inputs:
        cmd = d.command.replace("{input}", shlex.quote(inp))
        ref_code, ref_out, _, ref_to = run_shell(cmd, reference, timeout)
        if ref_code != 0:
            return Step("differential", "differential", False, ref_code, time.monotonic() - t0,
                        f"the reference failed on {inp!r}:\n{ref_out}", environment=True)
        code, out, _, to = run_shell(cmd, tree, timeout)
        if to:
            return Step("differential", "differential", False, None, time.monotonic() - t0, out, environment=True)
        if code != 0 or out.strip() != ref_out.strip():
            mismatches.append({"input": inp, "exit": code, "expected": ref_out[-500:], "got": out[-500:]})
    return Step("differential", "differential", not mismatches, 0 if not mismatches else 1, time.monotonic() - t0,
                "" if not mismatches else json.dumps(mismatches[:3], indent=1)[-TAIL:],
                detail={"inputs": len(d.inputs), "mismatches": len(mismatches)})


def _unity(task: LoadedTask, tree: Path, timeout: float, replay: UnityReplay | None) -> list[Step]:
    u = task.task.grader.unity
    assert u is not None
    steps = []
    for a in u.asserts:
        p = tree / a.path
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            steps.append(Step(f"asset {a.path}", "unity", False, output=f"{a.path} is missing"))
            continue
        missing = [s for s in a.contains if s not in text]
        present = [s for s in a.absent if s in text]
        steps.append(Step(f"asset {a.path}", "unity", not missing and not present,
                          output="" if not (missing or present) else
                          f"missing: {missing}  should be absent: {present}"))
    if u.replay:
        replay = replay or unity_cli_replay
        if replay is None:
            steps.append(Step("replay", "unity", False, output="no Unity to replay with", environment=True))
        else:
            t0 = time.monotonic()
            try:
                report = replay(tree / u.project if u.project else tree, u.replay, timeout)
            except Exception as e:  # noqa: BLE001 — Unity missing, licence, crash: the environment's
                steps.append(Step("replay", "unity", False, duration_s=time.monotonic() - t0, output=str(e)[-TAIL:],
                                  environment=True))
            else:
                frames = report.get("frames") or {}
                ok = (report.get("status") == "pass"
                      and (not frames or frames.get("expected") == frames.get("compared"))
                      and (report.get("console") or {}).get("errors", 0) == 0)
                steps.append(Step("replay", "unity", ok, duration_s=time.monotonic() - t0,
                                  output="" if ok else json.dumps({k: report.get(k) for k in (
                                      "status", "frames", "first_divergent_frame", "provider_id", "message")}),
                                  environment=report.get("status") in ("error", "incompatible"),
                                  detail={"frames": frames, "status": report.get("status")}))
    return steps


async def grade(task: LoadedTask, tree: Path, *, reference: Path | None = None, unity_replay: UnityReplay | None = None,
                rubric: Rubric | None = None) -> Grade:
    """Grade the candidate in `tree` (already holding its change). Mutates the tree (overlays the tests)."""
    g = task.task.grader
    diff = tree_diff(tree) if g.rubric else ""
    tampered = overlay_tests(task, tree)
    steps: list[Step] = []
    if g.command:
        code, out, dt, to = run_shell(g.command, tree, g.timeout_s)
        steps.append(Step("tests", "command", code == 0, code, dt, out, environment=code != 0 and _env_failure(code, out, to)))
    for c in g.checks:
        code, out, dt, to = run_shell(c.command, tree, g.timeout_s)
        steps.append(Step(c.name, "check", code == c.expect_exit, code, dt, out, environment=code in (126, 127)))
    if g.differential is not None:
        if reference is None:
            raise GradeError("differential grading needs the reference tree")
        steps.append(_differential(task, tree, reference, g.timeout_s))
    if g.unity is not None:
        steps += _unity(task, tree, g.timeout_s, unity_replay)
    if g.rubric:
        if rubric is None:
            steps.append(Step("rubric", "rubric", False, output="no model to judge the rubric with", environment=True))
        else:
            t0 = time.monotonic()
            verdict = await rubric(task.rubric, diff)
            steps.append(Step("rubric", "rubric", bool(verdict.get("pass")), duration_s=time.monotonic() - t0,
                              output=str(verdict.get("reasons") or "")[-TAIL:], detail=verdict))
    return Grade(passed=bool(steps) and all(s.passed for s in steps), steps=steps, tampered=tampered)


async def grade_patch(task: LoadedTask, patch: str, *, repo: Path | None = None, unity_replay: UnityReplay | None = None,
                      rubric: Rubric | None = None, prepare: Callable[[Path], None] | None = None) -> Grade:
    """Check out the task's start commit, apply `patch` (and `prepare`, e.g. a tampering edit), grade it."""
    src = resolve_repo(task, repo)
    with checkout(src, task.task.source.parent) as tree:
        if task.task.grader.setup:
            code, out, dt, to = run_shell(task.task.grader.setup, tree, task.task.grader.timeout_s)
            if code != 0:
                return Grade(False, [Step("setup", "setup", False, code, dt, out, environment=True)])
        applied = apply_patch(tree, patch)
        if not applied.passed:
            return Grade(False, [applied])
        if prepare is not None:
            prepare(tree)
        if task.task.grader.differential is not None:
            with checkout(src, task.task.source.parent) as ref:
                ref_applied = apply_patch(ref, task.solution)
                if not ref_applied.passed:
                    raise GradeError("the reference solution doesn't apply to its own start commit")
                return await grade(task, tree, reference=ref, unity_replay=unity_replay, rubric=rubric)
        return await grade(task, tree, unity_replay=unity_replay, rubric=rubric)
