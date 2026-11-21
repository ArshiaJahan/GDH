"""Model router (Feature D, D6): auto selection, pins, escalation, spans, mixed-run stats, queued-unit caps."""
import asyncio
import json
import sqlite3
from contextlib import closing

import pytest

from gamedevworkstation.agent.tools import ToolContext, ToolOutput
from gamedevworkstation.app import AppState
from gamedevworkstation.config import data_dir
from gamedevworkstation.core.types import Usage
from gamedevworkstation.features import routing_policy, subagents
from gamedevworkstation.features.task_board import TaskBoard
from gamedevworkstation.features.usage_routes import UsageQueries
from gamedevworkstation.providers.base import ProviderError
from gamedevworkstation.providers.fake import FakeProvider, text_response, tool_response
from gamedevworkstation.usage import BudgetExceeded

HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
TERRA, SOL = "gpt-6.1-terra", "gpt-6.1-sol"


@pytest.fixture
async def app(cfg, tmp_path):
    cfg.tracing.update(enabled=True, sample_rate=1.0, otlp_endpoint="")
    cfg.limits.update(global_daily_usd=0, session_usd=0, task_usd=0)
    state = AppState(config=cfg, db_path=tmp_path / "ledger.db")
    state.claude, state.codex = FakeProvider("anthropic"), FakeProvider("openai")
    state.providers.override("anthropic", "default", state.claude)
    state.providers.override("openai", "default", state.codex)
    state.mgr = subagents.SubagentManager(state)
    state.extensions["subagents"] = state.mgr
    subagents._register_tools(state, state.mgr)
    # The Opus approval card needs a UI to answer it. Tests answer through this fake: state.opus_answers holds the
    # replies in order (default: approve) and state.opus_cards records every card asked.
    state.opus_cards, state.opus_answers = [], []

    async def ask(_session_id, kind, payload):
        assert kind == "opus_subagent", kind
        state.opus_cards.append(payload)
        return {"status": state.opus_answers.pop(0) if state.opus_answers else "approved"}

    state.approvals.ask = ask
    await state.tracing.astart()
    try:
        yield state
    finally:
        await state.tracing.aclose()
        state.db.close()


def _ctx(app):
    s = app.store.create(folder=None)
    return ToolContext(app=app, session=s, run_id=f"main:{s['id']}")


async def _run(app, ctx, **args):
    sub = await app.mgr.spawn(ctx, {"name": "u", "instructions": "Extract the names as JSON.", **args})
    await asyncio.wait_for(sub.task, 5)
    return sub


async def _spans(app):
    await app.tracing.aclose()
    with closing(sqlite3.connect(data_dir() / "traces.sqlite3")) as conn:
        conn.row_factory = sqlite3.Row
        return [{**row, "attrs": json.loads(row["attrs_json"])}
                for row in conn.execute("SELECT * FROM trace_spans ORDER BY start_ns")]


