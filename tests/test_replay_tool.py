"""Tests for the unity tool replay ops (replay_install, record, replay, replay_verify,
replay_render) using FakeUnityBridge. Never touches real Unity.

Regressions covered here: record is routed to the live Editor only (H1), the approval class per
contract §7 (H2), the full ReplayReport v1 with an environment comparison (H3), validation limits
and run_id/archive/scene rules (M7) and the shared run_replay_op path for stop/status (H4)."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from gamedevworkstation.app import AppState
from gamedevworkstation.features import hooks as H
from gamedevworkstation.features import ladder as L
from gamedevworkstation.features import replay as R
from gamedevworkstation.features import unity_tool as UT
from gamedevworkstation.features.unity_bridge import OP_ROUTES, BridgeResult, FakeUnityBridge

GOLDEN = Path(__file__).parent / "fixtures" / "replay" / "golden_v1.gdwreplay"
RUN_ID = "rr-test0001"
REL_ARCHIVE = f"Logs/harness/replay/{RUN_ID}/run.gdwreplay"


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "u.db")
    H.install(a)
    L.install(a)
    UT.install(a)
    return a


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "Game"
    (d / "ProjectSettings").mkdir(parents=True)
    (d / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")
    (d / "Assets/Game").mkdir(parents=True)
    (d / "Assets/Game/Hit.cs").write_text("class Hit {}\n")
    (d / "Packages").mkdir()
    (d / "Packages/manifest.json").write_text(json.dumps({"dependencies": {}}))
    return d.resolve()


@pytest.fixture
def archive(proj):
    dest = proj / REL_ARCHIVE
    dest.parent.mkdir(parents=True)
    shutil.copyfile(GOLDEN, dest)
    return dest


def session(app, folder, mode="ask"):
    return app.store.create(folder=str(folder), mode=mode)


def run_dir(proj: Path, run_id: str = RUN_ID) -> Path:
    return proj / "Logs" / "harness" / "replay" / run_id


def report_of(proj: Path, run_id: str = RUN_ID) -> dict:
    return json.loads((run_dir(proj, run_id) / "report.json").read_text())


class TestReplayInstallOp:
    async def test_replay_install_op(self, app, proj):
        s = session(app, proj)
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay_install"})
        assert r.is_error is False
        assert b.calls[-1][0] == "replay_install"

    async def test_replay_install_in_plan_mode(self, app, proj):
        s = session(app, proj, mode="plan")
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay_install"})
        assert r.is_error is True
        assert "plan" in r.text.lower()


class TestRecordOp:
    async def test_record_routes_live_not_batch(self, app, proj):
        """H1: record is live-only and never the batch verification test."""
        s = session(app, proj)
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "record"})
        assert r.is_error is False
        assert any(c[0] == "replay:record" for c in b.calls)
        assert OP_ROUTES["record"] == ("mcp", "cli_live")
        assert not {"cli_batch", "raw_batch"} & set(OP_ROUTES["record"])

    async def test_record_default_run_id_is_contract_shaped(self, app, proj):
        s = session(app, proj)
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "record"})
        assert r.is_error is False
        ids = [p.name for p in (proj / "Logs/harness/replay").iterdir() if p.is_dir()]
        assert len(ids) == 1
        assert re.fullmatch(r"rr_[0-9a-f]{16}", ids[0]), ids[0]

    async def test_record_writes_no_report(self, app, proj):
        s = session(app, proj)
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "record"})
        run_id = json.loads((run_dir(proj, r.text.split('"run_id": "')[1].split('"')[0]) / "request.json")
                            .read_text())["run_id"]
        assert not (run_dir(proj, run_id) / "report.json").exists()

    async def test_record_refused_in_plan_mode(self, app, proj):
        s = session(app, proj, mode="plan")
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "record"})
        assert r.is_error is True

    async def test_record_rejects_caller_paths(self, app, proj):
        s = session(app, proj)
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "record", "replay_path": REL_ARCHIVE})
        assert r.is_error is True
        assert "replay_path" in r.text.lower()


class TestReplayOp:
    async def test_replay_op(self, app, proj, archive):
        s = session(app, proj)
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay", "replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.is_error is False
        assert any(c[0] == "replay:replay" for c in b.calls)

    async def test_replay_report_is_full_v1(self, app, proj, archive):
        """H3: the report carries every contract §2 field, not a four-field stub."""
        s = session(app, proj)
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay", "replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.is_error is False
        report = report_of(proj)
        for key in ("schema", "run_id", "request_digest", "replay_sha256", "header_sha256", "log_sha256",
                    "content_sha256", "route", "status", "environment", "environment_diff", "frames",
                    "ticks", "first_divergent_frame", "first_divergent_tick", "provider_id",
                    "expected_hash", "actual_hash", "missing_provider_ids", "extra_provider_ids",
                    "nearby_markers", "console", "artifacts", "message", "started_utc", "ended_utc"):
            assert key in report, key
        assert report["schema"] == "gdw.replay.report/1"
        assert report["status"] == "pass"
        assert report["frames"] == {"expected": 2, "compared": 2}
        assert report["console"]["errors"] == 0
        assert report["replay_sha256"] == R._read_archive(proj, {"replay_path": REL_ARCHIVE}, {})[0].sha256
        assert report["artifacts"]["archive"] == REL_ARCHIVE
        assert report["artifacts"]["report"] == f"Logs/harness/replay/{RUN_ID}/report.json"

    async def test_environment_diff_is_reported_but_never_refused(self, app, proj, archive):
        """Decision 1: environment differences are reported, never turned into a refusal."""
        s = session(app, proj)
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay", "replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.is_error is False
        report = report_of(proj)
        # The golden header records a packages-lock digest this fixture project doesn't have.
        assert "package_lock" in report["environment_diff"]
        assert report["environment"] == "differs"
        assert report["status"] == "pass"

    async def test_replay_requires_an_existing_archive(self, app, proj):
        s = session(app, proj)
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay", "run_id": RUN_ID})
        assert r.is_error is True
        assert not any(c[0].startswith("replay:replay") for c in b.calls)
        assert report_of(proj)["status"] == "error"

    async def test_scene_mismatch_is_incompatible_without_running(self, app, proj, archive):
        s = session(app, proj)
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay", "replay_path": REL_ARCHIVE, "run_id": RUN_ID,
                                     "scene": "Assets/Other/Scene.unity"})
        assert r.is_error is True
        assert not any(c[0].startswith("replay:replay") for c in b.calls)
        report = report_of(proj)
        assert report["status"] == "incompatible"
        assert "scene" in report["message"].lower()

    async def test_existing_unity_report_is_not_overwritten(self, app, proj, archive):
        own = {"schema": "gdw.replay.report/1", "run_id": RUN_ID, "status": "pass", "message": "unity"}
        run_dir(proj).mkdir(parents=True, exist_ok=True)
        (run_dir(proj) / "report.json").write_text(json.dumps(own))
        s = session(app, proj)
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        await UT.run_op(app, s, {"op": "replay", "replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert report_of(proj) == own


class TestVerifyOp:
    async def test_verify_without_capture_follows_test_consent_and_runs_in_plan_mode(self, app, proj, archive):
        """H2: verify without capture is a verify op; Plan only mode allows it."""
        s = session(app, proj, mode="plan")
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay_verify", "replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.is_error is False
        assert any(c[0] == "replay:verify" for c in b.calls)

    async def test_verify_with_capture_is_a_change(self, app, proj, archive):
        s = session(app, proj, mode="plan")
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay_verify", "replay_path": REL_ARCHIVE, "run_id": RUN_ID,
                                     "capture": {"formats": ["mp4"]}})
        assert r.is_error is True
        assert "plan" in r.text.lower()

    async def test_verify_records_replay_verified_evidence(self, app, proj, archive):
        log = proj / "Logs/harness/replay-verify.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('[HARNESS] REPLAY {"v":1,"run_id":"%s","event":"done","status":"pass",'
                       '"frame":2,"tick":3}\n' % RUN_ID)

        class WithLog(FakeUnityBridge):
            async def run_replay(self, session, op, request, **kw):
                self.calls.append((f"replay:{op}", session["id"], kw.get("consent")))
                return BridgeResult("pass", "replay verify ok", "fake",
                                    evidence={"replay_op": op, "log": str(log), "started_at": 1.0})

        app.extensions["unity_bridge"] = WithLog(app)
        s = session(app, proj)
        r = await UT.run_op(app, s, {"op": "replay_verify", "replay_path": REL_ARCHIVE, "run_id": RUN_ID,
                                     "subjects": ["M1-S02-AC1"]})
        assert r.is_error is False
        report = report_of(proj)
        assert report["status"] == "pass"
        assert report["log_sha256"] and report["replay_sha256"]
        rows = [row for row in app.extensions["ladder"].evidence(proj, levels=["L3"])
                if row["detail"].get("kind") == "replay_verified"]
        assert rows, "verify must record replay_verified evidence"
        assert rows[0]["observed"] == "tool"
        assert rows[0]["subjects"] == ["M1-S02-AC1"]
        assert rows[0]["detail"]["report"]["frames"]["expected"] == rows[0]["detail"]["report"]["frames"]["compared"]


class TestRenderOp:
    async def test_render_needs_capture(self, app, proj, archive):
        s = session(app, proj)
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay_render", "replay_path": REL_ARCHIVE, "run_id": RUN_ID})
        assert r.is_error is True
        assert "capture" in r.text.lower()
        assert not any(c[0] == "replay:render" for c in b.calls)

    async def test_render_op(self, app, proj, archive):
        s = session(app, proj)
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay_render", "replay_path": REL_ARCHIVE, "run_id": RUN_ID,
                                     "capture": {"formats": ["mp4"], "fps": 30}})
        assert r.is_error is False
        assert any(c[0] == "replay:render" for c in b.calls)

    async def test_render_refused_in_plan_mode(self, app, proj, archive):
        """H2: render needs change permission, so Plan only mode refuses it."""
        s = session(app, proj, mode="plan")
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        r = await UT.run_op(app, s, {"op": "replay_render", "replay_path": REL_ARCHIVE, "run_id": RUN_ID,
                                     "capture": {"formats": ["mp4"]}})
        assert r.is_error is True
        assert "plan" in r.text.lower()


class TestApprovalClasses:
    def test_contract_classes(self):
        """H2: one classification for the Plan gate and the consent gate."""
        assert UT.get_bridge.__module__  # bridge imported through the tool module
        from gamedevworkstation.features.unity_bridge import UnityBridge
        assert UnityBridge.op_class("record") == "change"
        assert UnityBridge.op_class("replay") == "change"
        assert UnityBridge.op_class("render") == "change"
        assert UnityBridge.op_class("verify") == "verify"
        assert UnityBridge.op_class("verify", capture=True) == "change"


class TestValidation:
    """M7: contract §1 limits are enforced, never clamped."""

    @pytest.fixture
    def cfg(self):
        return {}

    def check(self, op, args, cfg=None):
        return R._validated_request(op, args, replay_cfg=cfg or {})

    def bad(self, op, args, cfg=None):
        with pytest.raises(R.ReplayOpError):
            self.check(op, args, cfg)

    def test_fixed_dt_is_a_reduced_rational(self):
        req = self.check("record", {"fixed_dt": 0.5})
        assert req["fixed_dt"] == {"num": 1, "den": 2}
        assert self.check("record", {"fixed_dt": {"num": 1, "den": 60}})["fixed_dt"] == {"num": 1, "den": 60}
        self.bad("record", {"fixed_dt": {"num": 2, "den": 120}})  # must be reduced
        self.bad("record", {"fixed_dt": 0.0005})
        self.bad("record", {"fixed_dt": 1.5})
        self.bad("record", {"fixed_dt": {"num": 2, "den": 4}})

    def test_capture_limits(self):
        self.bad("render", {"run_id": RUN_ID})
        self.bad("render", {"run_id": RUN_ID, "capture": {"formats": []}})
        self.bad("render", {"run_id": RUN_ID, "capture": {"formats": ["mov"]}})
        self.bad("render", {"run_id": RUN_ID, "capture": {"formats": ["mp4", "mp4"]}})
        self.bad("render", {"run_id": RUN_ID, "capture": {"formats": ["mp4"], "fps": 61}})
        self.bad("render", {"run_id": RUN_ID, "capture": {"formats": ["mp4"], "fps": 0}})
        self.bad("render", {"run_id": RUN_ID, "capture": {"formats": ["mp4"], "width": 15}})
        self.bad("render", {"run_id": RUN_ID, "capture": {"formats": ["mp4"], "width": 17}})
        self.bad("render", {"run_id": RUN_ID, "capture": {"formats": ["mp4"], "height": 1082}})
        self.bad("render", {"run_id": RUN_ID, "capture": {"formats": ["mp4"], "unknown": 1}})
        ok = self.check("render", {"run_id": RUN_ID, "capture": {"formats": ["gif"], "width": 480}})
        assert ok["capture"]["width"] == 480
        assert ok["capture"]["backend"] == "auto"

    def test_capture_duration_uses_config(self):
        capture = {"formats": ["gif"], "end_frame_exclusive": 600, "fps": 60}
        self.bad("render", {"run_id": RUN_ID, "capture": capture}, {"gif_max_seconds": 8})
        self.check("render", {"run_id": RUN_ID, "capture": capture}, {"gif_max_seconds": 15})

    def test_scene_and_replay_path(self):
        self.bad("replay", {"run_id": RUN_ID, "scene": "Other/Scene.unity"})
        self.bad("replay", {"run_id": RUN_ID, "scene": "Assets/Other/Scene.txt"})
        self.bad("replay", {"run_id": RUN_ID, "scene": "/Assets/Other.unity"})
        self.bad("replay", {"run_id": RUN_ID, "replay_path": "/tmp/x.gdwreplay"})
        self.bad("replay", {"run_id": RUN_ID, "replay_path": "Logs/../x.gdwreplay"})
        self.bad("replay", {"run_id": RUN_ID, "replay_path": "Logs/x.zip"})
        ok = self.check("replay", {"run_id": RUN_ID})
        assert ok["replay_path"] == f"Logs/harness/replay/{RUN_ID}/run.gdwreplay"

    def test_subjects(self):
        self.bad("record", {"subjects": [str(i) for i in range(33)]})
        self.bad("record", {"subjects": ["x" * 129]})
        self.bad("record", {"subjects": ["a", "a"]})

    def test_seed_and_run_id(self):
        self.bad("record", {"seed": 2 ** 32})
        self.bad("record", {"seed": True})
        self.bad("record", {"run_id": "rr-bad id"})
        assert self.check("record", {"seed": 0})["seed"] == 0


class TestSharedRunReplayOp:
    """H4: run_replay_op is the one dispatcher for the tool and REST, including stop/status."""

    async def test_replay_ops_are_declared_locally(self):
        assert R.REPLAY_OPS == ("record", "stop", "status", "replay", "verify", "render")

    async def test_stop_and_status_need_only_a_run_id(self, app, proj):
        s = session(app, proj)
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        st = await R.run_replay_op(app, s, "status", {"run_id": RUN_ID})
        assert st.is_error is False
        assert "report: none" in st.text
        assert any(c[0] == "replay:status" for c in b.calls) is False  # no job: no live call

        stop = await R.run_replay_op(app, s, "stop", {"run_id": RUN_ID})
        assert stop.is_error is False
        assert "no running replay" in stop.text

    async def test_invalid_run_id_is_refused_for_stop_and_status(self, app, proj):
        s = session(app, proj)
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        for op in ("stop", "status"):
            r = await R.run_replay_op(app, s, op, {"run_id": "nope"})
            assert r.is_error is True
            assert "run_id" in r.text.lower()


class TestNotAUnityProject:
    async def test_replay_ops_refused_for_non_unity(self, app, tmp_path):
        d = tmp_path / "not-unity"
        d.mkdir()
        s = session(app, d)
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        for op in ("replay_install", "record", "replay", "replay_verify", "replay_render"):
            r = await UT.run_op(app, s, {"op": op, "replay_path": REL_ARCHIVE, "run_id": RUN_ID,
                                         "capture": {"formats": ["mp4"]}})
            assert r.is_error is True
            assert "Unity project" in r.text or "folder" in r.text.lower()


class _SpyBridge(__import__("gamedevworkstation.features.unity_bridge", fromlist=["UnityBridge"]).UnityBridge):
    """The real UnityBridge replay code with the route, MCP and unity.sh layers replaced by spies."""

    def __init__(self, app, mode):
        super().__init__(app)
        self._mode = mode
        self.gates: list[tuple] = []
        self.mcp_calls: list[tuple] = []
        self.raw_calls: list[tuple] = []

    async def _route(self, session, op):
        from gamedevworkstation.features.unity_bridge import EditorState
        return EditorState(self._mode, True, True, True), Path(session["folder"]).resolve()

    async def ensure_allowed(self, session, op, key, **kw):
        self.gates.append((op, key, self.op_class(op, None, capture=kw.get("capture", False))))
        return None

    async def _mcp(self, session, tool, args, consent, timeout):
        self.mcp_calls.append((tool, args))
        return True, '{"ok": true}'

    async def _raw(self, session, op, args, consent, **kw):
        self.raw_calls.append((op, args, kw.get("key"), kw.get("capture")))
        self.gates.append((op, kw.get("key"), self.op_class(op, None, capture=kw.get("capture", False))))
        return 0, "", "RESULT pass", "", 0.0


class TestRealBridgeRouting:
    """H1/H2 against the real bridge code: record is a live eval, never the batch verify test."""

    async def test_record_runs_replaycommands_start_live_with_change_gate(self, app, proj):
        b = app.extensions["unity_bridge"] = _SpyBridge(app, "mcp")
        r = await UT.run_op(app, session(app, proj), {"op": "record"})
        assert r.is_error is False
        assert [c[0] for c in b.mcp_calls] == ["execute_code"]
        assert "Gdw.Replay.Editor.ReplayCommands.Start(" in b.mcp_calls[0][1]["code"]
        assert not b.raw_calls
        assert b.gates == [("record", "record", "change")]

    async def test_record_refuses_a_batch_route(self, app, proj):
        b = app.extensions["unity_bridge"] = _SpyBridge(app, "raw_batch")
        r = await UT.run_op(app, session(app, proj), {"op": "record"})
        assert r.is_error is True
        assert not b.raw_calls and not b.mcp_calls

    async def test_replay_and_render_are_change_verify_follows_test_consent(self, app, proj, archive):
        b = app.extensions["unity_bridge"] = _SpyBridge(app, "raw_batch")
        s = session(app, proj)
        cap = {"formats": ["mp4"]}
        for tool_op, extra in (("replay", {}), ("replay_render", {"capture": cap}),
                               ("replay_verify", {}), ("replay_verify", {"capture": cap})):
            b.gates.clear()
            await UT.run_op(app, s, {"op": tool_op, "replay_path": REL_ARCHIVE, "run_id": RUN_ID, **extra})
            assert len(b.gates) == 1, tool_op
        classes = []
        for tool_op, extra in (("replay", {}), ("replay_render", {"capture": cap}),
                               ("replay_verify", {}), ("replay_verify", {"capture": cap})):
            b.gates.clear()
            await UT.run_op(app, s, {"op": tool_op, "replay_path": REL_ARCHIVE, "run_id": RUN_ID, **extra})
            classes.append(b.gates[0][2])
        assert classes == ["change", "change", "verify", "change"]
        assert all("LogMatchesCheckpoints" in " ".join(c[1]) for c in b.raw_calls)


class TestToolStopStatus:
    """H4: the unity tool exposes stop and status through run_replay_op."""

    async def test_replay_stop_and_status_ops(self, app, proj):
        s = session(app, proj)
        app.extensions["unity_bridge"] = FakeUnityBridge(app)
        st = await UT.run_op(app, s, {"op": "replay_status", "run_id": RUN_ID})
        assert st.is_error is False and "report: none" in st.text
        stop = await UT.run_op(app, s, {"op": "replay_stop", "run_id": RUN_ID})
        assert stop.is_error is False and "no running replay" in stop.text
        bad = await UT.run_op(app, s, {"op": "replay_stop", "run_id": "x"})
        assert bad.is_error is True


class TestReplayConfig:
    """L3: [unity.replay] values are read where they are enforced."""

    def test_partial_user_table_keeps_defaults(self, app):
        from gamedevworkstation.features import unity_cli as uc
        app.config.unity = {"replay": {"max_seconds": 5}}
        cfg = uc.unity_cfg(app)["replay"]
        assert cfg["max_seconds"] == 5 and cfg["max_archive_mb"] == 512

    async def test_record_stops_after_max_seconds(self, app, proj):
        b = app.extensions["unity_bridge"] = FakeUnityBridge(app)
        s = session(app, proj)
        task = R._arm_record_limit(app, s, "rr-limit001", {"max_seconds": 1})
        assert task is not None
        await task
        assert any(c[0] == "replay:stop" for c in b.calls)
        assert R._arm_record_limit(app, s, "rr-limit001", {"max_seconds": 0}) is None

    async def test_archive_limit_is_read(self, app, proj, archive):
        archive_obj, status, msg = R._read_archive(proj, {"replay_path": REL_ARCHIVE}, {"max_archive_mb": 0})
        assert archive_obj is not None  # 0 falls back to the format cap, never silently below it
