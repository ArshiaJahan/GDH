"""OpenAI delegation routes and pricing, exercised offline with isolated app data."""
import tomllib
from pathlib import Path

import pytest

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.config import DEFAULT_CONFIG_PATH, Config
from gamedevworkstation.core.types import Usage
from gamedevworkstation.features.subagents import SubagentManager, _register_tools
from gamedevworkstation.providers.base import compute_cost
from gamedevworkstation.providers.fake import FakeProvider


CODEX_TIERS = {
    "codex.fast": "gpt-6.1-sol",
    "codex.standard": "gpt-6.1-sol",
    "codex.cli": "gpt-6.1-sol",
    "codex.deep": "gpt-6.2-sol",
    "codex.computer": "gpt-6.1-terra",
}


def test_codex_tiers_follow_the_model_rule(cfg):
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    for path in (DEFAULT_CONFIG_PATH, example):
        config = Config.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
        for tier, model in CODEX_TIERS.items():
            assert config.resolve_known(tier) == model
            assert config.tier_models()[tier]["model"] == model
    assert {tier: cfg.resolve(tier) for tier in CODEX_TIERS} == CODEX_TIERS


@pytest.mark.parametrize("input_tokens", [10_000, 265_000, 300_000])
def test_gpt_6_2_sol_is_priced_like_6_1_sol(cfg, input_tokens):
    usage = Usage(input_tokens=input_tokens, output_tokens=2_000,
                  cache_write_tokens=3_000, cache_read_tokens=4_000)
    assert compute_cost(cfg.model("gpt-6.2-sol"), usage) == compute_cost(cfg.model("gpt-6.1-sol"), usage)
    old = cfg.model("gpt-6.1-sol").model_dump(exclude={"id", "display_name"})
    assert cfg.model("gpt-6.2-sol").model_dump(exclude={"id", "display_name"}) == old


@pytest.mark.parametrize("tier,model", [
    ("codex.deep", "gpt-6.2-sol"),
    ("codex.computer", "gpt-6.1-terra"),
])
async def test_spawn_accepts_new_tiers(tmp_path, tier, model):
    # conftest isolates GDW_HOME and disables Keychain for every test.
    app = AppState(db_path=tmp_path / "app.db")
    fake = FakeProvider("openai")
    app.providers.override("openai", "default", fake)
    mgr = SubagentManager(app)
    app.extensions["subagents"] = mgr
    _register_tools(app, mgr)
    session = app.store.create(folder=str(tmp_path), mode="accept_edits")
    ctx = ToolContext(app=app, session=session, run_id=f"main:{session['id']}")
    result = await app.tools.run(ctx, "spawn_subagent", {
        "name": tier, "provider": "codex", "tier": tier, "effort": "low",
        "instructions": "Report ready.", "run_in_background": False,
    })
    assert not result.is_error, result.text
    assert fake.calls and all(call.model == model for call in fake.calls)
    sub = next(iter(mgr.subs.values()))
    assert (sub.tier, sub.model, sub.provider, sub.status) == (tier, model, "openai", "done")