def test_auto_route_chooses_cheapest_eligible_model(cfg):
    pick = lambda **kw: routing_policy.select(cfg, **{"job_type": "extract", "effort": "low", "instructions": "brief", **kw})
    r = pick()
    assert (r.tier, r.model, r.reason, r.check, r.chain) == ("claude.fast", HAIKU, "cheapest", "json_object",
                                                            ("claude.standard",))
    # Listed strongest-first, the cheapest still wins and only stronger-than-it candidates are fallbacks.
    cfg.model_routing["rules"]["extract"]["candidates"] = ["claude.standard", "claude.fast"]
    assert pick().tier == "claude.fast"
    cfg.model_routing["rules"]["extract"]["candidates"] = ["claude.fast", "claude.standard"]
    # An unpriced candidate is skipped, an effort the model lacks makes it ineligible.
    cfg.models[HAIKU].input = cfg.models[HAIKU].output = 0.0
    assert pick().tier == "claude.standard"
    cfg.models[HAIKU].input, cfg.models[HAIKU].output = 0.10, 0.50
    cfg.models[HAIKU].efforts = ["low"]
    assert pick(effort="high").tier == "claude.standard"
    # Never across provider families: a codex request on a claude-only rule gets the codex standard tier.
    r = pick(provider="codex")
    assert (r.tier, r.reason, r.chain) == ("codex.standard", "standard", ())
    assert pick(job_type="mechanical_edit").tier == "codex.fast"
    assert pick(job_type="mechanical_edit", provider="claude").tier == "claude.standard"
    # Unknown job types and disabled routing take the conservative standard tier.
    assert (pick(job_type="refactor_everything").tier, pick(job_type="other").reason) == ("claude.standard", "standard")
    cfg.model_routing["enabled"] = False
    assert pick().reason == "routing_disabled" and pick().tier == "claude.standard"
    # An input too large for every candidate falls back conservatively too.
    cfg.model_routing["enabled"] = True
    big = routing_policy.select(cfg, job_type="extract", effort="low", instructions="x" * 8_000_000)
    assert big.reason == "standard" and big.tier == "claude.standard"


async def test_auto_unit_runs_on_selected_model_and_pins_stay_pinned(app, cfg):
    ctx = _ctx(app)
    app.claude.script = [text_response('{"a": 1}'), text_response("ok"), text_response("ok")]
    auto = await _run(app, ctx, tier="auto", job_type="extract")
    assert (auto.tier, auto.model, auto.status) == ("claude.fast", HAIKU, "done")
    deep = await _run(app, ctx, tier="claude.deep", job_type="extract")
    assert (deep.tier, deep.model, deep.route, deep.escalations) == ("claude.deep", OPUS, None, 0)
    assert [c["tier"] for c in app.opus_cards] == ["claude.deep"]  # only the pinned Opus unit asked
    disabled = None
    cfg.model_routing["enabled"] = False
    disabled = await _run(app, ctx, tier="auto", job_type="extract")
    assert disabled.model == SONNET and disabled.route.reason == "routing_disabled"
    assert [c.model for c in app.claude.calls] == [HAIKU, OPUS, SONNET]


async def test_explicit_tier_and_cli_stay_pinned(app, cfg, tmp_path, monkeypatch):
    ctx = _ctx(app)
    # An explicit tier ignores the rule for its job type, even with a non-json reply a rule would fail.
    app.codex.script = [text_response("not json")]
    sub = await _run(app, ctx, tier="codex.standard", job_type="extract")
    assert (sub.model, sub.route, sub.status, sub.attempts[0]["reason"]) == (SOL, None, "done", "pinned")
    assert [c.model for c in app.codex.calls] == [SOL]
    # codex.cli is never an automatic candidate, even when a rule lists it.
    cfg.model_routing["rules"]["mechanical_edit"]["candidates"] = ["codex.cli", "codex.fast"]
    r = routing_policy.select(cfg, job_type="mechanical_edit", effort="low", instructions="x")
    assert r.tier == "codex.fast" and "codex.cli" not in r.chain
    cfg.model_routing["rules"]["mechanical_edit"]["candidates"] = ["codex.cli"]
    assert routing_policy.select(cfg, job_type="mechanical_edit", effort="low", instructions="x").tier == "codex.standard"
    # The CLI tier itself runs the pinned route: no routing decision, one span with the codex_cli harness.
    session = app.store.create(folder=str(tmp_path))
    cli_ctx = ToolContext(app=app, session=session, run_id=f"main:{session['id']}")

    async def is_repo(_folder):
        return True

    async def create_worktree(_folder, _root, _sub_id):
        return tmp_path

    async def run_cli(self, sub):
        sub.result = "cli done"

    monkeypatch.setattr(subagents.shutil, "which", lambda _name: "/fake/codex")
    monkeypatch.setattr(app.approvals, "allowlisted", lambda *_args: True)
    monkeypatch.setattr(subagents.worktrees, "is_repo", is_repo)
    monkeypatch.setattr(subagents.worktrees, "create", create_worktree)
    monkeypatch.setattr(subagents.SubagentManager, "_run_codex_cli", run_cli)
    cli = await app.mgr.spawn(cli_ctx, {"name": "cli", "tier": "codex.cli", "job_type": "mechanical_edit",
                                       "instructions": "edit"})
    await asyncio.wait_for(cli.task, 5)
    assert (cli.tier, cli.route, cli.status, cli.result) == ("codex.cli", None, "done", "cli done")
    spans = [s for s in await _spans(app) if s["name"] == "invoke_agent"]
    cli_span, = [s for s in spans if s["run_id"] == cli.id]
    assert cli_span["attrs"]["gdw.harness"] == "codex_cli" and cli_span["attrs"]["gdw.outcome"] == "ok"
    assert cli_span["attrs"]["gdw.routing.reason"] == "pinned"


