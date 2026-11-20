"""Render writes PNG frames in Unity, then GameDevWorkstation encodes them (com.gdw.replay 0.1.2).

Before 0.1.2 nothing called ReplayCapture and nothing ran the ffmpeg export, so a render "passed" and wrote
no media. Live recordings also failed verify: the input trace kept a frame marker for every Editor input
update (about 16 per game frame while the Editor had focus), and replay advanced on Editor updates too.
"""
import re
from pathlib import Path

from gamedevworkstation.features import replay, replay_media

TEMPLATES = Path(__file__).resolve().parents[1] / "skills" / "replay" / "templates" / "com.gdw.replay"


def _src(rel: str) -> str:
    return (TEMPLATES / rel).read_text(encoding="utf-8")


def _run_dir(tmp_path: Path, run_id: str = "rr_0123456789abcdef") -> Path:
    d = tmp_path / "Logs" / "harness" / "replay" / run_id
    d.mkdir(parents=True)
    return d


CAPTURE = {"formats": ["mp4", "gif"], "backend": "png", "fps": 60, "width": 1280, "height": 720, "start_frame": 0}


def test_no_capture_requested_means_no_export(tmp_path):
    _run_dir(tmp_path)
    assert replay._export_capture(tmp_path, "rr_0123456789abcdef", {"op": "render"}) is None
    assert replay._export_capture(tmp_path, "rr_0123456789abcdef", {"capture": {"formats": []}}) is None


def test_a_render_without_frames_is_reported_not_passed(tmp_path):
    _run_dir(tmp_path)
    out = replay._export_capture(tmp_path, "rr_0123456789abcdef", {"capture": CAPTURE})
    assert out == {"ok": False, "outputs": [], "error": "the render wrote no frames"}


def test_frames_are_encoded_with_the_requested_spec(tmp_path, monkeypatch):
    run = _run_dir(tmp_path)
    frames = run / "capture" / "frames"
    frames.mkdir(parents=True)
    for i in range(3):
        (frames / f"frame-{i:06d}.png").write_bytes(b"png")
    seen = {}

    def fake_execute(plan, **kw):
        seen["plan"] = plan
        for p in plan.outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"media")
        return {"ok": True, "results": [{"step": i, "output": p, "ok": True} for i, p in enumerate(plan.outputs)],
                "warnings": [], "verifications": []}

    monkeypatch.setattr(replay_media, "execute_steps", fake_execute)
    monkeypatch.setattr(replay_media, "_ffmpeg_paths", lambda *a, **k: ("ffmpeg", "ffprobe"))
    out = replay._export_capture(tmp_path, "rr_0123456789abcdef", {"capture": CAPTURE})

    assert out["ok"] is True and out["frames"] == 3 and out["error"] == ""
    assert [Path(p).name for p in out["outputs"]] == ["run.mp4", "run.gif"]
    assert all(p.startswith("Logs/harness/replay/rr_0123456789abcdef/exports/") for p in out["outputs"])
    assert seen["plan"].frames_dir == frames


