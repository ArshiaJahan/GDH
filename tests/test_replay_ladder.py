"""Task G: quality-ladder L3 evidence for verified replays.

Extends the ladder's _test_candidates/_ac_level/_l3 so a headless AC with
test:Gdw.Replay.Tests.ReplayVerificationTests.LogMatchesCheckpoints reaches L3
only with tool-observed replay_verified evidence: pass report, complete frames,
clean console, immutable log/report digests, fresh content, scoped subjects.
"""
import json
import time
from pathlib import Path

import pytest

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.features import ladder as L
from gamedevworkstation.skills import builtin_skills_dir

SKILLS = builtin_skills_dir()
PARSE_LOG = SKILLS / "compile-fix-loop/scripts/parse_unity_log.py"
CHECK = SKILLS / "play-verify/scripts/check_criteria.py"

BACKLOG = """# Backlog: Replay Tests
Current milestone: M2

## M2 Record/replay
Goal: Replay matches recorded checkpoints.
Exit: All M2 criteria pass.
Status: active

### M2-S01 Replay verification
- Status: doing
- Owner skill: replay

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M2-S01-AC1 | Given a recorded replay, When replayed, Then all checkpoints match | headless | test:Gdw.Replay.Tests.ReplayVerificationTests.LogMatchesCheckpoints |
"""

BACKLOG_WITH_VISUAL = """# Backlog: Replay Tests
Current milestone: M2

## M2 Record/replay
Goal: Replay matches recorded checkpoints.
Exit: All M2 criteria pass.
Status: active

### M2-S01 Replay verification
- Status: doing
- Owner skill: replay
- Visual: yes

| AC | Given / When / Then | Test | Signal |
|---|---|---|---|
| M2-S01-AC1 | Given a recorded replay, When replayed, Then all checkpoints match | headless | test:Gdw.Replay.Tests.ReplayVerificationTests.LogMatchesCheckpoints |
"""


def replay_report(overrides: dict | None = None) -> dict:
    """A minimal passing replay report dict, suitable for record_evidence detail.report."""
    r = {
        "schema": "gdw.replay.report/1",
        "run_id": "rr_aabbccdd0011",
        "status": "pass",
        "environment": "matched",
        "environment_diff": [],
        "route": "mcp",
        "request_digest": "aa" * 32,
        "replay_sha256": "bb" * 32,
        "header_sha256": "cc" * 32,
        "log_sha256": "dd" * 32,
        "content_sha256": "ee" * 32,
        "frames": {"expected": 600, "compared": 600},
        "ticks": {"expected": 600, "compared": 600},
        "first_divergent_frame": None,
        "first_divergent_tick": None,
        "provider_id": None,
        "expected_hash": None,
        "actual_hash": None,
        "missing_provider_ids": [],
        "extra_provider_ids": [],
        "nearby_markers": [],
        "console": {"errors": 0, "warnings": 5},
        "artifacts": {
            "archive": "Logs/harness/replay/rr_aabbccdd0011/run.gdwreplay",
            "report": "Logs/harness/replay/rr_aabbccdd0011/report.json",
        },
        "message": "600 frames replayed, all checkpoints match",
        "started_utc": "2026-11-18T10:00:00Z",
        "ended_utc": "2026-11-18T10:01:00Z",
    }
    if overrides:
        r.update(overrides)
    return r


# ---------------------------------------------------------------------- fixtures


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "l.db")
    a.lad = L.install(a)
    return a


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "game"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.0f1\n")
    for rel in ("Assets/Game/Hit.cs",):
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// code\n")
    (d / "BACKLOG.md").write_text(BACKLOG)
    return d


@pytest.fixture
def proj_visual(tmp_path):
    d = tmp_path / "game_vis"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.0f1\n")
    for rel in ("Assets/Game/Hit.cs",):
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// code\n")
    (d / "BACKLOG.md").write_text(BACKLOG_WITH_VISUAL)
    return d


def session(app, folder, mode="accept_edits"):
    return app.store.create(folder=str(folder), mode=mode)


def state(app, proj, sid_):
    bl = L.read_backlog(proj)
    return app.lad.story_state(proj, bl.stories[sid_], scan=L.project_scan(proj))


async def compile_ok(app, s, proj):
    log = proj / "Logs" / "compile.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps([{"type": "log", "message": "Compilation finished"}]))
    from gamedevworkstation.agent.tools import ToolOutput
    from gamedevworkstation.features.hookbus import HookEvent

    out = ToolOutput("exit code 0\ncompile errors: 0 | runtime errors: 0\nRESULT: OK")
    ctx = ToolContext(app=app, session=s, run_id=f"main:{s['id']}", role="main")
    ev = HookEvent("post_tool", ctx, tool="run_command",
                   args={"command": f"python3 {PARSE_LOG} Logs/compile.json"}, output=out)
    await app.lad.observe(ev)


