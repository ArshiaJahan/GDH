"""Regressions for problems found while recording the README demo on a real Unity project (2026-11-19).

- L3 turned green for a replay criterion from an EditMode run that never ran the replay test.
- A batch replay had no Editor log, so its report's log_sha256 was empty and L3 refused the evidence.
- Every batch replay reported environment "differs" (os, project_id) on the machine that recorded it.
- The prompt improver gave up ("malformed") when the model put raw newlines inside JSON strings.
- Claude Code aborted a GDW tool call after 300 s of silence (a Unity batch run, an unanswered card).
- An approval card stayed open after the tool call waiting on it was cancelled.
- A recording had no per-call length, and an old stop timer could stop a later recording.
"""
import asyncio
import json
from pathlib import Path

import pytest

from gamedevworkstation.app import AppState
from gamedevworkstation.features import ladder as L
from gamedevworkstation.features import replay as R
from gamedevworkstation.features.pi_contracts import PiFormatError, loads_reply, parse_eval

BACKLOG = """# Backlog: Coin Dash
Current milestone: M1

## M1 Movement feel
Goal: A dash.
Exit: All M1 criteria pass.
Status: active

### M1-S01 Dash
- Status: doing
- Owner skill: replay

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M1-S01-AC1 | Given a run, When replayed, Then hashes match | headless | test:ReplayVerificationTests.LogMatchesCheckpoints |
| M1-S01-AC2 | Given a dash, When replayed, Then hashes match and the dash test passes | headless | test:ReplayVerificationTests.LogMatchesCheckpoints; test:DashTests.Dash |
"""


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "f.db")
    a.lad = L.install(a)
    return a


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "game"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n", encoding="utf-8")
    (d / "BACKLOG.md").write_text(BACKLOG, encoding="utf-8")
    return d


def _report(**over):
    r = {"schema": "gdw.replay.report/1", "status": "pass", "frames": {"expected": 10, "compared": 10},
         "console": {"errors": 0, "warnings": 0}, "log_sha256": "a" * 64, "replay_sha256": "b" * 64,
         "environment": "matched"}
    r.update(over)
    return r


def _tests_row(app, proj, *, passed=(), scope="all"):
    app.lad.record_evidence(proj, "L2", "pass", source="tool:unity", observed="tool", subjects=[],
                            detail={"kind": "tests", "scope": scope, "total": 11, "failed_n": 0,
                                    "passed": list(passed), "failed": []})


def _replay_row(app, proj, ac_id, report=None):
    app.lad.record_evidence(proj, "L3", "pass", source="tool:replay", observed="tool", subjects=[ac_id],
                            detail={"kind": "replay_verified", "report": report or _report()})


def _cands(app, proj, ac_id):
    story = L.read_backlog(proj).stories["M1-S01"]
    ac = next(a for a in story.acs if a.id == ac_id)
    return app.lad._test_candidates(ac, story.milestone, app.lad.evidence(proj))


# --------------------------------------------------------------- ladder


def test_an_editmode_run_covering_the_milestone_is_not_replay_evidence(app, proj):
    _tests_row(app, proj)  # 11 EditMode tests passed, scope "all"; LogMatchesCheckpoints never ran
    assert _cands(app, proj, "M1-S01-AC1") == []


def test_a_tool_observed_replay_report_is(app, proj):
    _replay_row(app, proj, "M1-S01-AC1")
    (c,) = _cands(app, proj, "M1-S01-AC1")
    assert c[1] is True and c[3].startswith("replay_verified pass")


def test_a_report_without_the_editor_log_digest_still_isnt(app, proj):
    _replay_row(app, proj, "M1-S01-AC1", _report(log_sha256=""))
    assert _cands(app, proj, "M1-S01-AC1") == []


def test_a_criterion_naming_both_needs_both(app, proj):
    _replay_row(app, proj, "M1-S01-AC2")
    assert _cands(app, proj, "M1-S01-AC2") == []  # the dash test hasn't been seen
    _tests_row(app, proj, passed=["DashTests.Dash"])
    (c,) = _cands(app, proj, "M1-S01-AC2")
    assert c[1] is True and c[3].startswith("replay_verified pass") and len(c[2]) == 2


# --------------------------------------------------------------- environment


def test_unitys_os_name_matches_this_machine(proj, monkeypatch):
    monkeypatch.setattr(R, "_local_platform_name", lambda: "macOS")
    header = {"os": {"platform": "Mac OS X 26.6.2"}}
    assert "os" not in R.environment_diff(proj, header)
    assert "os" in R.environment_diff(proj, {"os": {"platform": "Windows 11  (10.0.22631) 64bit"}})
    assert R._os_family("Darwin") == R._os_family("Mac OS X 26.6.2") == "macOS"


PROJECT_SETTINGS = """PlayerSettings:
  companyName: DefaultCompany
  productName: Coin Dash
  applicationIdentifier: {}
  buildNumber:
    Standalone: 0
"""


