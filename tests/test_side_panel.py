import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Message, ToolResultBlock, ToolUseBlock
from gamedevworkstation.providers.fake import FakeProvider, text_response
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}


@pytest.fixture
def state(tmp_path):
    s = AppState(db_path=tmp_path / "s.db")
    s.providers.override("anthropic", "default", FakeProvider("anthropic"))
    return s


@pytest.fixture
def client(state):
    with TestClient(create_app("t", state)) as c:
        yield c


def test_context_breakdown(client, state):
    sid = state.store.create()["id"]
    state.store.add_message(sid, Message.user("x" * 3600))
    ctx = client.get(f"/api/sessions/{sid}/context", headers=H).json()
    assert ctx["window"] == 1_000_000
    assert ctx["parts"]["messages"] == 1000
    assert ctx["parts"]["skills"] > 500  # delegation skill is on by default
    assert ctx["parts"]["tools"] > 0 and ctx["parts"]["system"] > 0
    assert 0 < ctx["fraction"] < 0.015  # system, ~25 tool specs (task board included), skills, the message


def test_compact_keeps_originals_and_recent_turns(client, state):
    fake = state.providers.chat("anthropic")
    fake.script = [text_response("- user wants X\n- decided Y")]
    sid = state.store.create()["id"]
    for i in range(6):
        state.store.add_message(sid, Message.user(f"question {i}"))
        a = Message.assistant(ToolUseBlock(id=f"t{i}", name="read_file", input={"path": "a"}))
        state.store.add_message(sid, a)
        state.store.add_message(sid, Message(role="user", content=[ToolResultBlock.text(f"t{i}", "ok")],
                                             meta={"tool_results": True}))
        state.store.add_message(sid, Message.assistant(f"answer {i}"))
    r = client.post(f"/api/sessions/{sid}/compact", headers=H).json()
    assert r["compacted"] == 12  # 3 old turns x 4 messages
    live = state.store.messages(sid, include_compacted=False)
    assert live[0].meta.get("summary") and "decided Y" in live[0].text()
    assert live[1].text() == "question 3"
    assert len(state.store.messages(sid)) == 25  # originals kept
    assert fake.calls[0].model == "claude-haiku-5-5" and fake.calls[0].effort == "low"
    row = state.db.one("SELECT role, model FROM usage_records WHERE session_id=?", [sid])
    assert row == {"role": "compact", "model": "claude-haiku-5-5"}


def test_environment(client):
    env = client.get("/api/environment", headers=H).json()
    assert env["harnesses"]["builtin"] is True
    assert "codex_cli" in env["harnesses"] and env["accounts"]["anthropic"] == ["default"]
