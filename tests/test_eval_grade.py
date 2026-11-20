"""Eval Forge v0, part 2: graders and grader validation, on a real throwaway git repo."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gamedevworkstation.features import eval_cli, eval_forge, eval_grade, eval_task, eval_validate

from .evalrepo import make_repo


@pytest.fixture
async def task(tmp_path):
    repo = make_repo(tmp_path)
    return eval_task.load(await eval_forge.forge(repo, "HEAD", tmp_path / "suite", task_id="scores-task"))


async def test_the_reference_passes_and_the_start_state_fails(task):
    ref = await eval_grade.grade_patch(task, task.solution)
    assert ref.passed, ref.to_dict()
    start = await eval_grade.grade_patch(task, "")
    assert not start.passed and not start.environment_failure
    assert [s.name for s in start.steps if not s.passed] == ["tests"]


async def test_a_patch_that_doesnt_apply_fails_cleanly(task):
    g = await eval_grade.grade_patch(task, "diff --git a/nope.py b/nope.py\n--- a/nope.py\n+++ b/nope.py\n@@ -1 +1 @@\n-x\n+y\n")
    assert not g.passed and g.steps[0].kind == "apply"


async def test_edited_tests_are_put_back_and_reported(task):
    def tamper(tree: Path) -> None:
        (tree / "tests").mkdir(exist_ok=True)
        (tree / "tests" / "test_scores.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    g = await eval_grade.grade_patch(task, "", prepare=tamper)
    assert not g.passed and g.tampered == ["tests/test_scores.py"]


async def test_checks_and_environment_failures(task, tmp_path):
    t = task.task.model_copy(deep=True)
    t.grader.checks = [eval_task.Check(name="has clamp", command="grep -q clamp src/scores.py"),
                       eval_task.Check(name="tool missing", command="definitely-not-a-real-tool-xyz")]
    lt = task.model_copy(update={"task": t})
    g = await eval_grade.grade_patch(lt, lt.solution)
    by = {s.name: s for s in g.steps}
    assert by["tests"].passed and by["has clamp"].passed
    assert not by["tool missing"].passed and by["tool missing"].environment and g.environment_failure


async def test_differential_grading_compares_with_the_reference(task):
    t = task.task.model_copy(deep=True)
    t.grader.command = ""
    t.grader.differential = eval_task.Differential(
        command="python -c 'import sys; from src.scores import apply_penalty; print(apply_penalty(*map(int, sys.argv[1].split(\",\"))))' {input}",
        inputs=["3,10", "50,10", "150,10"])
    lt = task.model_copy(update={"task": t})
    assert (await eval_grade.grade_patch(lt, lt.solution)).passed
    start = await eval_grade.grade_patch(lt, "")
    assert not start.passed and start.steps[0].detail["mismatches"] == 2  # 3-10=-7 and 150-10=140 differ


async def test_unity_grader_with_a_recorded_replay_and_asset_asserts(task):
    t = task.task.model_copy(deep=True)
    t.kind, t.grader.command = "unity", ""
    t.grader.unity = eval_task.UnityGrader(replay="Logs/run.gdwreplay", asserts=[
        eval_task.AssetAssert(path="src/scores.py", contains=["def clamp_score"], absent=["TODO"])])
    lt = task.model_copy(update={"task": t})
    seen = []

    def replay_pass(project, replay, timeout):
        seen.append(replay)
        return {"status": "pass", "frames": {"expected": 1968, "compared": 1968}, "console": {"errors": 0}}

    def replay_diverged(project, replay, timeout):
        return {"status": "diverged", "frames": {"expected": 1968, "compared": 17}, "first_divergent_frame": 17}

    assert (await eval_grade.grade_patch(lt, lt.solution, unity_replay=replay_pass)).passed
    assert seen == ["Logs/run.gdwreplay"]
    g = await eval_grade.grade_patch(lt, lt.solution, unity_replay=replay_diverged)
    assert not g.passed and not g.environment_failure
    g = await eval_grade.grade_patch(lt, "", unity_replay=replay_pass)
    assert not g.passed  # the asset assert fails at the start state


async def test_rubric_grader_uses_the_judge(task):
    t = task.task.model_copy(deep=True)
    t.grader.rubric = True
    lt = task.model_copy(update={"task": t, "rubric": "- negative scores are clamped to zero"})
    got = {}

    async def judge(rubric, diff):
        got["rubric"], got["diff"] = rubric, diff
        return {"pass": "clamp" in diff, "score": 1, "reasons": "ok"}

    assert (await eval_grade.grade_patch(lt, lt.solution, rubric=judge)).passed
    assert "negative scores" in got["rubric"] and "def clamp_score" in got["diff"]
    g = await eval_grade.grade_patch(lt, lt.solution)  # no judge configured
    assert not g.passed and g.environment_failure


# --------------------------------------------------------------- validation


async def test_validation_kills_flawed_solutions(task):
    rep = await eval_validate.validate(task)
    assert rep.reference_passed and rep.ok
    kinds = {o.kind for o in rep.outcomes}
    assert {"noop", "mutant", "tamper"} <= kinds
    assert all(not o.passed for o in rep.outcomes if o.kind in ("noop", "tamper"))
    # The two survivors are equivalent mutants: at v == 0 and v == hi both branches return the same value, so
    # no test can tell them apart. The report says so instead of hiding them.
    assert sorted(o.description for o in rep.survivors) == ["< to <= in: if v < 0:", "> to >= in: if v > hi:"]
    assert rep.killed == rep.flawed - 2 and rep.kill_rate >= 0.7
    saved = json.loads((task.dir / eval_validate.REPORT_FILE).read_text(encoding="utf-8"))
    assert saved["task"] == "scores-task" and saved["kill_rate"] == rep.kill_rate


async def test_a_weak_grader_shows_up_as_survivors(task):
    t = task.task.model_copy(deep=True)
    t.grader.command = "python -m pytest -q tests/test_scores.py -k inside_the_range"  # only checks 50-10
    lt = task.model_copy(update={"task": t})
    rep = await eval_validate.validate(lt, write_report=False)
    assert rep.reference_passed
    assert any(o.kind == "noop" for o in rep.survivors)  # the start state already passes that test
    assert rep.kill_rate < 0.7


def test_mutants_change_one_added_line_each():
    patch = ("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,4 @@\n"
             " def f(v):\n-    return v\n+    if v < 0:\n+        return 0\n+    return v + 1\n")
    ms = eval_validate.mutants(patch, 20)
    assert len(ms) >= 3
    for m in ms:
        changed = [(a, b) for a, b in zip(patch.splitlines(), m.patch.splitlines()) if a != b]
        assert len(changed) == 1 and changed[0][0].startswith("+")
    labels = " ".join(m.description for m in ms)
    assert "< to <=" in labels and "constant +1" in labels


def test_partials_leave_out_one_hunk():
    patch = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+A\n@@ -9 +9 @@\n-b\n+B\n"
             "diff --git a/c.py b/c.py\n--- a/c.py\n+++ b/c.py\n@@ -1 +1 @@\n-c\n+C\n")
    ps = eval_validate.partials(patch, 10)
    assert len(ps) == 3
    assert "+A" not in ps[0].patch and "+B" in ps[0].patch and "+C" in ps[0].patch
    assert "c.py" not in eval_validate.partials(patch, 10)[2].patch


# --------------------------------------------------------------- CLI


async def test_cli_grade_and_validate(task, tmp_path, capsys):
    good, bad = tmp_path / "good.patch", tmp_path / "bad.patch"
    good.write_text(task.solution, encoding="utf-8")
    bad.write_text("", encoding="utf-8")
    import asyncio

    def run(argv):  # the CLI runs its own event loop
        return asyncio.get_running_loop().run_in_executor(None, eval_cli.cli, argv)

    assert await run(["grade", str(task.dir), "--patch", str(good)]) == 0
    assert await run(["grade", str(task.dir), "--patch", str(bad)]) == 1
    assert await run(["validate", str(task.dir), "--markdown", "--mutants", "3"]) == 0
    out = capsys.readouterr().out
    assert "| scores-task | pass |" in out
