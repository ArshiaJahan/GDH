"""`gdw eval compare-routing` (Feature D, D7): preview without models, paired arms, spend threshold, rubric accounting.
Fake providers only: no paid or live call, no network."""
from __future__ import annotations

import json

import pytest

from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Usage
from gamedevworkstation.features import eval_cli, eval_forge, eval_run, eval_task, eval_validate, subagents
from gamedevworkstation.providers.base import ProviderError
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response

from .evalrepo import SOLVED, make_repo

HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
ARGS = ["compare-routing", "--baseline-tier", "claude.standard", "--job-type", "extract", "--trials", "2",
        "--max-spend-usd", "5"]


def _cost(c: float) -> Usage:
    return Usage(input_tokens=10, output_tokens=5, cost_usd=c)


@pytest.fixture
def suite(tmp_path):
    import asyncio

    repo = make_repo(tmp_path)

    async def build():
        t = eval_task.load(await eval_forge.forge(repo, "HEAD", tmp_path / "suite", task_id="scores-task"))
        await eval_validate.validate(t, max_mutants=2)  # attribution reads validation.json

    asyncio.run(build())
    return tmp_path / "suite"


@pytest.fixture
def app(cfg, tmp_path):
    cfg.tracing.update(enabled=False)
    cfg.limits.update(global_daily_usd=0, session_usd=0, task_usd=0)
    # These suites route as "extract" but their units fix files, so this test's own tool policy lets extract
    # units write; the default policy keeps extract read-only.
    from gamedevworkstation.config import data_dir
    (data_dir() / "tool_policy.toml").write_text(
        'version = 1\n[agents.subagent.job_types.extract]\n'
        'allow = ["read_file", "list_dir", "search", "write_file", "edit_file", "delete_file"]\n', encoding="utf-8")
    state = AppState(config=cfg, db_path=tmp_path / "ledger.db")
    state.claude, state.codex = FakeProvider("anthropic"), FakeProvider("openai")
    state.providers.override("anthropic", "default", state.claude)
    state.providers.override("openai", "default", state.codex)
    state.mgr = subagents.SubagentManager(state)
    state.extensions["subagents"] = state.mgr
    subagents._register_tools(state, state.mgr)
    yield state
    state.db.close()


def _fix(c: float, reply: str):
    """One unit that fixes the task: write the solution, then answer with `reply`."""
    return [tool_response("write_file", {"path": "src/scores.py", "content": SOLVED}), text_response(reply, usage=_cost(c))]


