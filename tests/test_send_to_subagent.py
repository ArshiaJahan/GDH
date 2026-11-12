"""Sending an item to a subagent: delivered while it runs, a clear `not_running` once it has
finished (also for subagents from an earlier app run), and the follow-up message to the session."""
import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.config import data_dir
from gamedevworkstation.features.subagents import Subagent
from gamedevworkstation.providers.fake import FakeProvider, text_response
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}


def wait_idle(client, sid, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not client.get(f"/api/sessions/{sid}", headers=H).json()["running"]:
            return
        time.sleep(0.02)
    raise TimeoutError


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "s.db")
    fake = FakeProvider()
    s.providers.override("anthropic", "default", fake)
    (tmp_path / "report.md").write_text("# Report\n")
    with TestClient(create_app("t", s)) as c:
        sid = c.post("/api/sessions", json={}, headers=H).json()["id"]
        iid = s.items.add_file(tmp_path / "report.md", source="agent", session_id=sid, provider="anthropic",
                               model="claude-haiku-5-5")
        yield c, s, fake, sid, iid


def add_sub(s, sid, status, tier="claude.fast", sub_id="sub_t1"):
    sub = Subagent(id=sub_id, session_id=sid, name="summarize-docs", provider="anthropic", tier=tier,
                   model="claude-haiku-5-5", effort="low", instructions="Summarize the docs.", tools=[], status=status)
    s.extensions["subagents"].subs[sub.id] = sub
    return sub


def send(c, iid, **body):
    return c.post(f"/api/items/{iid}/send", json=body, headers=H)


def test_running_subagent_gets_the_item_in_its_inbox(env):
    c, s, _, sid, iid = env
    sub = add_sub(s, sid, "running")
    r = send(c, iid, target="subagent", subagent_id=sub.id).json()
    assert r["ok"] is True and r["status"] == "sent"
    assert len(sub.inbox) == 1 and iid in sub.inbox[0]
    # The item's title (a web page's, for a link) reaches the subagent as outside content.
    assert re.search(rf'<untrusted-[0-9a-f]{{8}} source="item:{iid} title">\nreport.md\n</untrusted-', sub.inbox[0])


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_finished_subagent_returns_not_running_and_queues_nothing(env, status):
    c, s, _, sid, iid = env
    sub = add_sub(s, sid, status)
    r = send(c, iid, target="subagent", subagent_id=sub.id)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is False and d["status"] == "not_running"
    assert d["subagent"]["id"] == sub.id and d["subagent"]["session_id"] == sid and d["subagent"]["status"] == status
    assert "finished" in d["message"]
    assert sub.inbox == []  # nobody would ever read it


def test_codex_cli_runs_have_no_inbox(env):
    c, s, _, sid, iid = env
    sub = add_sub(s, sid, "running", tier="codex.cli")
    d = send(c, iid, target="subagent", subagent_id=sub.id).json()
    assert d["ok"] is False and d["status"] == "no_inbox" and sub.inbox == []


def test_subagent_from_an_earlier_run_is_not_running_and_unknown_ids_404(env):
    c, s, _, sid, iid = env
    d = data_dir() / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    (d / "sub_old.json").write_text(json.dumps({"card": {"id": "sub_old", "name": "old-unit", "status": "done",
                                                         "result_preview": "Found 3 issues."}, "result": "", "history": []}))
    s.jobs.start(sid, "subagent", "old-unit", {"subagent": "sub_old"}, status="done")
    r = send(c, iid, target="subagent", subagent_id="sub_old").json()
    assert r["status"] == "not_running" and r["subagent"]["session_id"] == sid
    assert send(c, iid, target="subagent", subagent_id="sub_nope").status_code == 404
    assert send(c, iid, target="subagent", subagent_id="../sub_old").status_code == 404
    # The follow-up for it carries the saved result preview, since the subagent itself is gone.
    r = send(c, iid, target="followup", subagent_id="sub_old")
    assert r.status_code == 200
    wait_idle(c, sid)
    first = c.get(f"/api/sessions/{sid}/messages", headers=H).json()[0]["content"][0]["text"]
    assert "Follow up on subagent old-unit (sub_old, done)" in first and "Found 3 issues." in first


def test_followup_posts_to_the_session_and_runs_the_main_agent(env):
    c, s, fake, sid, iid = env
    sub = add_sub(s, sid, "done")
    fake.script = [text_response("On it.")]
    r = send(c, iid, target="followup", subagent_id=sub.id)
    assert r.status_code == 200 and r.json()["status"] == "followup" and r.json()["session_id"] == sid
    wait_idle(c, sid)
    msgs = c.get(f"/api/sessions/{sid}/messages", headers=H).json()
    text = msgs[0]["content"][0]["text"]
    assert text.startswith(f"Follow up on subagent summarize-docs ({sub.id}, done) with item {iid} at ")
    assert re.search(rf'<untrusted-[0-9a-f]{{8}} source="item:{iid} title">\nreport.md\n</untrusted-', text)
    assert "message_subagent" in text
    assert msgs[-1]["role"] == "assistant"
    assert fake.calls[-1].messages[0].text() == text


def test_followup_refuses_while_the_main_agent_works_and_for_sensitive_items(env, monkeypatch):
    c, s, _, sid, iid = env
    sub = add_sub(s, sid, "done")
    monkeypatch.setattr(s.runner, "is_running", lambda x: True)
    assert send(c, iid, target="followup", subagent_id=sub.id).status_code == 409
    monkeypatch.undo()
    c.patch(f"/api/items/{iid}", json={"sensitive": True}, headers=H)
    monkeypatch.setitem(s.config.data_policy, "sensitive_allowed", [])
    assert send(c, iid, target="followup", subagent_id=sub.id).status_code == 403
    assert c.get(f"/api/sessions/{sid}/messages", headers=H).json() == []


def test_unknown_target_is_400(env):
    c, _, _, _, iid = env
    assert send(c, iid, target="nowhere").status_code == 400
