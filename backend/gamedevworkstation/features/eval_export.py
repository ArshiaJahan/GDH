"""Export Eval Forge tasks as Harbor tasks (the format Terminal-Bench 2.0 tasks use), so other harnesses can run them.

Written against the Harbor docs (docs.harborframework.com, tasks/overview, configuration, verifier, solution;
read 2026-11-20):

    <task-id>/
      instruction.md          the prompt
      task.toml               schema_version 1.4: [task] name, [metadata], [verifier]/[agent] timeout_sec,
                              [environment] build_timeout_sec and workdir
      environment/Dockerfile  the start state: a snapshot of the repo at the start commit in /app
      environment/repo/       that snapshot (git archive), unless --clone-url makes the image clone it
      solution/solve.sh       the oracle: applies solution.patch in /app
      solution/solution.patch
      tests/test.sh           lays the hidden tests over /app, runs the task's command and checks, and writes
                              1 or 0 to /logs/verifier/reward.txt
      tests/files/...         the hidden tests

Only the command and check graders export: differential, Unity and rubric graders need GameDevWorkstation, so a
task that has them is exported with them left out and listed under [metadata] graders_not_exported.
"""
from __future__ import annotations

import io
import json
import shlex
import shutil
import subprocess
import tarfile
from pathlib import Path

import tomli_w

from .eval_task import LoadedTask

SCHEMA_VERSION = "1.4"
APP, TESTS, SOLUTION, REWARD = "/app", "/tests", "/solution", "/logs/verifier/reward.txt"


class ExportError(RuntimeError):
    pass


def _not_exported(task: LoadedTask) -> list[str]:
    g = task.task.grader
    return [name for name, present in (("differential", g.differential is not None), ("unity", g.unity is not None),
                                       ("rubric", g.rubric)) if present]


def test_sh(task: LoadedTask) -> str:
    g = task.task.grader
    lines = ["#!/bin/bash",
             "# Eval Forge verifier: hidden tests over the agent's work, then the task's command and checks.",
             "set -uo pipefail",
             f'APP="${{APP:-{APP}}}"; TESTS="${{TESTS:-{TESTS}}}"; REWARD="${{REWARD:-{REWARD}}}"',
             'mkdir -p "$(dirname "$REWARD")"',
             'fail() { echo "FAILED: $1"; echo 0 > "$REWARD"; exit 0; }',
             'cp -R "$TESTS/files/." "$APP/" || fail "could not lay the hidden tests over $APP"',
             'cd "$APP"']
    if g.command:
        lines.append(f"bash -c {shlex.quote(g.command)} || fail {shlex.quote('tests: ' + g.command)}")
    for c in g.checks:
        lines.append(f'bash -c {shlex.quote(c.command)}; code=$?; '
                     f'[ "$code" -eq {c.expect_exit} ] || fail {shlex.quote("check " + c.name)}')
    lines.append('echo 1 > "$REWARD"')
    return "\n".join(lines) + "\n"


def solve_sh() -> str:
    return ("#!/bin/bash\n# Oracle: the original commit's source change.\nset -euo pipefail\n"
            f'APP="${{APP:-{APP}}}"; SOLUTION="${{SOLUTION:-{SOLUTION}}}"\n'
            'cd "$APP"\n'
            '[ -s "$SOLUTION/solution.patch" ] && git apply --whitespace=nowarn "$SOLUTION/solution.patch"\n'
            "exit 0\n")


def dockerfile(task: LoadedTask, *, base_image: str, clone_url: str | None, docker_setup: str = "") -> str:
    g = task.task.grader
    out = [f"FROM {base_image}",
           "RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates "
           "&& rm -rf /var/lib/apt/lists/*"]
    if "pytest" in g.command:
        out.append("RUN pip install --no-cache-dir pytest")
    if clone_url:
        out += [f"RUN git clone {shlex.quote(clone_url)} {APP} && git -C {APP} checkout --detach "
                f"{task.task.source.parent}"]
    else:
        out += [f"COPY repo/ {APP}/"]
    out.append(f"WORKDIR {APP}")
    for cmd in (g.setup, docker_setup):  # the task's own setup, then image-only setup (dependencies)
        if cmd:
            out.append(f"RUN {cmd}")
    return "\n".join(out) + "\n"


