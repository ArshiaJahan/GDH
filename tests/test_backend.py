import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from workspace.app import AppState
from workspace.providers.fake import FakeProvider, text_response, tool_response
from workspace.server import create_app

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def state(tmp_path):
    return AppState(db_path=tmp_path / "t.db")


@pytest.fixture
def fake(state):
    f = FakeProvider()
    state.providers.override("anthropic", "default", f)
    return f


@pytest.fixture
def client(state):
    with TestClient(create_app(TOKEN, state)) as c:
        yield c


def wait_idle(client, sid, timeout=5.0):
    import time

    t0 = time.time()
    while time.time() - t0 < timeout:
        if not client.get(f"/api/sessions/{sid}", headers=H).json()["running"]:
            return
        time.sleep(0.02)
    raise TimeoutError


def test_health_open_api_needs_token(client):
    assert client.get("/health").json()["ok"] is True
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/sessions?token=wrong").status_code == 401
    assert client.get("/api/sessions", headers=H).status_code == 200
    assert client.get(f"/api/sessions?token={TOKEN}").status_code == 200


def test_session_crud(client):
    s = client.post("/api/sessions", json={"title": "Alpha"}, headers=H).json()
    assert s["model"] == "claude-opus-5-5" and s["settings"]["skills"] == ["delegation"]
    client.patch(f"/api/sessions/{s['id']}", json={"pinned": True, "title": "Beta", "model": "claude.fast"},
                 headers=H)
    got = client.get(f"/api/sessions/{s['id']}", headers=H).json()
    assert got["pinned"] and got["title"] == "Beta" and got["model"] == "claude-haiku-5-5"
    assert [x["title"] for x in client.get("/api/sessions?q=Bet", headers=H).json()] == ["Beta"]
    client.delete(f"/api/sessions/{s['id']}", headers=H)
    assert client.get("/api/sessions", headers=H).json() == []


def test_chat_turn_persists_messages_events_and_usage(client, state, fake):
    fake.script = [text_response("Hi! See https://example.com/docs.")]
    sid = client.post("/api/sessions", json={}, headers=H).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "hello there"}, headers=H)
    wait_idle(client, sid)
    msgs = client.get(f"/api/sessions/{sid}/messages", headers=H).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"][0]["text"].startswith("Hi!")
    assert msgs[1]["meta"]["model"] == "claude-opus-5-5"
    types = [e["type"] for e in state.bus.replay(0, sid)]
    assert "message.created" in types and "usage.recorded" in types and "message.delta" not in types
    assert state.db.one("SELECT COUNT(*) n FROM usage_records WHERE session_id=?", [sid])["n"] == 1
    # The link was indexed and the session got a title from the first message.
    assert state.items.list(session_id=sid, tab="links")[0]["url"] == "https://example.com/docs"
    assert client.get(f"/api/sessions/{sid}", headers=H).json()["title"] == "hello there"


def test_websocket_streams_and_replays(client, state, fake):
    fake.script = [text_response("streamed reply text")]
    sid = client.post("/api/sessions", json={}, headers=H).json()["id"]
    with client.websocket_connect(f"/ws?token={TOKEN}&since=0") as ws:
        got = []
        while (m := json.loads(ws.receive_text()))["type"] != "ws.ready":
            got.append(m["type"])
        assert "session.created" in got  # replayed from the store
        client.post(f"/api/sessions/{sid}/messages", json={"text": "go"}, headers=H)
        deltas, seen = "", set()
        while "agent.idle" not in seen:
            m = json.loads(ws.receive_text())
            seen.add(m["type"])
            if m["type"] == "message.delta":
                deltas += m["data"]["text"]
        assert deltas == "streamed reply text"
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=bad") as ws:
            ws.receive_text()


