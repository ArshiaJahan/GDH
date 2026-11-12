import asyncio
import re
import subprocess

import pytest

from workspace.agent.tools import ToolContext
from workspace.app import AppState
from workspace.features import subagents as subs_mod
from workspace.features.subagents import SubagentManager, _register_tools
from workspace.providers.fake import FakeProvider, text_response


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
    a.claude = FakeProvider("anthropic")
    a.providers.override("anthropic", "default", a.claude)
    mgr = SubagentManager(a)
    a.extensions["subagents"] = mgr
    _register_tools(a, mgr)
    return a


def ctx_for(app, folder):
    s = app.store.create(folder=str(folder), mode="accept_edits")
    return ToolContext(app=app, session=s, run_id=f"main:{s['id']}")


def sid(out):
    return out.text.split(" as ")[1].split()[0]


def blocker(gate: asyncio.Event, seen: list | None = None):
    """A scripted reply that holds the unit (inside its model call path) until the gate opens."""
    def script(req):
        if seen is not None:
            seen.append([m.text() for m in req.messages])
        return text_response("ok")
    return script


async def test_history_dropped_and_message_resumes_with_prior_turns(app, repo):
    seen: list = []
    app.claude.script = [blocker(None, seen), blocker(None, seen)]
    ctx = ctx_for(app, repo)
    mgr = app.extensions["subagents"]
    i = sid(await app.tools.run(ctx, "spawn_subagent", {"name": "u", "tier": "claude.fast", "instructions": "first brief"}))
    await app.tools.run(ctx, "get_subagent_result", {"id": i})
    sub = mgr.subs[i]
    assert sub.history == [] and sub.history_on_disk
    out = await app.tools.run(ctx, "message_subagent", {"id": i, "message": "second brief"})
    assert not out.is_error, out.text
    await app.tools.run(ctx, "get_subagent_result", {"id": i})
    assert seen[1][0] == "first brief" and seen[1][-1] == "second brief" and len(seen[1]) == 3
    assert mgr.subs[i].history == [] and mgr.subs[i].history_on_disk


async def test_get_rehydrates_evicted_finished_subagent(app, repo):
    ctx = ctx_for(app, repo)
    mgr = app.extensions["subagents"]
    i = sid(await app.tools.run(ctx, "spawn_subagent", {"name": "u", "tier": "claude.fast", "instructions": "x"}))
    first = await app.tools.run(ctx, "get_subagent_result", {"id": i})
    old = mgr.subs.pop(i)
    got = mgr.get(i)
    assert got is not old and got.done_event.is_set() and got.status == "done"
    assert got.session_id == old.session_id and got.model == old.model and got.result == old.result
    mgr.subs.pop(i)
    again = await app.tools.run(ctx, "get_subagent_result", {"id": i, "wait": False})
    tagless = lambda t: re.sub(r"untrusted-[0-9a-f]{8}", "untrusted-X", t)  # noqa: E731 — a fresh tag each call
    assert "<untrusted-X" in tagless(first.text) and tagless(again.text) == tagless(first.text) and not again.is_error
    assert mgr.get("sub_nope") is None


async def test_prune_keeps_running_and_caps_finished(app, repo, monkeypatch):
    import workspace.features.subagents as m
    monkeypatch.setattr(m, "KEEP_FINISHED", 2)
    ctx = ctx_for(app, repo)
    mgr = app.extensions["subagents"]
    ids = [sid(await app.tools.run(ctx, "spawn_subagent", {"name": f"u{n}", "tier": "claude.fast", "instructions": "x"}))
           for n in range(4)]
    await app.tools.run(ctx, "get_subagent_result", {"ids": ids})
    await asyncio.sleep(0.05)
    assert len(mgr.subs) == 2 and mgr.get(ids[0]) is not None  # evicted ones come back from disk


async def test_queued_unit_creates_worktree_only_after_it_gets_a_slot(app, repo):
    app.config.delegation["max_parallel"]["claude_codex"] = 1
    gate = asyncio.Event()
    started = asyncio.Event()

    class Slow(FakeProvider):
        async def complete(self, req):
            started.set()
            await gate.wait()
            return await super().complete(req)

    slow = Slow("anthropic")
    app.providers.override("anthropic", "default", slow)
    ctx = ctx_for(app, repo)
    mgr = app.extensions["subagents"]
    a = sid(await app.tools.run(ctx, "spawn_subagent", {"name": "a", "tier": "claude.fast", "instructions": "x"}))
    await started.wait()
    out = await app.tools.run(ctx, "spawn_subagent", {"name": "b", "tier": "claude.fast", "instructions": "y",
                                                      "worktree": True})
    assert not out.is_error and "worktree" in out.text
    b = sid(out)
    plan = mgr.subs[b].worktree_plan
    await asyncio.sleep(0.2)
    assert mgr.subs[b].status == "queued" and mgr.subs[b].worktree is None and not plan.exists()
    gate.set()
    await app.tools.run(ctx, "get_subagent_result", {"ids": [a, b]})
    assert mgr.subs[b].status == "done" and mgr.subs[b].worktree == plan and plan.exists()


async def test_worktree_without_folder_fails_at_spawn(app):
    s = app.store.create(mode="accept_edits")
    ctx = ToolContext(app=app, session=s, run_id=f"main:{s['id']}")
    out = await app.tools.run(ctx, "spawn_subagent", {"name": "a", "tier": "claude.fast", "instructions": "x",
                                                      "worktree": True})
    assert out.is_error and "session folder" in out.text and not app.extensions["subagents"].subs


async def test_worktree_failure_fails_the_unit_not_the_manager(app, tmp_path, repo, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    out = await app.tools.run(ctx_for(app, plain), "spawn_subagent", {"name": "a", "tier": "claude.fast",
                                                                      "instructions": "x", "worktree": True})
    assert out.is_error and "git repo" in out.text and not app.extensions["subagents"].subs  # refused up front

    async def broken(*_a, **_k):
        raise subs_mod.worktrees.GitError("disk full")

    monkeypatch.setattr(subs_mod.worktrees, "create", broken)
    out = await app.tools.run(ctx_for(app, repo), "spawn_subagent", {"name": "b", "tier": "claude.fast",
                                                                     "instructions": "x", "worktree": True,
                                                                     "run_in_background": False})
    assert out.is_error and "disk full" in out.text


async def test_raising_max_parallel_lets_queued_unit_start_live(app, repo):
    app.config.delegation["max_parallel"]["claude_codex"] = 1
    gate = asyncio.Event()

    class Slow(FakeProvider):
        async def complete(self, req):
            if not gate.is_set() and len(self.calls) == 0:
                self.calls.append(req)
                await gate.wait()
                return text_response("ok")
            return await super().complete(req)

    app.providers.override("anthropic", "default", Slow("anthropic"))
    ctx = ctx_for(app, repo)
    mgr = app.extensions["subagents"]
    a = sid(await app.tools.run(ctx, "spawn_subagent", {"name": "a", "tier": "claude.fast", "instructions": "x"}))
    await asyncio.sleep(0.1)
    b = sid(await app.tools.run(ctx, "spawn_subagent", {"name": "b", "tier": "claude.fast", "instructions": "y"}))
    await asyncio.sleep(0.2)
    assert mgr.subs[a].status == "running" and mgr.subs[b].status == "queued"
    app.config.delegation["max_parallel"]["claude_codex"] = 2
    await asyncio.wait_for(mgr.subs[b].done_event.wait(), 2.5)
    assert mgr.subs[b].status == "done" and mgr.subs[a].status == "running"  # a was never cancelled
    gate.set()
    await mgr.subs[a].done_event.wait()