def _snapshot(repo: Path, commit: str, dest: Path) -> int:
    """`git archive` of the start commit unpacked into dest; returns the file count."""
    r = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", commit], capture_output=True, timeout=600)
    if r.returncode != 0:
        raise ExportError(f"git archive {commit[:12]} failed: {r.stderr.decode('utf-8', 'replace')[:300]}")
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        for m in tf.getmembers():
            if m.name.startswith("/") or ".." in Path(m.name).parts or not (m.isfile() or m.isdir()):
                continue
            try:
                tf.extract(m, dest, filter="data")
            except TypeError:  # Python before 3.11.4: no extraction filters (paths were checked above)
                tf.extract(m, dest)
            n += m.isfile()
    return n


def export(task: LoadedTask, out_root: Path, *, repo: Path | None = None, base_image: str = "python:3.12-slim",
           clone_url: str | None = None, org: str = "gdh", docker_setup: str = "") -> Path:
    t = task.task
    d = Path(out_root) / t.id
    if d.exists():
        raise ExportError(f"{d} already exists")
    (d / "environment").mkdir(parents=True)
    (d / "solution").mkdir()
    (d / "tests" / "files").mkdir(parents=True)
    skipped = _not_exported(task)
    if not (t.grader.command or t.grader.checks):
        shutil.rmtree(d)
        raise ExportError(f"{t.id}: only {', '.join(skipped)} grading, which needs GameDevWorkstation; nothing to export")
    meta = {"source_repo": t.source.repo, "source_commit": t.source.commit, "start_commit": t.source.parent,
            "kind": t.kind, "forged_by": "GameDevWorkstation Eval Forge", "leak_filter_removed": t.forge.removed}
    validation = task.dir / "validation.json"
    if validation.is_file():
        v = json.loads(validation.read_text(encoding="utf-8"))
        meta["grader_validation"] = {"reference_passed": v.get("reference_passed"), "kill_rate": v.get("kill_rate"),
                                     "flawed": v.get("flawed"), "killed": v.get("killed")}
    if skipped:
        meta["graders_not_exported"] = skipped
    config = {"schema_version": SCHEMA_VERSION,
              "task": {"name": f"{org}/{t.id}", "description": t.title, "keywords": list(t.tags) or [t.kind]},
              "metadata": meta,
              "verifier": {"timeout_sec": float(t.grader.timeout_s)},
              "agent": {"timeout_sec": float(t.limits.agent_timeout_s)},
              "environment": {"build_timeout_sec": 1800.0, "workdir": APP}}
    (d / "task.toml").write_text(tomli_w.dumps(config), encoding="utf-8")
    (d / "instruction.md").write_text(task.prompt.rstrip() + f"\n\nThe project is in {APP}. Don't commit.\n",
                                      encoding="utf-8")
    (d / "environment" / "Dockerfile").write_text(dockerfile(task, base_image=base_image, clone_url=clone_url,
                                                             docker_setup=docker_setup),
                                                  encoding="utf-8")
    if not clone_url:
        from .eval_grade import resolve_repo

        _snapshot(resolve_repo(task, repo), t.source.parent, d / "environment" / "repo")
    (d / "solution" / "solve.sh").write_text(solve_sh(), encoding="utf-8")
    (d / "solution" / "solution.patch").write_text(task.solution, encoding="utf-8")
    (d / "tests" / "test.sh").write_text(test_sh(task), encoding="utf-8")
    for rel in t.grader.tests:
        dst = d / "tests" / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(task.grader_file(rel), dst)
    for sh in (d / "solution" / "solve.sh", d / "tests" / "test.sh"):
        sh.chmod(0o755)
    return d
