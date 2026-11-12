import time

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Usage
from gamedevworkstation.providers.fake import FakeProvider
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}


@pytest.fixture
def state(tmp_path):
    s = AppState(db_path=tmp_path / "s.db")
    s.providers.override("anthropic", "default", FakeProvider("anthropic"))
    oa = FakeProvider("openai")
    oa.models = ["gpt-6.1-sol", "gpt-6.1-terra"]
    s.providers.override("openai", "default", oa)
    return s


@pytest.fixture
def client(state):
    with TestClient(create_app("t", state)) as c:
        yield c


def test_valid_key_online_bad_key_auth_failed(client, state):
    state.providers.chat("openai").auth_status = "auth_failed"
    snap = client.post("/api/status/refresh", headers=H).json()
    by = {p["provider"]: p for p in snap["providers"]}
    assert by["anthropic"]["status"] == "online"
    assert by["openai"]["status"] == "auth_failed"
    m = snap["models"]
    assert m["claude-haiku-5-5"]["status"] == "online"
    # Models of a failed provider never show as online.
    assert all(v["status"] != "online" for k, v in m.items() if v["provider"] == "openai")
    # A model missing from an online provider's list is not online either.
    assert m["claude-fable-5-1"]["status"] == "unavailable"


def test_unreachable(client, state):
    class Boom(FakeProvider):
        async def check_auth(self):
            raise ConnectionError("no route to host")

    state.providers.override("anthropic", "default", Boom())
    snap = client.post("/api/status/refresh", headers=H).json()
    a = next(p for p in snap["providers"] if p["provider"] == "anthropic")
    assert a["status"] == "unreachable" and "no route" in a["error"]
    assert snap["models"]["claude-opus-5-5"]["status"] == "unreachable"


def _rec(state, **kw):
    u = kw.pop("usage", Usage(input_tokens=100, output_tokens=50, cache_read_tokens=400, reasoning_tokens=10,
                              cost_usd=0.01))
    return state.usage.record(usage=u, **{"provider": "anthropic", "model": "claude-opus-5-5", **kw})


def test_usage_models_comparison_savings_csv(client, state):
    sid = state.store.create(title="Usage test")["id"]
    _rec(state, session_id=sid, latency_ms=100, effort="medium", context_fill=0.1)
    _rec(state, session_id=sid, latency_ms=300, effort="medium", context_fill=0.3)
    _rec(state, session_id=sid, model="claude-haiku-5-5", role="subagent", effort="low", latency_ms=50,
         usage=Usage(input_tokens=1000, output_tokens=200, cost_usd=0.0002))
    _rec(state, session_id=sid, ok=False, error_kind="rate_limit", usage=Usage())
    state.db.insert("delegation_stats", {"ts": time.time(), "job_type": "extract", "provider": "anthropic",
                                         "tier": "claude.fast", "model": "claude-haiku-5-5", "effort": "low",
                                         "cost_usd": 0.0002, "success": 1})
    models = {m["model"]: m for m in client.get("/api/usage/models", headers=H).json()}
    opus = models["claude-opus-5-5"]
    assert opus["requests"] == 3 and opus["latency_p95"] == 300 and opus["rate_limit_rate"] == pytest.approx(1 / 3)
    assert opus["effort"]["medium"] == 2 and opus["top_sessions"][0]["title"] == "Usage test"
    assert opus["cache_hit_rate"] == pytest.approx(800 / 1000)
    assert models["claude-haiku-5-5"]["share_main"] == 0
    sub_only = client.get("/api/usage/models?role=subagent", headers=H).json()
    assert [m["model"] for m in sub_only] == ["claude-haiku-5-5"]
    cmp = {m["model"]: m for m in client.get("/api/usage/comparison", headers=H).json()}
    assert cmp["claude-haiku-5-5"]["success_rate"] == 1.0
    assert cmp["claude-haiku-5-5"]["by_job_type"]["extract"]["count"] == 1
    sv = client.get("/api/usage/savings", headers=H).json()
    assert sv["estimated_without_delegation"] > sv["actual"]  # haiku work priced at opus rates
    csv_text = client.get("/api/usage/export.csv", headers=H).text
    assert csv_text.splitlines()[0].startswith("time,session_id") and len(csv_text.splitlines()) == 5
    per = client.get(f"/api/usage/session/{sid}", headers=H).json()
    assert {m["model"] for m in per["models"]} == {"claude-opus-5-5", "claude-haiku-5-5"}


def test_elevenlabs_rows_report_characters_and_credits(client, state):
    # ElevenLabs bills characters/credits, so the comparison table and the session panel show those, not tokens=0.
    sid = state.store.create(title="Voiceover")["id"]
    _rec(state, session_id=sid, provider="elevenlabs", model="eleven_v4", usage=Usage(characters=1200, credits=600))
    _rec(state, session_id=sid, provider="elevenlabs", model="scribe_v2", usage=Usage(credits=90))
    cmp = {m["model"]: m for m in client.get("/api/usage/comparison", headers=H).json()}
    assert cmp["eleven_v4"]["tokens"] == 0 and cmp["eleven_v4"]["characters"] == 1200
    assert cmp["eleven_v4"]["credits"] == 600 and cmp["scribe_v2"]["credits"] == 90
    per = {m["model"]: m for m in client.get(f"/api/usage/session/{sid}", headers=H).json()["models"]}
    assert per["eleven_v4"]["characters"] == 1200 and per["scribe_v2"]["credits"] == 90