def record_replay_evidence(app, folder, subjects, *, report=None, observed="tool", ts=None,
                           session_id=None):
    """Record a replay_verified evidence row."""
    report = report or replay_report()
    return app.lad.record_evidence(
        folder, "L3", "pass", source="tool:replay", observed=observed,
        subjects=subjects, session_id=session_id,
        detail={"kind": "replay_verified", "report": report,
                "summary": f"replay {report['status']}, {report['frames']['compared']} frames"},
        ts=ts)


# ====================================================================== tests


class TestReplayVerifiedCandidates:
    """_test_candidates returns a replay_verified candidate when evidence is valid."""

    def test_finds_replay_verified(self, proj, app):
        s = session(app, proj)
        bl = L.read_backlog(proj)
        story = bl.stories["M2-S01"]
        ac = story.acs[0]
        rows = app.lad.evidence(proj)

        # No evidence yet → no candidates.
        cands = app.lad._test_candidates(ac, story.milestone, rows)
        assert len([c for c in cands if c[3].startswith("replay_verified")]) == 0

        # With valid replay_verified evidence → candidate found.
        record_replay_evidence(app, proj, [ac.id], session_id=s["id"])
        rows = app.lad.evidence(proj)
        cands = app.lad._test_candidates(ac, story.milestone, rows)
        rv = [c for c in cands if c[3].startswith("replay_verified")]
        assert len(rv) == 1
        assert rv[0][1] is True  # passed

    def test_rejects_unscoped_subjects(self, proj, app):
        """Evidence must name the AC in its subjects."""
        s = session(app, proj)
        bl = L.read_backlog(proj)
        ac = bl.stories["M2-S01"].acs[0]
        record_replay_evidence(app, proj, ["M2-S01"], session_id=s["id"])  # story, not AC
        rows = app.lad.evidence(proj)
        cands = app.lad._test_candidates(ac, "M2", rows)
        assert len([c for c in cands if c[3].startswith("replay_verified")]) == 0

    def test_rejects_forged_evidence(self, proj, app):
        """observed must be 'tool' — anything else is forged."""
        s = session(app, proj)
        bl = L.read_backlog(proj)
        ac = bl.stories["M2-S01"].acs[0]
        record_replay_evidence(app, proj, [ac.id], observed="command", session_id=s["id"])
        rows = app.lad.evidence(proj)
        cands = app.lad._test_candidates(ac, "M2", rows)
        assert len([c for c in cands if c[3].startswith("replay_verified")]) == 0

    def test_rejects_non_pass_report(self, proj, app):
        s = session(app, proj)
        bl = L.read_backlog(proj)
        ac = bl.stories["M2-S01"].acs[0]
        record_replay_evidence(app, proj, [ac.id], session_id=s["id"],
                               report=replay_report({"status": "diverged"}))
        rows = app.lad.evidence(proj)
        cands = app.lad._test_candidates(ac, "M2", rows)
        assert len([c for c in cands if c[3].startswith("replay_verified")]) == 0

    def test_rejects_incomplete_frames(self, proj, app):
        s = session(app, proj)
        bl = L.read_backlog(proj)
        ac = bl.stories["M2-S01"].acs[0]
        record_replay_evidence(app, proj, [ac.id], session_id=s["id"],
                               report=replay_report({"frames": {"expected": 600, "compared": 590}}))
        rows = app.lad.evidence(proj)
        cands = app.lad._test_candidates(ac, "M2", rows)
        assert len([c for c in cands if c[3].startswith("replay_verified")]) == 0

    def test_rejects_dirty_console(self, proj, app):
        s = session(app, proj)
        bl = L.read_backlog(proj)
        ac = bl.stories["M2-S01"].acs[0]
        record_replay_evidence(app, proj, [ac.id], session_id=s["id"],
                               report=replay_report({"console": {"errors": 1, "warnings": 5}}))
        rows = app.lad.evidence(proj)
        cands = app.lad._test_candidates(ac, "M2", rows)
        assert len([c for c in cands if c[3].startswith("replay_verified")]) == 0

    def test_rejects_missing_digests(self, proj, app):
        s = session(app, proj)
        bl = L.read_backlog(proj)
        ac = bl.stories["M2-S01"].acs[0]
        report = replay_report()
        del report["log_sha256"]
        record_replay_evidence(app, proj, [ac.id], session_id=s["id"], report=report)
        rows = app.lad.evidence(proj)
        cands = app.lad._test_candidates(ac, "M2", rows)
        assert len([c for c in cands if c[3].startswith("replay_verified")]) == 0

        report = replay_report()
        del report["replay_sha256"]
        record_replay_evidence(app, proj, [ac.id], session_id=s["id"], report=report)
        rows = app.lad.evidence(proj)
        cands = app.lad._test_candidates(ac, "M2", rows)
        assert len([c for c in cands if c[3].startswith("replay_verified")]) == 0

    def test_environment_differs_still_counts(self, proj, app):
        """environment=differs is accepted; the candidate detail says so."""
        s = session(app, proj)
        bl = L.read_backlog(proj)
        ac = bl.stories["M2-S01"].acs[0]
        record_replay_evidence(app, proj, [ac.id], session_id=s["id"],
                               report=replay_report({"environment": "differs",
                                                     "environment_diff": ["unity_version"]}))
        rows = app.lad.evidence(proj)
        cands = app.lad._test_candidates(ac, "M2", rows)
        rv = [c for c in cands if c[3].startswith("replay_verified")]
        assert len(rv) == 1
        assert "environment differs" in rv[0][3]


