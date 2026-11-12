import asyncio
import json
import subprocess
import time

import pytest

from workspace.agent.tools import ToolContext
from workspace.app import AppState
from workspace.core.effort import APPROVALS
from workspace.core.types import ChatRequest, Response, TextBlock, ToolResultBlock, ToolUseBlock, Usage, new_id
from workspace.features.subagents import SubagentManager, _register_tools
from workspace.providers.fake import FakeProvider, text_response


class SmartFake(FakeProvider):
    """Subagent stand-in: a code unit writes the file named in its brief, then reports."""

    def __init__(self, name, delay=0.3):
        super().__init__(name, delay=delay)
        self.windows: list[tuple[float, float]] = []

    async def complete(self, req: ChatRequest) -> Response:
        t0 = time.monotonic()
        r = await super().complete(req)
        self.windows.append((t0, time.monotonic()))
        return r

    def _next(self, req: ChatRequest) -> Response:
        last = req.messages[-1]
        brief = req.messages[0].text()
        if any(isinstance(b, ToolResultBlock) for b in last.content) or "WRITE:" not in brief:
            return Response(id=new_id(), provider=self.name, model=req.model, content=[TextBlock(text=f"done: {brief[:30]}")],
                            usage=Usage(input_tokens=100, output_tokens=20, cost_usd=0.001))
        path = brief.split("WRITE:")[1].split()[0]
        return Response(id=new_id(), provider=self.name, model=req.model, stop_reason="tool_use",
                        content=[ToolUseBlock(id=new_id("toolu_"), name="write_file", input={"path": path, "content": "x = 1\n"})],
                        usage=Usage(input_tokens=100, output_tokens=20, cost_usd=0.001))


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    (d / "README.md").write_text("hi\n")
    for c in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
              ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=d, check=True)
    return d


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "d.db")
    a.claude, a.codex = SmartFake("anthropic"), SmartFake("openai")
    a.providers.override("anthropic", "default", a.claude)
    a.providers.override("openai", "default", a.codex)
    mgr = SubagentManager(a)
    a.extensions["subagents"] = mgr
    _register_tools(a, mgr)
    return a


def ctx_for(app, folder, mode="accept_edits"):
    s = app.store.create(folder=str(folder), mode=mode)
    return ToolContext(app=app, session=s, run_id=f"main:{s['id']}")


async def test_three_units_parallel_routed_worktrees_and_stats(app, repo):
    ctx = ctx_for(app, repo)
    units = [
        {"name": "extract-contacts", "provider": "claude", "tier": "claude.fast", "effort": "low", "job_type": "extract",
         "instructions": "Extract names as JSON."},
        {"name": "rename-a", "provider": "codex", "tier": "codex.fast", "effort": "low", "job_type": "mechanical_edit",
         "worktree": True, "tools": ["read_file", "write_file"], "instructions": "WRITE: a.py then report"},
        {"name": "rename-b", "provider": "codex", "tier": "codex.fast", "effort": "low", "job_type": "mechanical_edit",
         "worktree": True, "tools": ["read_file", "write_file"], "instructions": "WRITE: b.py then report"},
    ]
    t0 = time.monotonic()
    outs = await asyncio.gather(*(app.tools.run(ctx, "spawn_subagent", u) for u in units))
    assert all(not o.is_error for o in outs), [o.text for o in outs]
    ids = [o.text.split(" as ")[1].split()[0] for o in outs]
    res = await app.tools.run(ctx, "get_subagent_result", {"ids": ids})
    assert res.text.count("done:") == 3
    # Parallel: total wall time well under the sum of the subagents' call times.
    serial = sum(e - s for s, e in app.claude.windows + app.codex.windows)
    assert time.monotonic() - t0 < serial * 0.75
    # Routed per the table: extraction on claude.fast (Haiku), mechanical edits on codex.fast (GPT-6.1 Terra).
    assert {c.model for c in app.claude.calls} == {"claude-haiku-5-5"}
    assert {c.model for c in app.codex.calls} == {"gpt-6.1-terra"}
    assert all(c.effort == "low" for c in app.claude.calls + app.codex.calls)
    # Separate worktrees for the code units, none for the extraction unit.
    mgr = app.extensions["subagents"]
    wts = [mgr.subs[i].worktree for i in ids]
    assert wts[0] is None and wts[1] != wts[2]
    assert (wts[1] / "a.py").exists() and not (wts[1] / "b.py").exists() and (wts[2] / "b.py").exists()
    assert not (repo / "a.py").exists()  # untouched until merged
    # Orchestrator merges.
    for i in ids[1:]:
        m = await app.tools.run(ctx, "merge_worktree", {"id": i})
        assert not m.is_error, m.text
    assert (repo / "a.py").exists() and (repo / "b.py").exists()
    rows = app.db.all("SELECT * FROM delegation_stats ORDER BY job_type")
    assert len(rows) == 3
    assert {(r["job_type"], r["tier"], r["effort"], r["success"]) for r in rows} == {
        ("extract", "claude.fast", "low", 1), ("mechanical_edit", "codex.fast", "low", 1)}
    assert all(r["cost_usd"] > 0 and r["wall_time_s"] > 0 for r in rows)
    stats = await app.tools.run(ctx, "get_delegation_stats", {})
    assert "mechanical_edit: codex.fast @ low — n=2, success 100%" in stats.text


