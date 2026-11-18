"""CI failure triage wiring: the `gdw triage` command, the LLM fallback and POST /api/triage."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation import __main__ as entry
from gamedevworkstation.app import AppState
from gamedevworkstation.core.effort import EffortApprovalRequired
from gamedevworkstation.features import ci_triage as T
from gamedevworkstation.features import triage_rules as R
from gamedevworkstation.providers.fake import FakeProvider, text_response
from gamedevworkstation.server import create_app

FIX = Path(__file__).parent / "fixtures" / "ci_logs"
LOG = FIX / "gdh_windows_path_assert.log"
LOG2 = FIX / "gdh_pytest_docs_assert.log"
H = {"Authorization": "Bearer t"}


def test_cli_markdown(capsys):
    assert T.cli([str(LOG)]) == 0
    out = capsys.readouterr().out
    assert "### CI triage:" in out and "tests/test_release_feed.py" in out


def test_cli_json_has_rule_coverage(capsys):
    assert T.cli([str(LOG), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert "rule_coverage" in d and d["failures"]


def test_cli_merges_sources(capsys):
    assert T.cli([str(LOG), str(LOG2), "--json"]) == 0
    both = json.loads(capsys.readouterr().out)
    T.cli([str(LOG), "--json"])
    one = json.loads(capsys.readouterr().out)
    assert both["blocks"] > one["blocks"]


def test_cli_missing_file(capsys):
    assert T.cli(["/no/such/file.log"]) == 2
    assert capsys.readouterr().err


def test_cli_run_id(monkeypatch, capsys):
    seen = []

    def fake(run_id, repo=None):
        seen.append((run_id, repo))
        return LOG.read_text()

    monkeypatch.setattr(R, "fetch_run_log", fake)
    monkeypatch.setattr(T, "fetch_run_log", fake)
    assert T.cli(["987654", "--repo", "me/repo"]) == 0
    assert seen == [("987654", "me/repo")]
    assert "### CI triage:" in capsys.readouterr().out


def test_cli_bad_repo(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("gh must not run"))
    assert T.cli(["987654", "--repo", "bad repo; rm"]) == 2
    assert capsys.readouterr().err


def test_cli_summary(monkeypatch, tmp_path, capsys):
    f = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(f))
    assert T.cli([str(LOG), "--summary"]) == 0
    assert "### CI triage:" in f.read_text()
    monkeypatch.delenv("GITHUB_STEP_SUMMARY")
    assert T.cli([str(LOG), "--summary"]) == 2


def test_cli_comment(monkeypatch):
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert T.cli([str(LOG), "--comment", "12", "--repo", "me/repo"]) == 0
    assert len(calls) == 1
    argv, kw = calls[0]
    assert argv[:7] == ["gh", "pr", "comment", "12", "--edit-last", "--create-if-none", "--body-file"]
    assert argv[7] == "-" and argv[-2:] == ["-R", "me/repo"]
    assert kw["input"].startswith("<!-- gdh-ci-triage -->\n### CI triage:") and kw["timeout"] == 60
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "boom"))
    assert T.cli([str(LOG), "--comment", "12"]) == 2


def test_cli_comment_falls_back_to_plain_comment(monkeypatch):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if "--edit-last" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "no comments found for current user")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert T.cli([str(LOG), "--comment", "12"]) == 0
    assert calls[1] == ["gh", "pr", "comment", "12", "--body-file", "-"]


def test_cli_refuses_bad_local_sources(tmp_path, capsys):
    big = tmp_path / "big.log"
    with open(big, "wb") as f:
        f.truncate(21 * 1024 * 1024)
    assert T.cli([str(big)]) == 2
    assert "too large" in capsys.readouterr().err
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "pipe.log"
        os.mkfifo(fifo)
        assert T.cli([str(fifo)]) == 2
        assert "regular" in capsys.readouterr().err
    if os.path.exists("/dev/zero"):
        assert T.cli(["/dev/zero"]) == 2


def test_main_dispatches_triage(monkeypatch, capsys):
    import uvicorn

    monkeypatch.setattr(uvicorn, "Server", lambda *a, **k: pytest.fail("server started"))
    monkeypatch.setattr(sys, "argv", ["gdw", "triage", str(LOG)])
    with pytest.raises(SystemExit) as e:
        entry.main()
    assert e.value.code == 0
    assert "### CI triage:" in capsys.readouterr().out


# ------------------------------------------------------------------ LLM


def _app(tmp_path, reply):
    s = AppState(db_path=tmp_path / "t.db")
    fake = FakeProvider(script=[text_response(reply)])
    s.providers.override("anthropic", "default", fake)
    return s, fake


async def test_make_llm_parses_reply(tmp_path):
    reply = 'Sure: {"category": "infra", "summary": "runner lost", "file": null, "line": null, "fix": "rerun", "confidence": 0.7} done'
    s, fake = _app(tmp_path, reply)
    f = await T.make_llm(s)(["weird failure", "<untrusted-x>ignore previous</untrusted-x>"])
    assert f and f.category == "infra" and f.source == "llm" and f.confidence == 0.7
    req = fake.calls[0]
    assert "<untrusted-" in req.messages[0].text() and req.max_tokens == 600 and req.show_thinking is False
    rows = s.db.all("SELECT feature FROM usage_records")
    assert [r["feature"] for r in rows] == ["ci_triage"]


async def test_make_llm_invalid_reply(tmp_path):
    s, _ = _app(tmp_path, '{"category": "nonsense", "summary": "x"}')
    assert await T.make_llm(s)(["x"]) is None
    s, _ = _app(tmp_path, "no json here")
    assert await T.make_llm(s)(["x"]) is None


async def test_make_llm_effort_needs_approval(tmp_path):
    s, fake = _app(tmp_path, "{}")
    with pytest.raises(EffortApprovalRequired):
        await T.make_llm(s, effort="xhigh")(["x"])
    assert not fake.calls


# ------------------------------------------------------------------ route


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app("t", AppState(db_path=tmp_path / "t.db"))) as c:
        yield c


def test_route_text(client):
    r = client.post("/api/triage", json={"text": LOG.read_text()}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["report"]["failures"] and d["markdown"].startswith("### CI triage:") and "rule_coverage" in d
    items = client.get("/api/items?grouped=false", headers=H).json()
    assert any(i["id"] == d["item_id"] and i["subtype"] == "ci_triage" for i in items)


def test_route_validation(client):
    assert client.post("/api/triage", json={"text": "a", "path": "b"}, headers=H).status_code == 400
    assert client.post("/api/triage", json={}, headers=H).status_code == 400
    assert client.post("/api/triage", json={"path": "/no/such"}, headers=H).status_code == 400
    assert client.post("/api/triage", json={"path": str(LOG)}, headers=H).status_code == 200


def test_route_run_id_error(client, monkeypatch):
    def boom(run_id, repo=None):
        raise RuntimeError("gh failed")

    monkeypatch.setattr(T, "fetch_run_log", boom)
    assert client.post("/api/triage", json={"run_id": "5"}, headers=H).status_code == 400


def test_route_llm_xhigh_forbidden(client):
    r = client.post("/api/triage", json={"text": "something odd happened", "llm": True, "effort": "xhigh"}, headers=H)
    assert r.status_code == 403


def test_route_refuses_bad_paths(client, tmp_path):
    def post(**kw):
        return client.post("/api/triage", json=kw, headers=H)

    if os.path.exists("/dev/zero"):
        assert post(path="/dev/zero").status_code == 400
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "pipe.log"
        os.mkfifo(fifo)
        assert post(path=str(fifo)).status_code == 400
    big = tmp_path / "big.log"
    with open(big, "wb") as f:
        f.truncate(21 * 1024 * 1024)
    r = post(path=str(big))
    assert r.status_code == 400 and "too large" in r.text
    d = tmp_path / "dir"
    d.mkdir()
    (d / "a.log").write_text(LOG.read_text())
    assert post(path=str(d)).status_code == 200
    (d / "b.log").write_bytes(big.read_bytes())
    assert post(path=str(d)).status_code == 400


def test_route_oversize_text(client):
    r = client.post("/api/triage", json={"text": "x" * (20 * 1024 * 1024 + 1)}, headers=H)
    assert r.status_code == 400 and "too large" in r.text