async def test_failed_check_escalates_without_replaying_tools(app):
    ran = []

    @app.tools.add("count_tool", "Count", {"type": "object", "properties": {}}, read_only=True)
    async def count_tool(_ctx, _args):
        ran.append(1)
        return ToolOutput("counted")

    ctx = _ctx(app)
    app.claude.script = [tool_response("count_tool", {}), text_response("not json"), text_response('{"ok": 1}')]
    sub = await _run(app, ctx, tier="auto", job_type="extract", tools=["count_tool"])
    assert sub.status == "done", sub.error
    assert sub.result == '{"ok": 1}' and len(ran) == 1  # the executed tool was not replayed
    assert [c.model for c in app.claude.calls] == [HAIKU, HAIKU, SONNET]
    last = app.claude.calls[2].messages
    assert [m.role for m in last] == ["user", "assistant", "user", "assistant", "user"]
    assert "json_object" in last[-1].text()  # the fixed repair instruction names the check
    assert (sub.model, sub.tier, sub.escalations) == (SONNET, "claude.standard", 1)
    assert [(a["model"], a["reason"]) for a in sub.attempts] == [(HAIKU, "cheapest"), (SONNET, "failed_check")]
    rows = app.db.all("SELECT model, ok FROM usage_records WHERE run_id=? AND role='subagent' ORDER BY id", [sub.id])
    assert [(r["model"], r["ok"]) for r in rows] == [(HAIKU, 1), (HAIKU, 1), (SONNET, 1)]  # one record per attempt
    assert app.db.one("SELECT mixed_models FROM delegation_stats WHERE job_id=?", [sub.job_id])["mixed_models"] == 1
    span, = [s for s in await _spans(app) if s["name"] == "invoke_agent"]
    a = span["attrs"]
    assert (a["gdw.routing.escalation"], a["gdw.routing.selected_tier"], a["gdw.routing.reason"]) == (
        1, "claude.standard", "failed_check")
    assert (a["gdw.routing.policy_revision"], a["gdw.routing.job_type"], a["gdw.outcome"]) == ("1", "extract", "ok")

    # Still failing after the allowed escalation: the unit fails with the check's name.
    app.claude.script, app.claude.calls = [text_response("nope"), text_response("still nope")], []
    bad = await _run(app, ctx, tier="auto", job_type="extract")
    assert bad.status == "failed" and "json_object" in bad.error and len(app.claude.calls) == 2


async def test_transient_error_escalates_and_auth_does_not(app):
    def boom(_req):
        raise ProviderError("overloaded", status=503)

    ctx = _ctx(app)
    app.claude.script = [boom, text_response('{"x": 1}')]
    sub = await _run(app, ctx, tier="auto", job_type="extract")
    assert (sub.status, sub.model) == ("done", SONNET)
    assert [r["ok"] for r in app.db.all("SELECT ok FROM usage_records WHERE run_id=? ORDER BY id", [sub.id])] == [0, 1]

    def denied(_req):
        raise ProviderError("bad key", status=401, auth=True)

    app.claude.script = [denied, text_response('{"x": 1}')]
    sub = await _run(app, ctx, tier="auto", job_type="extract")
    assert sub.status == "failed" and sub.model == HAIKU and sub.escalations == 0