async def test_above_high_subagent_needs_approval_token(app, repo):
    ctx = ctx_for(app, repo)
    out = await app.tools.run(ctx, "spawn_subagent", {"name": "deep", "tier": "claude.deep", "effort": "max",
                                                      "instructions": "prove it"})
    assert out.is_error and "approval" in out.text and not app.claude.calls
    # Approval card → token → launch works, and the token is bound to that one unit.
    task = asyncio.create_task(app.tools.run(ctx, "request_effort_approval", {
        "subagent_plan": "deep proof on claude.deep", "effort": "max", "reason": "high failed twice", "est_cost": 0.4}))
    for _ in range(100):
        pend = app.approvals.pending(ctx.session_id)
        if pend:
            break
        await asyncio.sleep(0.01)
    assert pend[0]["kind"] == "effort" and pend[0]["payload"]["est_extra_cost_usd"] == 0.4
    app.approvals.resolve(pend[0]["id"], "approve")
    tok = json.loads((await task).text)["approval_token"]
    ok = await app.tools.run(ctx, "spawn_subagent", {"name": "deep", "tier": "claude.deep", "effort": "max",
                                                     "instructions": "prove it", "approval_token": tok,
                                                     "run_in_background": False})
    assert not ok.is_error and app.claude.calls[-1].effort == "max"
    again = await app.tools.run(ctx, "spawn_subagent", {"name": "deep2", "tier": "claude.deep", "effort": "max",
                                                        "instructions": "x", "approval_token": tok})
    assert again.is_error
    row = app.db.one("SELECT approval_requested FROM delegation_stats WHERE unit='deep'")
    assert row["approval_requested"] == 1


async def test_subagent_cannot_spawn_and_tools_are_scoped(app, repo):
    ctx = ctx_for(app, repo)
    sub_ctx = ToolContext(app=app, session=ctx.session, run_id="sub_x", role="subagent")
    out = await app.tools.run(sub_ctx, "spawn_subagent", {"name": "n", "tier": "claude.fast", "instructions": "x"})
    assert out.is_error  # one level deep
    out = await app.tools.run(sub_ctx, "write_file", {"path": "z.txt", "content": "no"}, allowed=["read_file"])
    assert out.is_error and not (repo / "z.txt").exists()


async def test_pool_limits_queue_extra_units(app, repo):
    mgr = app.extensions["subagents"]
    mgr.pools["api"] = asyncio.Semaphore(2)
    app.claude.delay = 0.2
    ctx = ctx_for(app, repo)
    outs = [await app.tools.run(ctx, "spawn_subagent", {"name": f"u{i}", "tier": "claude.fast",
                                                        "instructions": "x"}) for i in range(4)]
    await asyncio.sleep(0.05)
    statuses = sorted(s.status for s in mgr.subs.values())
    assert statuses.count("running") == 2 and statuses.count("queued") == 2
    ids = [o.text.split(" as ")[1].split()[0] for o in outs]
    await app.tools.run(ctx, "get_subagent_result", {"ids": ids})
    assert all(mgr.subs[i].status == "done" for i in ids)
