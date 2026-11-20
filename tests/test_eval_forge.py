"""Eval Forge v0, part 1: the task format, `gdw eval forge` and the leak filter."""
from __future__ import annotations

from pathlib import Path

import pytest

from gamedevworkstation.features import eval_cli, eval_forge, eval_task

from .evalrepo import git as _git
from .evalrepo import make_repo


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path)


async def test_a_commit_becomes_a_task(repo, tmp_path):
    out = await eval_forge.forge(repo, "HEAD", tmp_path / "suite")
    t = eval_task.load(out)
    head, parent = _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "HEAD^")
    assert t.task.source.commit == head and t.task.source.parent == parent
    assert t.task.grader.tests == ["tests/__init__.py", "tests/test_scores.py"]
    assert t.task.grader.command == "python -m pytest -q tests/test_scores.py"
    assert t.grader_file("tests/test_scores.py").read_text(encoding="utf-8").startswith("from src.scores")
    # The reference solution is the source change only: the tests stay hidden in the grader.
    assert "src/scores.py" in t.solution and "test_scores" not in t.solution
    assert t.task.id.startswith("clamp-scores-to-the-board-s-range-") and out.name == t.task.id


async def test_the_prompt_doesnt_leak_the_solution(repo, tmp_path):
    t = eval_task.load(await eval_forge.forge(repo, "HEAD", tmp_path / "suite"))
    p = t.prompt
    assert "Scores could go negative after a penalty" in p  # the requirement stays
    assert "apply_penalty" in p  # it existed before the change, so it's fair to name
    assert "clamp_score" not in p and "[new name]" in p  # the solution's new function doesn't
    assert "```" not in p and "max(0" not in p  # nor its code
    assert "test_penalty_never_goes_negative" not in p and "tests/test_scores.py" not in p
    assert "Co-Authored-By" not in p
    assert "name: clamp_score" in t.task.forge.removed and "code block" in t.task.forge.removed


async def test_a_rewrite_is_filtered_too(repo, tmp_path):
    async def rewrite(text: str) -> str:
        assert "clamp_score" not in text  # the model never sees the leaked name either
        return "Make sure scores can't drop below zero. You could add clamp_score for it."

    t = eval_task.load(await eval_forge.forge(repo, "HEAD", tmp_path / "suite", rewrite=rewrite,
                                              rewritten_by="fake"))
    assert t.prompt.startswith("Make sure scores can't drop below zero. You could add [new name] for it.")
    assert t.task.forge.rewritten_by == "fake"


async def test_commits_without_tests_or_source_are_refused(repo, tmp_path):
    (repo / "README.md").write_text("docs\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Docs")
    with pytest.raises(eval_forge.ForgeError, match="no tests"):
        await eval_forge.forge(repo, "HEAD", tmp_path / "suite")
    (repo / "tests" / "test_more.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Only tests")
    with pytest.raises(eval_forge.ForgeError, match="only changes tests"):
        await eval_forge.forge(repo, "HEAD", tmp_path / "suite")


async def test_an_existing_task_isnt_overwritten(repo, tmp_path):
    await eval_forge.forge(repo, "HEAD", tmp_path / "suite", task_id="scores-task")
    with pytest.raises(eval_task.EvalTaskError, match="already holds a task"):
        await eval_forge.forge(repo, "HEAD", tmp_path / "suite", task_id="scores-task")


def test_test_paths():
    for p in ("tests/test_x.py", "pkg/tests/util.py", "test_y.py", "a/b_test.py", "src/x.test.tsx",
              "Assets/Tests/EditMode/DashTests.cs", "PlayerTests.cs"):
        assert eval_forge.is_test_path(p), p
    for p in ("src/scores.py", "Assets/Scripts/Dash.cs", "frontend/src/lib/api.ts", "testing.md"):
        assert not eval_forge.is_test_path(p), p


def test_the_leak_filter_on_its_own():
    text, removed = eval_forge.leak_filter(
        "Add MAX_SPEED and a SpeedLimiter in src/limit.py.\n@@ -1,2 +1,3 @@\n+x = 1\nKeep SpeedLimiterTests green.",
        names=["MAX_SPEED", "SpeedLimiter"], paths=["src/limit.py"], tests=["SpeedLimiterTests"])
    assert "SpeedLimiter" not in text and "MAX_SPEED" not in text and "src/limit.py" not in text
    assert "@@" not in text and text.count("[new name]") == 2 and "[hidden test]" in text
    assert "diff lines" in removed


# --------------------------------------------------------------- format


def _task(**over):
    base = {"schema": "gdw.eval.task/1", "id": "abc-task", "title": "t",
            "source": {"repo": "x", "commit": "a" * 40, "parent": "b" * 40},
            "grader": {"command": "true"}}
    base.update(over)
    return base


def test_the_schema_rejects_bad_tasks():
    eval_task.Task.model_validate(_task())
    for bad in (_task(id="Bad ID"), _task(grader={}), _task(grader={"command": "x", "tests": ["../escape.py"]}),
                _task(source={"repo": "x", "commit": "nothex", "parent": "b" * 40}), _task(extra=1)):
        with pytest.raises(ValueError):
            eval_task.Task.model_validate(bad)


async def test_load_names_every_problem(repo, tmp_path):
    out = await eval_forge.forge(repo, "HEAD", tmp_path / "suite")
    (out / "prompt.md").write_text("  \n", encoding="utf-8")
    (out / "grader/files/tests/test_scores.py").unlink()
    with pytest.raises(eval_task.EvalTaskError) as e:
        eval_task.load(out)
    assert "prompt.md is empty" in str(e.value) and "isn't in grader/files/" in str(e.value)