async def test_fallback_rechecks_effort_and_run_cap(app, cfg, monkeypatch):
    seen = []
    real = subagents.check_effort
    monkeypatch.setattr(subagents, "check_effort", lambda *a, **k: (seen.append(a[2]), real(*a, **k))[1])
    ctx = _ctx(app)

    def boom(_req):
        raise ProviderError("overloaded", status=503)

    app.claude.script = [boom, text_response('{"x": 1}')]
    sub = await _run(app, ctx, tier="auto", job_type="extract", effort="medium")
    assert sub.status == "done" and seen == [sub.id] * 3  # accept, first dispatch, fallback dispatch

    # The run cap is checked again before the fallback dispatch: no second model call is made.
    cfg.delegation["subagent_spend_cap_usd"] = 0.01
    app.claude.script = [text_response("not json", usage=Usage(input_tokens=10, output_tokens=5, cost_usd=0.02)),
                         text_response('{"x": 1}')]
    app.claude.calls = []
    capped = await _run(app, ctx, tier="auto", job_type="extract")
    assert capped.status == "failed" and capped.error.startswith("BudgetExceeded")
    assert len(app.claude.calls) == 1 and capped.escalations == 1


async def test_resumed_and_cancelled_units_close_distinct_spans(app):
    ctx = _ctx(app)
    app.claude.script = [text_response('{"a": 1}'), text_response('{"b": 2}')]
    first = await _run(app, ctx, tier="auto", job_type="extract")
    out = await app.tools.run(ctx, "message_subagent", {"id": first.id, "message": "once more"})
    assert not out.is_error
    await asyncio.wait_for(first.task, 5)

    # Cancelled before its first step (callback path) and while waiting for a slot (finally path).
    app.mgr.pools["api"] = asyncio.Semaphore(1)
    async with app.mgr.pools["api"]:
        early = await app.mgr.spawn(ctx, {"name": "e", "tier": "auto", "job_type": "extract", "instructions": "x"})
        assert await app.mgr.stop(early.id)
        late = await app.mgr.spawn(ctx, {"name": "l", "tier": "auto", "job_type": "extract", "instructions": "x"})
        await asyncio.sleep(0)
        assert late.status == "queued" and await app.mgr.stop(late.id)
        await asyncio.gather(early.task, late.task, return_exceptions=True)
        await asyncio.sleep(0)
    assert early.done_event.is_set() and late.done_event.is_set()

    spans = [s for s in await _spans(app) if s["name"] == "invoke_agent"]
    by_run = {rid: [s for s in spans if s["run_id"] == rid] for rid in (first.id, early.id, late.id)}
    assert [len(v) for v in by_run.values()] == [2, 1, 1] and len(spans) == 4
    assert len({s["span_id"] for s in spans}) == 4
    assert len({s["attrs"]["gdw.job.id"] for s in by_run[first.id]}) == 2  # follow-up job, own span
    assert [s["attrs"]["gdw.outcome"] for s in by_run[first.id]] == ["ok", "ok"]
    assert by_run[early.id][0]["attrs"]["gdw.outcome"] == by_run[late.id][0]["attrs"]["gdw.outcome"] == "cancelled"
    assert all(s["category"] == "subagent" and s["end_ns"] >= s["start_ns"] for s in spans)