def test_an_unset_application_identifier_is_unitys_default(proj):
    (proj / "ProjectSettings/ProjectSettings.asset").write_text(PROJECT_SETTINGS, encoding="utf-8")
    assert R._project_identifier(proj) == "com.DefaultCompany.Coin-Dash"
    assert "project_id" not in R.environment_diff(proj, {"project": {"id": "com.DefaultCompany.Coin-Dash"}})
    assert "project_id" in R.environment_diff(proj, {"project": {"id": "com.other.Game"}})


def test_an_explicit_standalone_identifier_wins(proj):
    text = PROJECT_SETTINGS.replace("applicationIdentifier: {}",
                                    "applicationIdentifier:\n    Android: com.a.android\n    Standalone: com.a.game")
    (proj / "ProjectSettings/ProjectSettings.asset").write_text(text, encoding="utf-8")
    assert R._project_identifier(proj) == "com.a.game"


# --------------------------------------------------------------- batch replay log


async def test_batch_replay_asks_the_editor_for_its_log(tmp_path, monkeypatch):
    from gamedevworkstation.features import unity_bridge as UB

    seen = {}

    def fake_argv(cli, root, platform, xml, t, **kw):
        seen["extra"] = kw.get("extra")
        seen["xml"] = xml
        raise ValueError("stop here")

    monkeypatch.setattr(UB.uc, "argv_test_batch", fake_argv)
    app = AppState(db_path=tmp_path / "b.db")
    proj = tmp_path / "Game"
    (proj / "ProjectSettings").mkdir(parents=True)
    (proj / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n", encoding="utf-8")
    s = app.store.create(folder=str(proj), mode="ask")
    br = UB.UnityBridge(app)

    async def route(session, op):
        return UB.EditorState(mode="cli_batch"), proj

    async def cli_info():
        return object()

    async def editor_arg(root, cli):
        return None, None

    monkeypatch.setattr(br, "_route", route)
    monkeypatch.setattr(br, "_cli_info", cli_info)
    monkeypatch.setattr(br, "_editor_arg", editor_arg)
    r = await br.run_replay(s, "verify", {"_request_path": "/x/request.json"})
    assert r.status == "error"
    i = seen["extra"].index("-logFile")
    assert seen["extra"][i + 1] == str(seen["xml"].with_suffix(".log"))
    assert seen["extra"][:2] == ["-gdwReplayRequest", "/x/request.json"]


# --------------------------------------------------------------- prompt improver JSON


def test_raw_newlines_inside_json_strings_parse():
    reply = '{"decision": "PROCEED", "goal": "line one\nline two", "cited_facts": []}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(reply)  # what failed before
    assert loads_reply(reply)["goal"] == "line one\nline two"


def test_an_object_wrapped_in_prose_parses():
    assert loads_reply('Here is the evaluation:\n```json\n{"a": 1}\n```\nDone.') == {"a": 1}
    assert loads_reply('Sure. {"a": {"b": 2}} Hope that helps.') == {"a": {"b": 2}}


def test_real_garbage_is_still_malformed():
    with pytest.raises(PiFormatError):
        parse_eval("I can't do that.")


# --------------------------------------------------------------- approvals


async def test_a_card_whose_waiter_is_cancelled_is_closed(tmp_path):
    app = AppState(db_path=tmp_path / "a.db")
    s = app.store.create(folder=str(tmp_path), mode="ask")
    task = asyncio.create_task(app.approvals.ask(s["id"], "unity", {"subject": "replay"}))
    await asyncio.sleep(0.05)
    (card,) = app.approvals.pending(s["id"])
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert app.approvals.pending(s["id"]) == []
    row = app.db.one("SELECT status FROM approvals WHERE id=?", [card["id"]])
    assert row["status"] == "expired"


# --------------------------------------------------------------- recording length


def test_max_seconds_is_bounded_by_the_config():
    assert R._record_seconds({}, {"max_seconds": 600}) == 600
    assert R._record_seconds({"max_seconds": 12}, {"max_seconds": 600}) == 12
    for bad in (0, -1, 601):
        with pytest.raises(R.ReplayOpError):
            R._record_seconds({"max_seconds": bad}, {"max_seconds": 600})


async def test_a_new_recording_replaces_the_old_stop_timer(tmp_path):
    app = AppState(db_path=tmp_path / "w.db")
    s = app.store.create(folder=str(tmp_path), mode="ask")
    first = R._arm_record_limit(app, s, "rr-first0001", {"max_seconds": 600}, seconds=600)
    second = R._arm_record_limit(app, s, "rr-second001", {"max_seconds": 600}, seconds=30)
    await asyncio.sleep(0)
    assert first.cancelled() and not second.done()
    R._disarm_record_limit(s["id"])
    await asyncio.sleep(0)
    assert second.cancelled() and s["id"] not in R._WATCHDOGS


def test_the_gdw_server_outlives_the_cli_idle_limit(tmp_path):
    from gamedevworkstation.features.claude_cli import MCP_TOOL_TIMEOUT_MS
    from gamedevworkstation.features.gdw_mcp import SERVER, GdwMcp

    app = AppState(db_path=tmp_path / "g.db")
    app.listen_port = 8811
    cfg = GdwMcp(app).config_json("tok")["mcpServers"][SERVER]
    assert cfg["timeout"] == MCP_TOOL_TIMEOUT_MS > 300_000