# --------------------------------------------------------------- CLI and route


def test_cli_forge_and_list(repo, tmp_path, capsys):
    suite = tmp_path / "suite"
    assert eval_cli.cli(["forge", "HEAD", "--repo", str(repo), "--out", str(suite), "--id", "scores-task"]) == 0
    assert '"task": "scores-task"' in capsys.readouterr().out
    assert eval_cli.cli(["list", "--suite", str(suite)]) == 0
    assert "ok  scores-task" in capsys.readouterr().out
    assert eval_cli.cli(["forge", "--repo", str(repo)]) == 2  # neither a commit nor --pr
    assert eval_cli.cli(["forge", "--pr", "12", "--repo", str(repo)]) == 2  # --pr without --github
    assert eval_cli.cli(["forge", "HEAD", "--repo", str(repo), "--out", str(suite), "--effort", "max",
                         "--rewrite"]) == 2  # above high needs approval: refused up front


async def test_route_lists_the_suite(repo, tmp_path):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    await eval_forge.forge(repo, "HEAD", tmp_path / "suite", task_id="scores-task")
    app, api = FastAPI(), APIRouter(prefix="/api")
    eval_cli.register(app, api, None)  # type: ignore[arg-type]
    app.include_router(api)
    r = TestClient(app).get("/api/evals/tasks", params={"suite": str(tmp_path / "suite")})
    assert r.status_code == 200 and r.json()["tasks"][0]["id"] == "scores-task"
    assert TestClient(app).get("/api/evals/tasks", params={"suite": str(tmp_path / "nope")}).status_code == 400


async def test_the_interface_the_hidden_tests_need_is_named(repo, tmp_path):
    t = eval_task.load(await eval_forge.forge(repo, "HEAD", tmp_path / "suite"))
    # apply_penalty gained a parameter the tests call; clamp_score is only used inside the solution.
    assert "Interface the tests use" in t.prompt and "  - `def apply_penalty(v, p, hi=100):`" in t.prompt
    assert "clamp_score" not in t.prompt and "return" not in t.prompt.split("Interface")[1]


def test_interface_takes_declarations_not_bodies():
    patch = ("+++ b/Assets/Dash.cs\n"
             "+public sealed class Dash\n+{\n+    public float Multiplier => IsDashing ? 3f : 1f;\n"
             "+    public bool TryStart(bool moving)\n+    {\n+        return moving;\n+    }\n"
             "+    private void Hidden() { }\n")
    tests = {"t.cs": b"var d = new Dash(); d.TryStart(moving: true); _ = d.Multiplier;"}
    assert [(n, d) for n, d, _ in eval_forge.interface(patch, tests)] == [
        ("Dash", "public sealed class Dash"), ("Multiplier", "public float Multiplier"),
        ("TryStart", "public bool TryStart(bool moving)")]


def test_new_files_the_tests_import_are_named_and_calls_are_not_declarations():
    # 2026-11-20: a forged task hid `release_feed.py` as "[new file]" while its hidden test imported it, and listed
    # `return Path(...)` / `raise HTTPException(...)` as declarations.
    patch = ("+++ b/backend/app/features/release_feed.py\n+API = 'x'\n+def asset_name(v):\n+    return Path(v)\n"
             "+    raise HTTPException(400, 'no')\n+++ b/backend/app/features/helper.py\n+def private_bit():\n")
    tests = {"tests/t.py": b"from app.features import release_feed as F\nF.asset_name('1'); F.API; Path; HTTPException"}
    new = ["backend/app/features/release_feed.py", "backend/app/features/helper.py"]
    used = eval_forge.files_tests_use(new, tests)
    api = eval_forge.interface(patch, tests)
    assert used == ["backend/app/features/release_feed.py"]
    assert [n for n, _, _ in api] == ["API", "asset_name"]  # short constants count; calls don't
    text = eval_forge.interface_text(api, used, new)
    assert text.splitlines()[1:] == ["- `backend/app/features/release_feed.py` (new file):", "  - `API`",
                                     "  - `def asset_name(v):`"]
    # prose in docs isn't a declaration ("record items in" is not a C# record)
    assert eval_forge.interface("+++ b/SKILL.md\n+record items in the log\n", {"t.py": b"items"}) == []
    js = "+++ b/a.ts\n+export const LIMIT = 3\n+export function run() {\n+  const seen = new Set()\n+}\n"
    assert [n for n, _, _ in eval_forge.interface(js, {"t.ts": b"LIMIT run seen"})] == ["LIMIT", "run"]
    # files the tests read by name (not only imports) count too
    assert eval_forge.files_tests_use(["skills/x/SKILL.md"], {"t.py": b"(ROOT / 'SKILL.md').read_text()"})
    # C# tests need the class, not the file it's in
    assert eval_forge.files_tests_use(["Assets/Scripts/Dash.cs"], {"T.cs": b"new Dash()"}) == []


async def test_a_title_alone_is_not_a_task(repo, tmp_path):
    with pytest.raises(eval_forge.ForgeError, match="only a title"):
        await eval_forge.forge(repo, "HEAD", tmp_path / "suite", text="Clamp scores")
    t = eval_task.load(await eval_forge.forge(repo, "HEAD", tmp_path / "suite2", text=(
        "Clamp scores\n\nScores could go negative after a penalty; keep every update within zero and the max.")))
    assert t.prompt.startswith("Clamp scores")
