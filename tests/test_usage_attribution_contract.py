"""Pin the response shapes the Usage page's Cost attribution section reads."""
import time

from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Usage, new_id
from gamedevworkstation.features.status import StatusChecker
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}


def test_usage_page_attribution_and_trace_api_contract(tmp_path, monkeypatch):
    async def no_network_checks(_checker):
        pass

    monkeypatch.setattr(StatusChecker, "astart", no_network_checks)
    state = AppState(db_path=tmp_path / "app.db")
    sid = new_id("ses_")
    state.usage.record(provider="anthropic", model="claude-haiku-5-5", session_id=sid,
                       usage=Usage(input_tokens=10, output_tokens=5, cost_usd=0.5))
    state.usage.record(provider="anthropic", model="claude-haiku-5-5", session_id=sid, billing="subscription",
                       usage=Usage(input_tokens=1, output_tokens=1, cost_usd=0.25))
    # A row from before attribution existed has no snapshot at all.
    state.usage.record(provider="openai", model="gpt-6.1-terra", usage=Usage(cost_usd=0.1))
    state.db.execute("UPDATE usage_records SET task_attribution = NULL WHERE provider = 'openai'")
    state.db.execute("UPDATE usage_records SET task_attribution = 'ambiguous' WHERE billing = 'subscription'")

    with TestClient(create_app("t", state)) as client:
        assert client.get("/api/usage/attribution").status_code == 401
        since = time.time() - 3600
        body = client.get("/api/usage/attribution", params={"group_by": "task", "since": since}, headers=H).json()
        assert set(body) == {"group_by", "rows", "totals", "next_offset"} and body["group_by"] == "task"
        assert {"ledger_usd", "subscription_estimated_usd", "tokens", "attempts"} <= set(body["totals"])
        for row in body["rows"]:
            assert {"task_id", "task_attribution", "task_code", "task_title",
                    "ledger_usd", "subscription_estimated_usd", "attempts"} <= set(row)
        by_state = {row["task_attribution"]: row for row in body["rows"]}
        assert set(by_state) == {None, "unlinked", "ambiguous"}  # legacy has no state
        assert by_state[None]["ledger_usd"] == 0.1
        assert by_state["unlinked"]["ledger_usd"] == 0.5
        assert by_state["ambiguous"]["subscription_estimated_usd"] == 0.25

        model = client.get("/api/usage/attribution", params={"group_by": "model"}, headers=H).json()
        assert all(row["key"] == [row["provider"], row["model"]] for row in model["rows"])
        for group in ("session", "role", "run"):
            assert client.get("/api/usage/attribution", params={"group_by": group}, headers=H).status_code == 200
        assert client.get("/api/usage/attribution", params={"group_by": "bad"}, headers=H).status_code == 422

        # The disclosure lists root spans for one session; an unknown session is an empty list, not an error.
        empty = client.get("/api/traces", params={"session_id": sid, "limit": 20}, headers=H).json()
        assert empty["traces"] == [] and empty["next_cursor"] is None and "health" in empty
        with state.tracing.span("session_turn", category="turn", session_id=sid):
            pass
        deadline = time.monotonic() + 5
        while not (traces := client.get("/api/traces", params={"session_id": sid}, headers=H).json()["traces"]):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        root = traces[0]
        assert {"trace_id", "start_ns", "end_ns", "status", "name", "attrs"} <= set(root)
        assert root["attrs"]["gdw.outcome"] == "ok" and root["end_ns"] >= root["start_ns"]
