"""Tier discovery and Opus consent, using isolated app data and fake providers only."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from gamedevworkstation import skills
from gamedevworkstation.agent.loop import AgentRunner
from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.features.subagents import SubagentManager, _register_tools
from gamedevworkstation.providers.fake import FakeProvider, text_response


@pytest.fixture
def app(tmp_path):
    app = AppState(db_path=tmp_path / "tier-policy.db")
    app.claude = FakeProvider("anthropic", [text_response("done")])
    app.providers.override("anthropic", "default", app.claude)
    mgr = SubagentManager(app)
    app.extensions["subagents"] = mgr
    _register_tools(app, mgr)
    return app


def context(app):
    return ToolContext(app=app, session=app.store.create(mode="accept_edits"), run_id="tier-policy")


def test_system_prompt_names_tier_policy(app):
    session = context(app).session
    prompt = "\n".join(AgentRunner(app).system_segments(session))
    assert ("Tier policy: when you spawn a subagent, follow the delegation-tiers skill; "
            "where it differs from the delegation skill's "
            "routing table, delegation-tiers wins. Opus (claude.deep) subagents need the user's approval.") in prompt


def test_delegation_tiers_skill_is_featured_and_indexed():
    policy = skills.get_skill("delegation-tiers")
    assert policy and policy["native"] and policy["featured"]
    assert skills.FEATURED_SKILLS.index("delegation-tiers") == skills.FEATURED_SKILLS.index("cost-effective-claude-delegation") + 1
    prompt = "\n".join(skills.system_skill_segments({"skill_mode": "progressive"}))
    assert "- delegation-tiers:" in prompt
    # A pinned policy is already disclosed in full rather than repeated in the index.
    pinned = "\n".join(skills.system_skill_segments({"skill_mode": "progressive", "pinned_skills": ["delegation-tiers"]}))
    assert '<skill name="delegation-tiers">' in pinned


@pytest.mark.parametrize("tier,model_tier", [("claude.deep", None), ("claude.standard", "claude.deep"),
                                           ("claude.deep", "claude.standard")])
async def test_opus_subagent_asks_first_and_decline_is_actionable(app, tier, model_tier):
    if model_tier:
        app.config.tiers[tier] = app.config.resolve(model_tier)
    ctx = context(app)
    brief = "Review this design.\n" * 80
    task = asyncio.create_task(app.tools.run(ctx, "spawn_subagent", {
        "name": "review", "tier": tier, "effort": "medium", "instructions": brief}))

    async def pending_card():
        while not (cards := app.approvals.pending(ctx.session_id)):
            await asyncio.sleep(0.001)
        return cards[0]

    try:
        card = await asyncio.wait_for(pending_card(), 2)
        assert card["kind"] == "opus_subagent"
        assert card["payload"] == {"subject": "Opus subagent: review", "name": "review", "tier": tier,
                                   "model": app.config.resolve(tier), "effort": "medium", "instructions": brief[:600]}
        assert not app.claude.calls
        assert not app.extensions["subagents"].subs
        assert not app.db.all("SELECT * FROM jobs")
        app.approvals.resolve(card["id"], "deny")
        out = await asyncio.wait_for(task, 2)
        assert out.is_error
        assert out.text == "The user declined an Opus subagent. Continue with claude.standard (Sonnet) in smaller slices."
        assert not app.claude.calls
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_allowlisted_opus_skips_the_card(app, monkeypatch):
    app.config.modes["allowlist"] = ["opus_subagent:claude.deep"]
    ask = AsyncMock(side_effect=AssertionError("Allowlisted Opus must not ask"))
    monkeypatch.setattr(app.approvals, "ask", ask)
    out = await app.tools.run(context(app), "spawn_subagent", {
        "name": "approved", "tier": "claude.deep", "instructions": "Review", "run_in_background": False})
    assert not out.is_error
    assert len(app.claude.calls) == 1
    ask.assert_not_awaited()


async def test_sonnet_subagent_never_asks(app, monkeypatch):
    ask = AsyncMock(side_effect=AssertionError("Sonnet must not ask"))
    monkeypatch.setattr(app.approvals, "ask", ask)
    out = await app.tools.run(context(app), "spawn_subagent", {
        "name": "sonnet", "tier": "claude.standard", "effort": "medium",
        "instructions": "Review", "run_in_background": False})
    assert not out.is_error
    assert len(app.claude.calls) == 1
    ask.assert_not_awaited()


async def test_approved_opus_starts_after_consent(app, monkeypatch):
    async def approve(session_id, kind, payload):
        assert kind == "opus_subagent"
        assert not app.claude.calls and not app.extensions["subagents"].subs
        return {"status": "approved"}

    monkeypatch.setattr(app.approvals, "ask", approve)
    out = await app.tools.run(context(app), "spawn_subagent", {
        "name": "approved", "tier": "claude.deep", "instructions": "Review", "run_in_background": False})
    assert not out.is_error
    assert len(app.claude.calls) == 1
