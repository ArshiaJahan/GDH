"""The checked-in Eval Forge seed suite (evals/suite) stays loadable, validated and leak-free."""
import json
import re
from pathlib import Path

from gamedevworkstation.features import eval_task

SUITE = Path(__file__).resolve().parents[1] / "evals" / "suite"
TASKS = eval_task.discover(SUITE)


def test_the_suite_has_gdh_and_unity_tasks():
    kinds = [eval_task.load(d).task.kind for d in TASKS]
    assert len(TASKS) >= 14 and kinds.count("unity") >= 2


def test_every_task_loads_and_was_validated():
    for d in TASKS:
        t = eval_task.load(d)
        v = json.loads((d / "validation.json").read_text(encoding="utf-8"))
        assert v["task"] == t.task.id and v["reference_passed"] is True, d.name
        assert v["flawed"] >= 5 and 0 <= v["kill_rate"] <= 1, d.name


def test_gdh_tasks_import_the_candidates_code():
    for d in TASKS:
        t = eval_task.load(d).task
        if t.kind == "code":
            assert t.grader.command.startswith("PYTHONPATH=backend python -m pytest"), d.name


def test_no_prompt_contains_a_name_the_leak_filter_removed():
    for d in TASKS:
        t = eval_task.load(d)
        for removed in t.task.forge.removed:
            kind, _, value = removed.partition(": ")
            if kind == "name":
                assert not re.search(rf"\b{re.escape(value)}\b", t.prompt), (d.name, value)
            elif kind in ("path", "test"):
                assert value not in t.prompt, (d.name, value)
