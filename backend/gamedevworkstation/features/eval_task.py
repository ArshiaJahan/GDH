"""Eval Forge task format (gdw.eval.task/1): one directory per task.

    <task-id>/
      task.toml        what the task is, where it starts, how it's graded (schema below)
      prompt.md        what the agent is told (the PR/commit text with the solution filtered out)
      solution.patch   the reference solution: the source change of the original commit, tests excluded
      grader/files/    the original commit's tests; laid over the agent's work at grading time, so the agent
                       never sees them and can't edit them into passing
      rubric.md        optional: criteria for the LLM rubric grader

The agent starts from `source.parent` (the commit before the change). Pure: no app imports.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Literal

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA = "gdw.eval.task/1"
TASK_FILE, PROMPT_FILE, SOLUTION_FILE, RUBRIC_FILE = "task.toml", "prompt.md", "solution.patch", "rubric.md"
GRADER_DIR = "grader/files"
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


class EvalTaskError(ValueError):
    pass


def _rel(p: str, field: str) -> str:
    """A path inside the task's repo: relative, POSIX, no '..'."""
    pp = PurePosixPath(p)
    if not p or pp.is_absolute() or ".." in pp.parts or "\\" in p or p.startswith("~"):
        raise ValueError(f"{field} must be a relative path inside the repo, got {p!r}")
    return str(pp)


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_M):
    repo: str = Field(description="where the task came from: a local path or an OWNER/NAME slug")
    commit: str
    parent: str
    pr: int | None = None
    title: str = ""

    @field_validator("commit", "parent")
    @classmethod
    def _sha(cls, v: str) -> str:
        if not _SHA.match(v):
            raise ValueError(f"must be a hex commit id, got {v!r}")
        return v


class Check(_M):
    name: str
    command: str
    expect_exit: int = 0


class Differential(_M):
    """Grade by comparing outputs: `command` runs once per input in the reference tree and in the candidate's;
    the stdout must match. {input} in the command is replaced by the input (shell-quoted)."""
    command: str
    inputs: list[str] = Field(min_length=1)


class UnityGrader(_M):
    """Unity tasks: a replay of `replay` (project-relative .gdwreplay) must verify with every frame hash matching,
    and each `assert` must hold on the project's text assets (scene/prefab YAML)."""
    replay: str = ""
    asserts: list["AssetAssert"] = Field(default_factory=list)

    @field_validator("replay")
    @classmethod
    def _replay(cls, v: str) -> str:
        return _rel(v, "unity.replay") if v else v