async def test_mixed_route_excluded_from_single_model_stats(app):
    ctx = _ctx(app)
    app.claude.script = [text_response("nope"), text_response('{"a": 1}'), text_response("fine")]
    mixed = await _run(app, ctx, tier="auto", job_type="extract")
    single = await _run(app, ctx, tier="claude.fast", job_type="extract")
    assert mixed.status == single.status == "done"
    flags = {r["job_id"]: r["mixed_models"] for r in app.db.all("SELECT job_id, mixed_models FROM delegation_stats")}
    assert flags == {mixed.job_id: 1, single.job_id: 0}
    rows = {m["model"]: m for m in UsageQueries(app).comparison({})}
    assert rows[HAIKU]["tasks"] == 1 and rows[HAIKU]["successes"] == 1
    assert HAIKU in rows and rows[HAIKU]["by_job_type"]["extract"]["count"] == 1
    assert rows[SONNET]["tasks"] == 0 and rows[SONNET]["requests"] == 1  # its spend still shows in the ledger totals
    out = await app.tools.run(ctx, "get_delegation_stats", {})
    assert "n=1" in out.text and "n=2" not in out.text


async def test_queued_unit_rechecks_task_cap_at_launch(app, cfg):
    session = app.store.create()
    sid = session["id"]
    ctx = ToolContext(app=app, session=session, run_id=f"main:{sid}")
    board = TaskBoard(app)
    first, second = board.create(title="First task"), board.create(title="Second task")
    board.link(first["id"], sid)
    cfg.limits["task_usd"] = 5
    app.mgr.pools["api"] = asyncio.Semaphore(1)
    async with app.mgr.pools["api"]:
        unit = await app.mgr.spawn(ctx, {"name": "q", "tier": "auto", "job_type": "extract", "instructions": "x"})
        await asyncio.sleep(0)
        assert unit.status == "queued"
        assert unit.usage_scope.task_id == first["id"]  # the snapshot taken when it was queued
        app.usage.record(provider="anthropic", model=HAIKU, usage=Usage(cost_usd=5), session_id=sid, role="main")
        board.unlink(first["id"], sid)
        board.link(second["id"], sid)  # relinking must not let it escape the first task's cap
    await asyncio.wait_for(unit.task, 2)
    assert unit.status == "failed"
    assert unit.error == (f"BudgetExceeded: {first['code']} has reached its $5.00 spend limit. "
                          "Raise `limits.task_usd` to continue.")
    assert not app.claude.calls and not app.db.all("SELECT 1 FROM usage_records WHERE role='subagent'")
    with pytest.raises(BudgetExceeded):
        app.usage.check(sid, scope=unit.usage_scope)


def _opus_chain(cfg):
    """An extract rule whose escalation target is Opus (the shipped rules never reach it)."""
    cfg.model_routing["rules"]["extract"]["candidates"] = ["claude.fast", "claude.deep"]


async def test_auto_selection_of_opus_asks_and_decline_stops_the_spawn(app, cfg):
    cfg.model_routing["rules"]["extract"]["candidates"] = ["claude.deep"]
    for tier in ("claude.fast", "claude.standard"):  # make Opus the cheapest eligible: undercut the others
        cfg.models[cfg.resolve(tier)].input = cfg.models[cfg.resolve(tier)].output = 99.0
    cfg.models[OPUS].input = cfg.models[OPUS].output = 0.01
    app.opus_answers = ["denied"]
    ctx = _ctx(app)
    assert routing_policy.select(cfg, job_type="extract", effort="low", instructions="x").model == OPUS
    with pytest.raises(PermissionError, match="declined an Opus subagent"):
        await app.mgr.spawn(ctx, {"name": "u", "tier": "auto", "job_type": "extract", "instructions": "x"})
    assert [c["model"] for c in app.opus_cards] == [OPUS] and not app.claude.calls and not app.mgr.subs
    app.claude.script = [text_response('{"a": 1}')]
    sub = await _run(app, ctx, tier="auto", job_type="extract")  # approved this time
    assert (sub.status, sub.model) == ("done", OPUS) and len(app.opus_cards) == 2
    assert set(app.opus_cards[0]) == {"subject", "name", "tier", "model", "effort", "instructions"}