def test_export_failure_keeps_the_ffmpeg_error(tmp_path, monkeypatch):
    run = _run_dir(tmp_path)
    (run / "capture" / "frames").mkdir(parents=True)
    (run / "capture" / "frames" / "frame-000000.png").write_bytes(b"png")
    monkeypatch.setattr(replay_media, "_ffmpeg_paths", lambda *a, **k: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(replay_media, "execute_steps", lambda plan, **kw: {
        "ok": False, "results": [{"step": 0, "output": plan.outputs[0], "ok": False, "error": "no encoder"}],
        "warnings": []})
    out = replay._export_capture(tmp_path, "rr_0123456789abcdef", {"capture": CAPTURE})
    assert out["ok"] is False and out["outputs"] == [] and out["error"] == "no encoder"
    text = replay._tool_output("render", "rr_0123456789abcdef", None, {"status": "pass", "message": "ok"}, out).text
    assert "Export failed: no encoder" in text


def test_the_verification_test_captures_frames_for_render_requests():
    test = _src("Tests/PlayMode/ReplayVerificationTests.cs")
    assert "ReplayCaptureHooks.Start(framesDir" in test
    assert "ReplayLoop.AfterCheckpoint = () => ReplayCaptureHooks.CaptureFrame()" in test
    assert re.search(r'Path\.Combine\([^;]*"capture", "frames"\)', test)
    assert "ReplayCaptureHooks.Start = Start;" in _src("Editor/ReplayCapture.cs")
    assert "AfterCheckpoint?.Invoke();" in _src("Runtime/ReplayLoop.cs")


def test_input_trace_keeps_only_the_replay_loops_own_frame_markers():
    adapter = _src("InputSystem/InputTraceAdapter.cs")
    assert "if (eventPtr.type == InputEventTrace.FrameMarkerEvent) return _inLoopUpdate;" in adapter
    # The replay controller only advances inside the loop's own input update.
    assert "_controller.paused = true;" in adapter
    assert adapter.count("RunLoopUpdate();") == 2


RUN = "rr-test0001"


def _tool_project(tmp_path, monkeypatch):
    import json
    import shutil

    from gamedevworkstation.app import AppState
    from gamedevworkstation.features import hooks as H
    from gamedevworkstation.features import ladder as L
    from gamedevworkstation.features import unity_tool as UT

    app = AppState(db_path=tmp_path / "u.db")
    H.install(app)
    L.install(app)
    UT.install(app)
    proj = tmp_path / "Game"
    (proj / "ProjectSettings").mkdir(parents=True)
    (proj / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n", encoding="utf-8")
    (proj / "Packages").mkdir()
    (proj / "Packages/manifest.json").write_text(json.dumps({"dependencies": {}}), encoding="utf-8")
    run_id = RUN
    run = proj / "Logs" / "harness" / "replay" / run_id
    run.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parent / "fixtures" / "replay" / "golden_v1.gdwreplay", run / "run.gdwreplay")
    frames = run / "capture" / "frames"
    frames.mkdir(parents=True)
    for i in range(2):
        (frames / f"frame-{i:06d}.png").write_bytes(b"png")
    monkeypatch.setattr(replay_media, "_ffmpeg_paths", lambda *a, **k: ("ffmpeg", "ffprobe"))

    def fake_execute(plan, **kw):
        for p in plan.outputs:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"media")
        return {"ok": True, "results": [{"step": i, "output": p, "ok": True} for i, p in enumerate(plan.outputs)],
                "warnings": []}

    monkeypatch.setattr(replay_media, "execute_steps", fake_execute)
    return app, UT, proj.resolve(), run


RENDER = {"op": "replay_render", "replay_path": f"Logs/harness/replay/{RUN}/run.gdwreplay", "run_id": RUN,
          "capture": {"formats": ["mp4", "gif"], "fps": 30}}


async def test_a_passing_render_through_the_tool_returns_the_export(tmp_path, monkeypatch):
    """The unity tool's replay_render runs the export after the batch run passes."""
    from gamedevworkstation.features.unity_bridge import FakeUnityBridge

    app, UT, proj, _run = _tool_project(tmp_path, monkeypatch)
    s = app.store.create(folder=str(proj), mode="ask")
    app.extensions["unity_bridge"] = FakeUnityBridge(app)
    r = await UT.run_op(app, s, dict(RENDER))
    assert r.is_error is False, r.text
    assert '"export"' in r.text and "run.gif" in r.text, r.text
    import json
    exports = json.loads((_run / "report.json").read_text(encoding="utf-8"))["artifacts"]["exports"]
    assert [Path(p).name for p in exports] == ["run.gif", "run.mp4"]


async def test_a_failed_render_isnt_reported_with_an_earlier_verify_report(tmp_path, monkeypatch):
    """A report.json left by an earlier verify of the same run must not stand in for this render's result."""
    import json
    import os

    from gamedevworkstation.features.unity_bridge import BridgeResult, FakeUnityBridge

    app, UT, proj, run = _tool_project(tmp_path, monkeypatch)
    stale = {"schema": "gdw.replay.report/1", "op": "verify", "status": "pass", "message": "1 tests passed"}
    (run / "report.json").write_text(json.dumps(stale), encoding="utf-8")
    os.utime(run / "report.json", (1_000_000_000, 1_000_000_000))

    class FailingRender(FakeUnityBridge):
        async def run_replay(self, session, op, request, *, consent=None, cancel=None):
            return BridgeResult("fail", "1 failing test of 1", "cli_batch", evidence={"replay_op": op})

    s = app.store.create(folder=str(proj), mode="ask")
    app.extensions["unity_bridge"] = FailingRender(app)
    r = await UT.run_op(app, s, dict(RENDER))
    assert not r.text.startswith("Replay render: pass"), r.text[:300]
    assert '"export"' not in r.text
    assert json.loads((run / "report.json").read_text(encoding="utf-8"))["op"] == "render"