def test_spend_limit_pauses_agents(state):
    state.config.limits["global_daily_usd"] = 0.01
    _rec(state, usage=Usage(cost_usd=0.02))
    from gamedevworkstation.usage import BudgetExceeded

    with pytest.raises(BudgetExceeded):
        state.usage.check()
    state.usage.resume_all()
    state.config.limits["global_daily_usd"] = 100
    state.usage.check()


def test_role_filters_comparison_and_savings_follow_filters(client, state):
    a = state.store.create(title="A")["id"]
    b = state.store.create(title="B")["id"]
    big = Usage(input_tokens=10_000, output_tokens=2_000, cost_usd=0.5)
    _rec(state, session_id=a, usage=big)
    _rec(state, session_id=a, model="claude-haiku-5-5", role="subagent",
         usage=Usage(input_tokens=10_000, output_tokens=2_000, cost_usd=0.02))
    # Non-delegation roles: never re-priced as delegated work.
    _rec(state, session_id=a, model="claude-haiku-5-5", role="compact",
         usage=Usage(input_tokens=50_000, output_tokens=1_000, cost_usd=0.06))
    _rec(state, session_id=a, model="claude-haiku-5-5", role="tool",
         usage=Usage(input_tokens=1_000, output_tokens=100, cost_usd=0.001))
    _rec(state, session_id=b, model="gpt-6.1-sol", provider="openai", role="subagent",
         usage=Usage(input_tokens=5_000, output_tokens=500, cost_usd=0.03))
    for sid, model, prov in ((a, "claude-haiku-5-5", "anthropic"), (b, "gpt-6.1-sol", "openai")):
        state.db.insert("delegation_stats", {"ts": time.time(), "session_id": sid, "job_type": "extract",
                                             "provider": prov, "model": model, "cost_usd": 0.01, "success": 1})

    def get(path, **q):
        return client.get(path, params={k: v for k, v in q.items() if v}, headers=H).json()

    # "Subagents" means role == subagent only; the rest is "other".
    sub = {m["model"]: m for m in get("/api/usage/models", role="subagent")}
    assert set(sub) == {"claude-haiku-5-5", "gpt-6.1-sol"} and sub["claude-haiku-5-5"]["requests"] == 1
    other = {m["model"]: m for m in get("/api/usage/models", role="other")}
    assert set(other) == {"claude-haiku-5-5"} and other["claude-haiku-5-5"]["requests"] == 2

    # Comparison honours session / provider / model / role.
    cmp_a = {m["model"]: m for m in get("/api/usage/comparison", session_id=a)}
    assert "gpt-6.1-sol" not in cmp_a and cmp_a["claude-haiku-5-5"]["tasks"] == 1
    assert [m["model"] for m in get("/api/usage/comparison", provider="openai")] == ["gpt-6.1-sol"]
    assert [m["model"] for m in get("/api/usage/comparison", model="claude-opus-5-5")] == ["claude-opus-5-5"]
    main_only = get("/api/usage/comparison", role="main")
    assert [m["model"] for m in main_only] == ["claude-opus-5-5"] and main_only[0]["tasks"] == 0

    # Savings: only subagent rows are re-priced; compact/tool cost the same on both sides.
    orch = state.config.model("claude-opus-5-5")
    from gamedevworkstation.providers.base import compute_cost
    sv = get("/api/usage/savings", session_id=a)
    assert sv["actual"] == pytest.approx(0.5 + 0.02 + 0.06 + 0.001)
    assert sv["other_actual"] == pytest.approx(0.061) and sv["delegated_actual"] == pytest.approx(0.02)
    repriced = compute_cost(orch, Usage(input_tokens=10_000, output_tokens=2_000))
    assert sv["saved"] == pytest.approx(repriced - 0.02)
    assert get("/api/usage/savings", session_id=a, role="main")["saved"] == 0
    assert get("/api/usage/savings", session_id=a, role="other")["saved"] == 0
    assert get("/api/usage/savings", provider="openai")["delegated_actual"] == pytest.approx(0.03)
    # Custom ranges: until bounds the window.
    assert get("/api/usage/models", until=str(time.time() - 3600)) == []


def test_output_series_and_totals_agree_on_reasoning(client, state):
    _rec(state, usage=Usage(input_tokens=100, output_tokens=500, reasoning_tokens=300, cost_usd=0.01))
    m = client.get("/api/usage/models", headers=H).json()[0]
    assert m["tokens"]["output"] == 200 and m["tokens"]["reasoning"] == 300
    assert sum(d["output"] for d in m["series"]) == m["tokens"]["output"]
    assert sum(d["reasoning"] for d in m["series"]) == m["tokens"]["reasoning"]