def test_tool_loop_with_command_approval(client, state, fake, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "a.txt").write_text("alpha\nbeta\n")
    fake.script = [tool_response("read_file", {"path": "a.txt"}),
                   tool_response("run_command", {"command": "echo hi-from-shell"}),
                   text_response("done")]
    sid = client.post("/api/sessions", json={"folder": str(folder)}, headers=H).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "do it"}, headers=H)
    # The command waits for an approval card.
    import time

    for _ in range(200):
        pend = client.get(f"/api/approvals?session_id={sid}", headers=H).json()
        if pend:
            break
        time.sleep(0.02)
    assert pend[0]["kind"] == "command" and pend[0]["payload"]["command"] == "echo hi-from-shell"
    client.post(f"/api/approvals/{pend[0]['id']}", json={"decision": "approve"}, headers=H)
    wait_idle(client, sid)
    results = [m for m in client.get(f"/api/sessions/{sid}/messages", headers=H).json()
               if m["meta"].get("tool_results")]
    assert "1\talpha" in results[0]["content"][0]["content"][0]["text"]
    assert "hi-from-shell" in results[1]["content"][0]["content"][0]["text"]
    jobs = client.get(f"/api/jobs?session_id={sid}", headers=H).json()
    assert jobs[0]["kind"] == "command" and jobs[0]["status"] == "done"


def test_file_tools_scoped_and_mode(client, state, fake, tmp_path):
    folder = tmp_path / "proj"
    folder.mkdir()
    fake.script = [tool_response("read_file", {"path": "../../etc/passwd"}),
                   tool_response("write_file", {"path": "out.md", "content": "# hi"}),
                   text_response("ok")]
    sid = client.post("/api/sessions", json={"folder": str(folder), "mode": "accept_edits"}, headers=H).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "x"}, headers=H)
    wait_idle(client, sid)
    results = [m for m in client.get(f"/api/sessions/{sid}/messages", headers=H).json()
               if m["meta"].get("tool_results")]
    assert "outside the session folder" in results[0]["content"][0]["content"][0]["text"]
    assert (folder / "out.md").read_text() == "# hi"  # accept_edits: no approval card
    assert state.db.one("SELECT content FROM snapshots WHERE session_id=?", [sid])["content"] is None
    assert state.items.list(session_id=sid) is not None


def test_plan_mode_blocks_edits(client, state, fake, tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    fake.script = [tool_response("write_file", {"path": "x.txt", "content": "no"}), text_response("ok")]
    sid = client.post("/api/sessions", json={"folder": str(folder), "mode": "plan"}, headers=H).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "x"}, headers=H)
    wait_idle(client, sid)
    assert not (folder / "x.txt").exists()


def test_main_session_above_high_needs_approval(client, state, fake):
    sid = client.post("/api/sessions", json={"effort": "max"}, headers=H).json()["id"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "think hard"}, headers=H)
    import time

    for _ in range(200):
        pend = client.get(f"/api/approvals?session_id={sid}", headers=H).json()
        if pend:
            break
        time.sleep(0.02)
    assert pend[0]["kind"] == "effort" and not fake.calls  # nothing sent before approval
    r = client.post(f"/api/approvals/{pend[0]['id']}", json={"decision": "downgrade"}, headers=H).json()
    assert "token" not in r
    wait_idle(client, sid)
    assert fake.calls[0].effort == "high"


def test_relaunch_restores_state(tmp_path):
    db = tmp_path / "persist.db"
    s1 = AppState(db_path=db)
    sid = s1.store.create(title="Keep me")["id"]
    from workspace.core.types import Message

    s1.store.add_message(sid, Message.user("remember"))
    s1.db.close()
    s2 = AppState(db_path=db)
    assert s2.store.get(sid)["title"] == "Keep me"
    assert s2.store.messages(sid)[0].text() == "remember"
    assert any(e["type"] == "message.created" for e in s2.bus.replay(0, sid))


def test_interrupted_tool_calls_are_repaired(tmp_path):
    from workspace.core.types import Message, ToolUseBlock

    s = AppState(db_path=tmp_path / "r.db")
    sid = s.store.create()["id"]
    s.store.add_message(sid, Message.user("go"))
    s.store.add_message(sid, Message.assistant(ToolUseBlock(id="tu_1", name="run_command", input={"command": "x"})))
    s.db.execute("UPDATE sessions SET status='running' WHERE id=?", [sid])
    s.on_startup()
    last = s.store.messages(sid)[-1]
    assert last.meta.get("repaired") and last.content[0].tool_use_id == "tu_1" and last.content[0].is_error
    assert s.store.repair_dangling_tool_calls(sid) == 0