class AssetAssert(_M):
    path: str
    contains: list[str] = Field(default_factory=list)
    absent: list[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def _p(cls, v: str) -> str:
        return _rel(v, "assert.path")


class Grader(_M):
    command: str = Field("", description="the test command, run from the repo root after the grader files are laid over")
    tests: list[str] = Field(default_factory=list, description="files under grader/files, laid over the work tree")
    checks: list[Check] = Field(default_factory=list)
    differential: Differential | None = None
    unity: UnityGrader | None = None
    rubric: bool = False
    setup: str = Field("", description="run once in a fresh tree before the agent starts (install, build)")
    timeout_s: int = Field(900, ge=10, le=4 * 3600)

    @field_validator("tests")
    @classmethod
    def _tests(cls, v: list[str]) -> list[str]:
        return [_rel(p, "grader.tests") for p in v]

    @model_validator(mode="after")
    def _something(self) -> "Grader":
        if not (self.command or self.checks or self.differential or self.unity or self.rubric):
            raise ValueError("a grader needs at least one of command, checks, differential, unity or rubric")
        return self


class Limits(_M):
    agent_timeout_s: int = Field(1800, ge=60, le=24 * 3600)
    max_cost_usd: float = Field(2.0, gt=0, le=100)


class Forge(_M):
    """How the task was made: which names and paths the leak filter took out of the prompt, and whether a model
    rewrote it."""
    removed: list[str] = Field(default_factory=list)
    rewritten_by: str = ""
    forged_at: str = ""


class Task(_M):
    schema_: Literal["gdw.eval.task/1"] = Field(SCHEMA, alias="schema")
    id: str
    title: str
    kind: Literal["code", "unity"] = "code"
    tags: list[str] = Field(default_factory=list)
    source: Source
    grader: Grader
    limits: Limits = Field(default_factory=Limits)
    forge: Forge = Field(default_factory=Forge)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError(f"id must match {_ID.pattern}, got {v!r}")
        return v


UnityGrader.model_rebuild()


class LoadedTask(BaseModel):
    task: Task
    dir: Path
    prompt: str
    solution: str
    rubric: str = ""

    def grader_file(self, rel: str) -> Path:
        return self.dir / GRADER_DIR / rel


def load(task_dir: Path | str) -> LoadedTask:
    """Read and check one task directory; raises EvalTaskError with every problem found."""
    d = Path(task_dir)
    problems: list[str] = []
    try:
        data = tomllib.loads((d / TASK_FILE).read_text(encoding="utf-8"))
    except OSError as e:
        raise EvalTaskError(f"{d.name}: can't read {TASK_FILE}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise EvalTaskError(f"{d.name}: {TASK_FILE} isn't valid TOML: {e}") from e
    try:
        task = Task.model_validate(data)
    except ValueError as e:
        raise EvalTaskError(f"{d.name}: {e}") from e
    if task.id != d.name:
        problems.append(f"id {task.id!r} doesn't match the directory name {d.name!r}")
    texts: dict[str, str] = {}
    for name in (PROMPT_FILE, SOLUTION_FILE) + ((RUBRIC_FILE,) if task.grader.rubric else ()):
        try:
            texts[name] = (d / name).read_text(encoding="utf-8")
        except OSError:
            problems.append(f"missing {name}")
    if PROMPT_FILE in texts and not texts[PROMPT_FILE].strip():
        problems.append(f"{PROMPT_FILE} is empty")
    for rel in task.grader.tests:
        if not (d / GRADER_DIR / rel).is_file():
            problems.append(f"grader test {rel} isn't in {GRADER_DIR}/")
    if task.kind == "unity" and task.grader.unity is None:
        problems.append("a unity task needs a [grader.unity] section")
    if problems:
        raise EvalTaskError(f"{d.name}: " + "; ".join(problems))
    return LoadedTask(task=task, dir=d, prompt=texts[PROMPT_FILE], solution=texts[SOLUTION_FILE],
                      rubric=texts.get(RUBRIC_FILE, ""))


def write(task: Task, task_dir: Path, *, prompt: str, solution: str, grader_files: dict[str, bytes],
          rubric: str = "") -> Path:
    """Write a task directory (creating it); returns the directory. Refuses to overwrite an existing task."""
    d = Path(task_dir)
    if (d / TASK_FILE).exists():
        raise EvalTaskError(f"{d} already holds a task")
    (d / GRADER_DIR).mkdir(parents=True, exist_ok=True)
    data = task.model_dump(by_alias=True, exclude_none=True)
    (d / TASK_FILE).write_text(tomli_w.dumps(data), encoding="utf-8")
    (d / PROMPT_FILE).write_text(prompt.rstrip() + "\n", encoding="utf-8")
    (d / SOLUTION_FILE).write_text(solution, encoding="utf-8")
    if rubric:
        (d / RUBRIC_FILE).write_text(rubric, encoding="utf-8")
    for rel, data_bytes in grader_files.items():
        p = d / GRADER_DIR / _rel(rel, "grader file")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data_bytes)
    load(d)  # what we wrote must read back
    return d


def discover(root: Path | str) -> list[Path]:
    """Task directories directly under `root` (each holds a task.toml), sorted by name."""
    r = Path(root)
    return sorted(p for p in r.iterdir() if (p / TASK_FILE).is_file()) if r.is_dir() else []