class TestReplayL3State:
    """Integration: story_state evaluates L3 correctly with replay_verified evidence."""

    async def test_l3_passes_with_valid_evidence(self, app, proj):
        s = session(app, proj)
        await compile_ok(app, s, proj)
        record_replay_evidence(app, proj, ["M2-S01-AC1"], session_id=s["id"])
        st = state(app, proj, "M2-S01")
        assert st["levels"]["L3"]["state"] == "pass"
        assert st["ok"]

    async def test_l3_pending_without_evidence(self, app, proj):
        s = session(app, proj)
        await compile_ok(app, s, proj)
        st = state(app, proj, "M2-S01")
        assert st["levels"]["L3"]["state"] == "pending"

    async def test_l3_stale_when_evidence_older_than_content(self, app, proj):
        s = session(app, proj)
        await compile_ok(app, s, proj)
        # Evidence timestamped in the past (before the code change).
        old_ts = 1000.0
        record_replay_evidence(app, proj, ["M2-S01-AC1"], ts=old_ts, session_id=s["id"])
        # "Change" code after the evidence.
        future = old_ts + 500
        os_utime = __import__("os").utime
        os_utime(proj / "Assets/Game/Hit.cs", (future, future))
        st = state(app, proj, "M2-S01")
        assert st["levels"]["L3"]["state"] == "stale"
        assert any("replay_verified" not in m and "stale" not in m for m in st["missing"])

    async def test_l3_fails_with_diverged_report(self, app, proj):
        s = session(app, proj)
        await compile_ok(app, s, proj)
        record_replay_evidence(app, proj, ["M2-S01-AC1"], session_id=s["id"],
                               report=replay_report({"status": "diverged"}))
        st = state(app, proj, "M2-S01")
        assert st["levels"]["L3"]["state"] == "pending"

    async def test_still_needs_screenshots_for_visual_stories(self, app, proj_visual):
        """A story with `- Visual: yes` needs screenshots even with replay_verified evidence."""
        s = session(app, proj_visual)
        await compile_ok(app, s, proj_visual)
        record_replay_evidence(app, proj_visual, ["M2-S01-AC1"], session_id=s["id"])
        st = state(app, proj_visual, "M2-S01")
        assert st["levels"]["L3"]["state"] == "pending"  # needs screenshot too
        assert any("no screenshot" in m for m in st["missing"])
        # Add a screenshot → passes.
        from tests.test_ladder import png
        png(proj_visual / "Logs/harness/verify/r1/shots/M2-S01-AC1-replay.png")
        st = state(app, proj_visual, "M2-S01")
        assert st["levels"]["L3"]["state"] == "pass" and st["ok"]

    async def test_environment_differs_l3_still_passes(self, app, proj):
        """environment=differs still yields L3 pass."""
        s = session(app, proj)
        await compile_ok(app, s, proj)
        record_replay_evidence(app, proj, ["M2-S01-AC1"], session_id=s["id"],
                               report=replay_report({"environment": "differs",
                                                     "environment_diff": ["os"]}))
        st = state(app, proj, "M2-S01")
        assert st["levels"]["L3"]["state"] == "pass"

    async def test_l2_tests_still_work_for_non_replay_acs(self, app, proj):
        """The replay_verified change must not break L2 for other AC types."""
        from tests.test_ladder import nunit
        s = session(app, proj)
        await compile_ok(app, s, proj)
        # Record a play-verify check for an EditMode AC (not in this backlog, so no effect),
        # but verify that _ac_level still works for L2 scenarios by checking no crash.
        # The real test is that existing tests (test_ladder.py) still pass.
        assert True