async def test_escalation_onto_opus_asks_and_proceeds_when_approved(app, cfg):
    _opus_chain(cfg)
    app.claude.script = [text_response("nope"), text_response('{"ok": 1}')]
    sub = await _run(app, _ctx(app), tier="auto", job_type="extract")
    assert (sub.status, sub.model, sub.escalations) == ("done", OPUS, 1), sub.error
    card, = app.opus_cards
    assert (card["tier"], card["model"], card["name"]) == ("claude.deep", OPUS, "u")
    assert card["subject"] == "Opus subagent: u" and card["instructions"] == "Extract the names as JSON."
    assert [c.model for c in app.claude.calls] == [HAIKU, OPUS]


async def test_declined_opus_escalation_stops_the_unit_with_a_clear_error(app, cfg):
    _opus_chain(cfg)
    app.opus_answers = ["denied"]
    app.claude.script = [text_response("nope"), text_response('{"ok": 1}')]
    sub = await _run(app, _ctx(app), tier="auto", job_type="extract")
    assert sub.status == "failed" and "declined the Opus escalation" in sub.error
    assert "claude.fast to claude.deep" in sub.error and "failed_check" in sub.error
    assert (sub.model, sub.escalations, sub.result) == (HAIKU, 0, "nope")  # never moved; last reply kept
    assert [c.model for c in app.claude.calls] == [HAIKU]
    # A transient provider failure is the same path: a decline stops it instead of switching silently.
    def boom(_req):
        raise ProviderError("overloaded", status=503)

    app.opus_answers, app.claude.script, app.claude.calls = ["denied"], [boom, text_response('{"x": 1}')], []
    sub = await _run(app, _ctx(app), tier="auto", job_type="extract")
    assert sub.status == "failed" and "declined the Opus escalation" in sub.error and sub.model == HAIKU
    assert len(app.claude.calls) == 1


async def test_allowlisted_opus_escalation_skips_the_ask(app, cfg):
    _opus_chain(cfg)
    cfg.modes["allowlist"] = ["opus_subagent:claude.deep"]
    app.claude.script = [text_response("nope"), text_response('{"ok": 1}')]
    sub = await _run(app, _ctx(app), tier="auto", job_type="extract")
    assert (sub.status, sub.model) == ("done", OPUS) and not app.opus_cards


async def test_pending_opus_escalation_card_does_not_hold_the_pool_slot(app, cfg):
    _opus_chain(cfg)
    cfg.delegation["max_parallel"]["claude_codex"] = 1
    gate = asyncio.Event()

    async def ask(_session_id, kind, payload):
        app.opus_cards.append(payload)
        await gate.wait()
        return {"status": "approved"}

    app.approvals.ask = ask
    app.claude.script = [text_response("nope"), text_response("second"), text_response('{"ok": 1}')]
    ctx = _ctx(app)
    a = await app.mgr.spawn(ctx, {"name": "a", "instructions": "x", "tier": "auto", "job_type": "extract"})
    for _ in range(100):
        if app.opus_cards:
            break
        await asyncio.sleep(0.01)
    assert app.opus_cards and app.mgr.pools["api"].running == 0  # slot released while the card is pending
    b = await app.mgr.spawn(ctx, {"name": "b", "instructions": "y", "tier": "claude.fast"})
    await asyncio.wait_for(b.task, 5)
    assert b.status == "done" and a.status in ("queued", "running")
    gate.set()
    await asyncio.wait_for(a.task, 5)
    assert a.status == "done" and a.model == OPUS and app.mgr.pools["api"].running == 0


async def test_subagent_error_stop_reason_records_one_failed_row(app):
    app.claude.script = [text_response("").model_copy(update={"stop_reason": "error"})]
    sub = await _run(app, _ctx(app), tier="claude.fast")
    rows = app.db.all("SELECT ok, error_kind FROM usage_records WHERE role='subagent' AND run_id=?", [sub.id])
    assert [(r["ok"], r["error_kind"]) for r in rows] == [(0, "other")]
