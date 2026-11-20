"""Eval Forge v0, part 3: agent runs, pass@k and failure attribution (scripted agents, no model calls)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gamedevworkstation.features import eval_attribute, eval_cli, eval_forge, eval_grade, eval_run, eval_task, eval_validate
from gamedevworkstation.features.eval_task import Limits

from .evalrepo import SOLVED, make_repo


@pytest.fixture
async def task(tmp_path):
    repo = make_repo(tmp_path)
    t = eval_task.load(await eval_forge.forge(repo, "HEAD", tmp_path / "suite", task_id="scores-task"))
    await eval_validate.validate(t, max_mutants=2)  # writes validation.json, which attribution reads
    return t


def test_pass_at_k_is_the_unbiased_estimator():
    assert eval_run.pass_at_k(5, 0, 1) == 0.0
    assert eval_run.pass_at_k(5, 5, 3) == 1.0
    assert eval_run.pass_at_k(5, 2, 1) == pytest.approx(0.4)
    assert eval_run.pass_at_k(5, 2, 3) == pytest.approx(1 - 1 / 10)  # 1 - C(3,3)/C(5,3)
    assert eval_run.pass_at_k(3, 1, 5) == 1.0  # k is capped at n


# --------------------------------------------------------------- scripted agents


async def solver(prompt: str, tree: Path, limits: Limits) -> eval_run.AgentResult:
    assert "clamp_score" not in prompt and not (tree / "tests" / "test_scores.py").exists()  # hidden from it
    (tree / "src" / "scores.py").write_text(SOLVED, encoding="utf-8")
    return eval_run.AgentResult(cost_usd=0.01, tool_calls=3, input_tokens=100, output_tokens=50, log="solved")


async def idler(prompt, tree, limits):
    return eval_run.AgentResult(cost_usd=0.002, tool_calls=1, log="nothing to do")


async def tamperer(prompt, tree, limits):
    (tree / "tests").mkdir(exist_ok=True)
    (tree / "tests" / "test_scores.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return eval_run.AgentResult(tool_calls=1)


async def logged_out(prompt, tree, limits):
    return eval_run.AgentResult(error="Invalid API key · Please run /login")


async def slowpoke(prompt, tree, limits):
    return eval_run.AgentResult(timed_out=True)


async def test_a_suite_run_scores_and_attributes(task, tmp_path):
    out = tmp_path / "run"
    agents = {"solver": solver, "idler": idler, "tamperer": tamperer, "logged_out": logged_out, "slowpoke": slowpoke}
    results = await eval_run.run_suite([task], agents, 2, out)
    by = {r.agent: [x for x in results if x.agent == r.agent] for r in results}
    assert all(r.passed and r.blame == "" for r in by["solver"])
    assert all(not r.passed and r.blame == "agent" for r in by["idler"])
    assert all(r.blame == "agent" and r.tampered == ["tests/test_scores.py"] and "hidden tests" in r.reason
               for r in by["tamperer"])
    assert all(r.blame == "environment" for r in by["logged_out"])
    assert all(r.blame == "agent" and "time limit" in r.reason for r in by["slowpoke"])
    summary = {s["agent"]: s for s in eval_run.summarize(results, 2)}
    assert summary["solver"]["pass@1"] == 1.0 and summary["idler"]["pass@2"] == 0.0
    assert summary["solver"]["mean_cost_usd"] == 0.01 and summary["solver"]["mean_tool_calls"] == 3
    assert summary["logged_out"]["blame"] == {"agent": 0, "environment": 2, "grader": 0}
    # raw evidence for every trial
    saved = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert len(saved["trials"]) == 10 and saved["summary"]
    t1 = out / "scores-task" / "solver"
    assert (t1 / "trial-1.log").read_text(encoding="utf-8") == "solved"
    assert "def clamp_score" in (t1 / "trial-1.diff").read_text(encoding="utf-8")
    md = eval_run.render_markdown(results, 2)
    assert "| solver | 1 | 100% | 100% | $0.010 |" in md


async def test_an_unvalidated_task_blames_the_grader(task, tmp_path):
    (task.dir / eval_validate.REPORT_FILE).unlink()
    (r,) = await eval_run.run_suite([task], {"idler": idler}, 1, tmp_path / "run")
    assert r.blame == "grader" and "never validated" in r.reason


# --------------------------------------------------------------- attribution rules


def _grade(*steps, tampered=()):
    return eval_grade.Grade(all(s.passed for s in steps), list(steps), list(tampered))


VALID = {"reference_passed": True, "kill_rate": 0.9}


def test_environment_failures_are_not_the_agents():
    g = _grade(eval_grade.Step("tests", "command", False, 127, output="bash: pytest: command not found",
                               environment=True))
    assert eval_attribute.attribute(g, validation=VALID).blame == "environment"
    g = _grade(eval_grade.Step("tests", "command", False, 1,
                               output="npm ERR! code ETIMEDOUT\nnpm ERR! network request to https://registry.npmjs.org failed"))
    a = eval_attribute.attribute(g, validation=VALID)
    assert a.blame == "environment" and "CI triage" in a.reason


def test_grader_blame():
    failing = _grade(eval_grade.Step("tests", "command", False, 1, output="AssertionError"))
    assert eval_attribute.attribute(failing, validation={"reference_passed": False}).blame == "grader"
    only_rubric = _grade(eval_grade.Step("tests", "command", True, 0),
                         eval_grade.Step("rubric", "rubric", False))
    assert eval_attribute.attribute(only_rubric, validation=VALID).blame == "grader"


def test_agent_blame_and_passes():
    failing = _grade(eval_grade.Step("tests", "command", False, 1, output="assert -7 == 0\nAssertionError"))
    assert eval_attribute.attribute(failing, validation=VALID).blame == "agent"
    passing = _grade(eval_grade.Step("tests", "command", True, 0))
    assert eval_attribute.attribute(passing, validation=VALID).blame == ""
    assert eval_attribute.attribute(None, agent_error="segfault", validation=VALID).blame == "environment"


# --------------------------------------------------------------- CLI log parsers


def test_claude_stream_json_is_counted():
    lines = [{"type": "system", "subtype": "init"},
             {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"},
                                                           {"type": "tool_use", "name": "Edit", "input": {}}]}},
             {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
             {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0421,
              "usage": {"input_tokens": 10, "cache_read_input_tokens": 1000, "output_tokens": 300}}]
    r = eval_run.parse_claude_stream("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    assert (r.tool_calls, r.cost_usd, r.input_tokens, r.output_tokens, r.error) == (2, 0.0421, 1010, 300, "")
    err = eval_run.parse_claude_stream(json.dumps({"type": "result", "is_error": True, "result": "Not logged in"}))
    assert err.error == "Not logged in"


def test_codex_jsonl_is_counted():
    lines = [{"type": "thread.started"}, {"type": "item.completed", "item": {"type": "command_execution"}},
             {"type": "item.completed", "item": {"type": "file_change"}},
             {"type": "item.completed", "item": {"type": "agent_message"}},
             {"type": "turn.completed", "usage": {"input_tokens": 500, "output_tokens": 70}}]
    r = eval_run.parse_codex_jsonl("\n".join(json.dumps(x) for x in lines))
    assert (r.tool_calls, r.input_tokens, r.output_tokens, r.cost_usd) == (2, 500, 70, None)


async def test_missing_clis_are_environment_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_run.shutil, "which", lambda name: None)
    r = await eval_run.codex_agent()("x", tmp_path, Limits())
    assert "isn't installed" in r.error
    assert eval_attribute.attribute(None, agent_error=r.error).blame == "environment"


async def test_builtin_that_cant_start_reports_why(tmp_path):
    class App:
        extensions = {}

        class store:
            @staticmethod
            def create(**kw):
                return {"id": "s1", "folder": kw["folder"], "mode": kw["mode"], "settings": {}}

    class Mgr:
        async def spawn(self, ctx, a):
            assert a["tools"] == eval_run.FILE_TOOLS and "run_command" not in a["tools"]
            raise ValueError("This job has spent $5.00, at its job_budget_usd")

    App.extensions["subagents"] = Mgr()
    r = await eval_run.builtin_agent(App())("x", tmp_path, Limits())  # type: ignore[arg-type]
    assert "job_budget_usd" in r.error


def test_cli_rejects_unknown_agents(tmp_path):
    assert eval_cli.cli(["run", "--agents", "gpt9", "--suite", str(tmp_path)]) == 2
    assert eval_cli.cli(["run", "--agents", "codex", "--suite", str(tmp_path / "empty")]) == 2