def test_compare_routing_preview_never_starts_models(suite, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("the preview must not start anything")

    monkeypatch.setattr(eval_cli, "_cli_state", boom)  # AppState is what builds providers and clients
    for name in ("builtin_agent", "run_trial", "compare_routing", "run_suite"):
        monkeypatch.setattr(eval_run, name, boom)
    monkeypatch.setattr(eval_cli.eval_grade, "grade", boom)
    monkeypatch.setattr(eval_cli.eval_grade, "run_shell", boom)
    monkeypatch.setattr(subagents.SubagentManager, "spawn", boom)
    # A Unity task and a rubric task are listed as exclusions.
    import shutil

    base = (suite / "scores-task" / "task.toml").read_text(encoding="utf-8")
    unity = base.replace('id = "scores-task"', 'id = "unity-one"').replace('kind = "code"', 'kind = "unity"')
    unity = unity.replace("[limits]", '[grader.unity]\nreplay = "a.gdwreplay"\n\n[limits]')
    rubric = base.replace('id = "scores-task"', 'id = "rubric-one"').replace("rubric = false", "rubric = true")
    for tid, text in (("unity-one", unity), ("rubric-one", rubric)):
        shutil.copytree(suite / "scores-task", suite / tid)
        (suite / tid / "task.toml").write_text(text, encoding="utf-8")
        (suite / tid / "rubric.md").write_text("- clamps\n", encoding="utf-8")
    code = eval_cli.cli([ARGS[0], "--suite", str(suite), *ARGS[1:]])
    out = capsys.readouterr().out
    assert code == 0
    assert "PREVIEW" in out and "claude.standard -> claude-sonnet-5-5" in out
    assert "scores-task: pinned claude-sonnet-5-5; routed claude.fast -> claude-haiku-5-5" in out
    assert "arm runs: 4" in out and "spend ceiling:   $5.00" in out
    assert "needs Unity replay" in out and "needs a paid rubric grader" in out
    assert "Nothing was run" in out

    # A policy that picks the baseline for every task reports no selection change.
    code = eval_cli.cli(["compare-routing", "--suite", str(suite), "--baseline-tier", "claude.fast",
                         "--job-type", "extract", "--trials", "1", "--max-spend-usd", "1"])
    assert code == 0 and "no selection change" in capsys.readouterr().out
    # Bad requests exit 2 before anything else.
    assert eval_cli.cli(["compare-routing", "--suite", str(suite), "--baseline-tier", "nope", "--job-type", "extract",
                         "--trials", "1", "--max-spend-usd", "1"]) == 2


def test_compare_routing_pairs_trials_and_counts_fallback_cost(suite, app, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(eval_cli, "_cli_state", lambda: app)
    out = tmp_path / "report"
    # Trial 1 (pinned first): pinned Sonnet; routed Haiku answers a non-JSON reply, fails the json check, and falls
    # back to Sonnet. Trial 2 (routed first): both answer JSON the first time.
    app.claude.script = [
        *_fix(0.02, '{"ok": 1}'),
        tool_response("write_file", {"path": "src/scores.py", "content": SOLVED}),
        text_response("all done", usage=_cost(0.001)),
        text_response('{"ok": 1}', usage=_cost(0.03)),
        *_fix(0.001, '{"ok": 1}'),
        *_fix(0.02, '{"ok": 1}')]
    code = eval_cli.cli([*ARGS, "--suite", str(suite), "--approve-paid", "--out", str(out)])
    assert code == 0, capsys.readouterr()
    rep = json.loads((out / "compare-routing.json").read_text(encoding="utf-8"))
    p1, p2 = rep["pairs"]
    assert (p1["order"], p2["order"]) == (["pinned", "routed"], ["routed", "pinned"])
    assert [c.model for c in app.claude.calls] == [SONNET] * 2 + [HAIKU] * 2 + [SONNET] + [HAIKU] * 2 + [SONNET] * 2
    assert p1["pinned"]["passed"] and p1["routed"]["passed"] and p2["routed"]["passed"] and p2["pinned"]["passed"]
    assert p1["routed"]["fallbacks"] == 1 and p2["routed"]["fallbacks"] == 0
    assert [a["model"] for a in p1["routed"]["attempts"]] == [HAIKU, SONNET]
    assert p1["routed"]["ledger_models"] == [HAIKU, SONNET] and p1["pinned"]["ledger_models"] == [SONNET]
    # Spend comes from the ledger and keeps the fallback's cost: Haiku's two calls, then Sonnet's.
    assert p1["routed"]["spend_usd"] == pytest.approx(0.0001 + 0.001 + 0.03)
    assert p1["pinned"]["spend_usd"] == pytest.approx(0.0001 + 0.02)
    assert rep["arms"]["routed"]["fallbacks"] == 1 and rep["arms"]["pinned"]["fallbacks"] == 0
    assert rep["arms"]["routed"]["requests"] == 5 and rep["arms"]["routed"]["failed_requests"] == 0
    assert rep["paired"]["pairs"] == 2 and rep["paired"]["pinned_pass_rate"] == rep["paired"]["routed_pass_rate"] == 1.0
    assert rep["arms"]["pinned"]["pass@1"] == 1.0 and rep["arms"]["routed"]["pass@2"] == 1.0
    assert rep["policy_revisions"] == ["1"] and rep["selection_changed_trials"] == 2
    # Equal pass rates: a savings line is made (here the fallback made the routed arm dearer on trial 1).
    assert rep["savings"].startswith("Same pass rate (2/2 both arms)") or rep["savings"].startswith("Savings at the same")
    assert "small sample" in " ".join(rep["notes"])
    md = (out / "compare-routing.md").read_text(encoding="utf-8")
    assert "pass@1" in md and "Fallbacks" in md and rep["savings"] in md
    shown = capsys.readouterr().out
    assert "Routing comparison" in shown and str(out) in shown
    assert (out / "scores-task" / "routed" / "trial-1.json").exists()


def test_compare_routing_reports_no_savings_claim_when_pass_rates_differ(suite, app, tmp_path):
    import asyncio

    tasks = [eval_task.load(suite / "scores-task")]
    app.claude.script = [*_fix(0.02, '{"ok": 1}'), text_response('{"ok": 1}', usage=_cost(0.001))]  # routed: no fix
    rep = asyncio.run(eval_run.compare_routing(app, tasks, baseline_tier="claude.standard", job_type="extract",
                                               effort="low", trials=1, max_spend_usd=5, out_dir=tmp_path / "r"))
    assert rep["paired"]["pinned_pass_rate"] == 1.0 and rep["paired"]["routed_pass_rate"] == 0.0
    assert rep["savings"].startswith("Pass rates differ") and "no savings" in rep["savings"]


def test_compare_routing_stops_at_approved_spend_threshold(suite, app, tmp_path):
    import asyncio

    tasks = [eval_task.load(suite / "scores-task")]
    app.claude.script = [text_response('{"a": 1}', usage=_cost(0.05)) for _ in range(6)]
    rep = asyncio.run(eval_run.compare_routing(app, tasks, baseline_tier="claude.standard", job_type="extract",
                                               effort="low", trials=3, max_spend_usd=0.08, out_dir=tmp_path / "r"))
    # Pinned spends 0.05; 0.03 is left, so routed is admitted with that run cap and its one request overruns it.
    assert len(app.claude.calls) == 2 and [c.model for c in app.claude.calls] == [SONNET, HAIKU]
    assert rep["stopped_at_spend_threshold"] and rep["complete_pairs"] == 1 and rep["planned_pairs"] == 3
    assert len(rep["pairs"]) == 2 and rep["pairs"][1]["pinned"] is None  # trial 2 was never admitted
    assert rep["recorded_spend_usd"] == pytest.approx(0.10)
    assert any("stopped at the spend threshold" in n for n in rep["notes"])
    md = (tmp_path / "r" / "compare-routing.md").read_text(encoding="utf-8")
    assert "may overrun" in md
    # The routed unit's own run cap was the smaller of its task cap and the remaining allowance.
    assert rep["pairs"][0]["routed"]["spend_usd"] == pytest.approx(0.05)


def test_run_cap_is_the_smallest_of_task_allowance_and_active_cap(app, cfg):
    mgr = app.mgr
    cfg.delegation["subagent_spend_cap_usd"] = 0
    unit = subagents.Subagent(id="s", session_id="x", name="n", provider="anthropic", tier="claude.fast", model=HAIKU,
                              effort="low", instructions="i", tools=[], run_cap=0.5)
    assert mgr._cap(unit) == 0.5 and mgr._cap() is None
    cfg.delegation["subagent_spend_cap_usd"] = 0.2
    assert mgr._cap(unit) == 0.2
    cfg.delegation["subagent_spend_cap_usd"] = 3
    assert mgr._cap(unit) == 0.5


async def test_eval_rubric_records_failed_attempt_once(app):
    judge = eval_cli.make_rubric(app, model=SONNET)

    def broken(_req):
        raise ProviderError("overloaded", status=503)

    app.claude.script = [broken]
    with pytest.raises(ProviderError):
        await judge("- clamps", "diff")
    rows = app.db.all("SELECT ok, error_kind, feature, role FROM usage_records")
    assert len(rows) == 1 and rows[0]["ok"] == 0 and rows[0]["feature"] == "eval_rubric" and rows[0]["error_kind"]
    # A reply flagged as an error is one failed row too, and a good reply one successful row.
    errored = text_response("", usage=_cost(0.01)).model_copy(update={"stop_reason": "error"})
    app.claude.script = [errored, text_response('{"pass": true}', usage=_cost(0.01))]
    assert (await judge("- clamps", "diff"))["pass"] is False
    assert (await judge("- clamps", "diff"))["pass"] is True
    assert [r["ok"] for r in app.db.all("SELECT ok FROM usage_records ORDER BY id")] == [0, 0, 1]
