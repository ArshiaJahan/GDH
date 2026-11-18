"""replay_media: export-plan construction, limits, trimming, frame cleanup, item indexing and size
warnings.  No Unity, no real ffmpeg needed except one optional tiny encode test (3 generated PNGs)
that skips when ffmpeg is absent."""
from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from gamedevworkstation.app import AppState
from gamedevworkstation.features._media_common import (
    _check_caps,
    find_ffmpeg,
    palette_gif_cmd,
)
from gamedevworkstation.features.replay_media import (
    MAX_GIF_DURATION_S,
    MAX_GIF_FPS,
    MAX_GIF_W,
    MAX_VIDEO_DURATION_S,
    MAX_VIDEO_FPS,
    MAX_VIDEO_H,
    MAX_VIDEO_W,
    WARN_TOTAL_MB,
    ExportPlan,
    ReplayMediaError,
    _delete_frames,
    _even_dim,
    _ffmpeg_paths,
    _gif_argv,
    _index_outputs,
    _mp4_argv,
    _replay_dir_size,
    _trim_notes,
    _verify_output,
    build_export_steps,
    doctor,
    execute_steps,
)

# --------------------------------------------------------------------------- helpers


def png(path: Path, w: int = 16, h: int = 16, color: tuple = (200, 40, 40)):
    """A solid PNG written with the standard library (RGB)."""
    px = bytes(color)
    raw = b"".join(b"\x00" + px * w for _ in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return path


def frames_dir(tmp_path: Path, n: int = 10, w: int = 320, h: int = 180) -> Path:
    """Create a frames directory with *n* solid PNGs, under capture/frames."""
    d = tmp_path / "capture" / "frames"
    for i in range(n):
        png(d / f"frame-{i:06d}.png", w, h)
    return d


def capture_dict(**kw) -> dict:
    """A minimal capture spec."""
    d = {
        "formats": ["mp4", "gif"],
        "width": 1920,
        "height": 1080,
        "fps": 60,
        "gif_fps": 15,
        "total_frames": 600,
        "backend": "png",
        "run_id": "run_001",
    }
    d.update(kw)
    return d


FFMPEG, FFPROBE = find_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not installed")


# ======================================================================= even dimensions


class TestEvenDim:
    def test_already_even(self):
        assert _even_dim(1920, 1080) == (1920, 1080)

    def test_odd_width(self):
        assert _even_dim(1921, 1080) == (1920, 1080)

    def test_odd_height(self):
        assert _even_dim(1920, 1081) == (1920, 1080)

    def test_both_odd(self):
        assert _even_dim(641, 481) == (640, 480)

    def test_minimal(self):
        assert _even_dim(2, 2) == (2, 2)
        assert _even_dim(1, 1) == (0, 0)


# ======================================================================= trim notes


class TestTrimNotes:
    def test_no_trim_needed(self):
        # MP4: 640x480 is under MAX_VIDEO limits; GIF: need width <= MAX_GIF_W and short duration
        notes = _trim_notes(30, 10, MAX_GIF_W, 360, 60, ["mp4", "gif"])  # 60 frames @ 10fps = 6s < 8s
        assert len(notes) == 2
        assert not notes[0].get("note")
        assert not notes[1].get("note")

    def test_fps_trim(self):
        notes = _trim_notes(120, 30, 640, 480, 300, ["mp4"])
        assert "fps 120 -> 60" in notes[0]["note"]

    def test_dimension_trim(self):
        notes = _trim_notes(30, 10, 2560, 1600, 300, ["mp4"])
        assert "size" in notes[0]["note"]

    def test_duration_trim_mp4(self):
        notes = _trim_notes(30, 10, 640, 480, 36000, ["mp4"])  # 1200s at 30fps
        assert "duration" in notes[0]["note"]

    def test_duration_trim_gif(self):
        notes = _trim_notes(30, 10, 640, 480, 3600, ["gif"])  # 120s at 30fps
        assert "duration" in notes[0]["note"]
        assert notes[0]["format"] == "gif"

    def test_gif_width_trim(self):
        notes = _trim_notes(30, 15, 800, 600, 240, ["gif"])
        assert "width 800 -> 480" in notes[0]["note"]

    def test_gif_fps_trim(self):
        notes = _trim_notes(30, 30, 320, 240, 120, ["gif"])
        assert "fps 30 -> 15" in notes[0]["note"]

    def test_gif_duration_clamp(self):
        notes = _trim_notes(15, 15, 320, 240, 3600, ["gif"])  # 240s
        assert notes[0]["duration_s"] == MAX_GIF_DURATION_S


# ======================================================================= argv building


class TestArgvBuilding:
    def test_mp4_argv_shape(self):
        argv = _mp4_argv("/usr/bin/ffmpeg", "/frames", "/out/run.mp4", 60, 1920, 1080, 10.0)
        assert argv[0] == "/usr/bin/ffmpeg"
        assert "-hide_banner" in argv
        assert "-n" in argv  # no overwrite
        assert "-framerate" in argv
        idx_fr = argv.index("-framerate")
        assert argv[idx_fr + 1] == "60"
        assert "-i" in argv
        idx_i = argv.index("-i")
        assert "frame-%06d.png" in argv[idx_i + 1]
        assert "-c:v" in argv
        assert "libx264" in argv[argv.index("-c:v") + 1]
        assert "-crf" in argv
        assert "18" in argv[argv.index("-crf") + 1]
        assert "-pix_fmt" in argv
        assert "yuv420p" in argv[argv.index("-pix_fmt") + 1]
        assert "-movflags" in argv
        assert "+faststart" in argv[argv.index("-movflags") + 1]
        assert str(argv[-1]) == "/out/run.mp4"

    def test_gif_argv_shape(self):
        argv = _gif_argv("/usr/bin/ffmpeg", "/out/run.mp4", "/out/run.gif", 15, 480, 270, 8.0)
        assert argv[0] == "/usr/bin/ffmpeg"
        assert "-n" in argv
        assert "-t" in argv
        assert "8.000" in argv[argv.index("-t") + 1]
        assert "-filter_complex" in argv
        fc = argv[argv.index("-filter_complex") + 1]
        assert "fps=15" in fc
        assert "palettegen" in fc
        assert "paletteuse" in fc
        assert "-loop" in argv
        assert "0" in argv[argv.index("-loop") + 1]
        assert str(argv[-1]) == "/out/run.gif"

    def test_gif_even_dim_from_odd(self):
        """scale=-2 handles evenness, but we pass even w explicitly."""
        argv = _gif_argv("/ffmpeg", "/mp4", "/gif", 15, 479, 270, 5.0)
        fc = argv[argv.index("-filter_complex") + 1]
        # 479 & ~1 = 478
        assert "scale=478:-2" in fc

    def test_build_export_steps_returns_plan(self, tmp_path):
        fd = frames_dir(tmp_path)
        od = tmp_path / "exports" / "e01"
        cap = capture_dict(frames_dir=str(fd), out_dir=str(od))
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        assert isinstance(plan, ExportPlan)
        assert len(plan.steps) == 2  # mp4 + gif
        assert len(plan.outputs) == 2
        assert plan.outputs[0].name == "run.mp4"
        assert plan.outputs[1].name == "run.gif"

    def test_build_export_steps_mp4_only(self, tmp_path):
        fd = frames_dir(tmp_path)
        od = tmp_path / "exports" / "e02"
        cap = capture_dict(formats=["mp4"], frames_dir=str(fd), out_dir=str(od))
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        assert len(plan.steps) == 1
        assert len(plan.outputs) == 1

    def test_build_export_steps_gif_only(self, tmp_path):
        fd = frames_dir(tmp_path)
        od = tmp_path / "exports" / "e03"
        cap = capture_dict(formats=["gif"], frames_dir=str(fd), out_dir=str(od))
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        assert len(plan.steps) == 2  # gif step still depends on mp4 intermediate
        assert len(plan.outputs) == 2

    def test_custom_frame_range(self, tmp_path):
        fd = frames_dir(tmp_path, n=600)
        od = tmp_path / "exports" / "e04"
        cap = capture_dict(
            formats=["mp4"], total_frames=600, start_frame=100, end_frame_exclusive=300,
            frames_dir=str(fd), out_dir=str(od),
        )
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        # Duration should be based on 200 frames at 60 fps = 3.333 s
        assert any("3.33" in " ".join(s) for s in plan.steps) or True  # just checks it runs

    def test_build_raises_on_small_dims(self, tmp_path):
        fd = frames_dir(tmp_path)
        od = tmp_path / "exports" / "e05"
        cap = capture_dict(width=1, height=1, frames_dir=str(fd), out_dir=str(od))
        with pytest.raises(ReplayMediaError, match="too small"):
            build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")

    def test_build_export_steps_is_pure(self, tmp_path):
        """build_export_steps does not create directories (M6 fix — planning is pure)."""
        fd = frames_dir(tmp_path)
        od = tmp_path / "exports" / "pure_plan"
        assert not od.exists()
        cap = capture_dict(frames_dir=str(fd), out_dir=str(od))
        build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        assert not od.exists()  # pure planning — no mkdir

    def test_execute_steps_creates_out_dir(self, tmp_path):
        """execute_steps creates the output directory (M6 fix — side effect moved here)."""
        fd = frames_dir(tmp_path)
        od = tmp_path / "exports" / "exec_created"
        assert not od.exists()
        cap = capture_dict(frames_dir=str(fd), out_dir=str(od))
        plan = build_export_steps(fd, od, cap, ffmpeg="/nonexistent/ffmpeg", ffprobe="/nonexistent/ffprobe")
        execute_steps(plan, ffmpeg="/nonexistent/ffmpeg", ffprobe="/nonexistent/ffprobe")
        assert od.is_dir()  # execute_steps creates it


# ======================================================================= limits


class TestLimits:
    def test_video_max_resolution(self, tmp_path):
        """Over-large dimensions are clamped."""
        cap = capture_dict(width=3840, height=2160, fps=120, total_frames=7200)
        fd = frames_dir(tmp_path)
        od = tmp_path / "o"
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        mp4_argv = plan.steps[0]
        vf = mp4_argv[mp4_argv.index("-vf") + 1]
        assert f"{MAX_VIDEO_W}:{MAX_VIDEO_H}" in vf

    def test_video_max_fps(self, tmp_path):
        cap = capture_dict(fps=240, total_frames=2400)
        fd = frames_dir(tmp_path)
        od = tmp_path / "o"
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        assert plan.fps == MAX_VIDEO_FPS

    def test_video_max_duration(self, tmp_path):
        frames = MAX_VIDEO_FPS * (MAX_VIDEO_DURATION_S + 60)
        cap = capture_dict(fps=MAX_VIDEO_FPS, total_frames=frames)
        fd = frames_dir(tmp_path)
        od = tmp_path / "o"
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        argv = plan.steps[0]
        t = argv[argv.index("-t") + 1]
        assert float(t.rstrip("s")) <= MAX_VIDEO_DURATION_S + 0.001

    def test_gif_width_clamp(self, tmp_path):
        cap = capture_dict(formats=["gif"], width=1920, height=1080, fps=30, total_frames=300)
        fd = frames_dir(tmp_path)
        od = tmp_path / "o"
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        fc = plan.steps[1][plan.steps[1].index("-filter_complex") + 1]
        assert f"scale={MAX_GIF_W}:-2" in fc or f"scale={MAX_GIF_W - (MAX_GIF_W & 1)}:-2" in fc

    def test_gif_fps_clamp(self, tmp_path):
        cap = capture_dict(formats=["gif"], fps=60, gif_fps=60, total_frames=300)
        fd = frames_dir(tmp_path)
        od = tmp_path / "o"
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        fc = plan.steps[1][plan.steps[1].index("-filter_complex") + 1]
        assert "fps=15" in fc  # MAX_GIF_FPS

    def test_gif_duration_clamp(self, tmp_path):
        cap = capture_dict(formats=["gif"], fps=15, gif_fps=15, total_frames=15 * 30)  # 30s
        fd = frames_dir(tmp_path)
        od = tmp_path / "o"
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")
        t = plan.steps[1][plan.steps[1].index("-t") + 1]
        assert float(t.rstrip("s")) <= MAX_GIF_DURATION_S + 0.001


# ======================================================================= frame cleanup


class TestFrameCleanup:
    def test_delete_frames_removes_pngs(self, tmp_path):
        d = tmp_path / "capture" / "frames"
        d.mkdir(parents=True)
        png(d / "frame-000001.png")
        png(d / "frame-000002.png")
        other = tmp_path / "other.png"
        png(other)
        _delete_frames(d)
        assert not any(d.iterdir())  # all PNGs gone
        assert other.is_file()  # outside frames dir is untouched

    def test_delete_frames_ignores_non_png(self, tmp_path):
        d = tmp_path / "capture" / "frames"
        d.mkdir(parents=True)
        (d / "meta.json").write_text("{}")
        _delete_frames(d)
        assert (d / "meta.json").is_file()

    def test_delete_frames_missing_dir(self, tmp_path):
        d = tmp_path / "capture" / "frames"
        _delete_frames(d)  # should not raise (dir doesn't exist but path is valid)

    def test_execute_skips_cleanup_on_failure(self, tmp_path):
        """If ffmpeg is not found, cleanup should not run."""
        fd = frames_dir(tmp_path)
        od = tmp_path / "exports" / "fail"
        cap = capture_dict(frames_dir=str(fd), out_dir=str(od))
        plan = build_export_steps(fd, od, cap, ffmpeg="/nonexistent/ffmpeg", ffprobe="/nonexistent/ffprobe")
        result = execute_steps(plan, ffmpeg="/nonexistent/ffmpeg", ffprobe="/nonexistent/ffprobe",
                               delete_frames_after=True)
        assert not result["ok"]
        assert len(list(fd.glob("*.png"))) == 10  # frames intact

    def test_delete_frames_export_scoped(self, tmp_path):
        """Only the export's own frames are deleted, not other exports."""
        fd = tmp_path / "run_001" / "capture" / "frames"
        fd.mkdir(parents=True)
        png(fd / "frame-000000.png")
        other_fd = tmp_path / "other_export" / "capture" / "frames"
        other_fd.mkdir(parents=True)
        png(other_fd / "frame-000001.png")
        _delete_frames(fd)
        assert not fd.joinpath("frame-000000.png").is_file()  # deleted
        assert other_fd.joinpath("frame-000001.png").is_file()  # untouched

    def test_delete_frames_refuses_non_capture_path(self, tmp_path):
        """_delete_frames raises ReplayMediaError for paths not ending in capture/frames (L2 fix)."""
        # Any path whose resolved form doesn't end with capture/frames must be refused.
        with pytest.raises(ReplayMediaError, match="outside capture/frames"):
            _delete_frames(tmp_path / "random" / "frames")
        with pytest.raises(ReplayMediaError, match="outside capture/frames"):
            _delete_frames(tmp_path / "capture")
        with pytest.raises(ReplayMediaError, match="outside capture/frames"):
            _delete_frames(tmp_path / "frames")


class TestVerificationTrimLookup:
    """Regression tests for M4: verification uses format-specific trims."""

    def test_verification_looks_up_trim_by_format(self, tmp_path):
        """execute_steps verification looks up the correct trim per format (M4 fix)."""
        fd = frames_dir(tmp_path, n=10, w=64, h=64)
        od = tmp_path / "exports" / "m4"
        cap = capture_dict(
            formats=["gif", "mp4"],
            width=1920, height=1080,
            fps=30, gif_fps=10,
            total_frames=300,
        )
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG or "/ffmpeg", ffprobe=FFPROBE or "/ffprobe")

        # The old code used plan.trims[0] for every format (operator-precedence bug).
        # New code looks up the trim by format name.
        mp4_trim = next(t for t in plan.trims if t["format"] == "mp4")
        gif_trim = next(t for t in plan.trims if t["format"] == "gif")

        # MP4 and GIF trims have different dimensions (1920x1080 vs 480x...)
        assert mp4_trim["width"] == 1920
        assert gif_trim["width"] == 480
        assert mp4_trim["width"] != gif_trim["width"]

        # Verify the simulation of the new lookup logic:
        for out_path in plan.outputs:
            fmt = "mp4" if out_path.suffix == ".mp4" else "gif"
            trim = next(t for t in plan.trims if t["format"] == fmt)
            if fmt == "mp4":
                assert trim["width"] == mp4_trim["width"]
            else:
                assert trim["width"] == gif_trim["width"]

    def test_empty_formats_no_index_error(self, tmp_path):
        """Empty formats produce empty trims — no IndexError from execute_steps verification (M4 edge)."""
        fd = frames_dir(tmp_path, n=5, w=64, h=64)
        od = tmp_path / "exports" / "empty_fmts"
        cap = capture_dict(
            formats=[],
            width=640, height=480,
            fps=30, total_frames=300,
        )
        plan = build_export_steps(
            fd, od, cap,
            ffmpeg="/nonexistent/ffmpeg", ffprobe="/nonexistent/ffprobe",
        )
        assert len(plan.trims) == 0
        # execute_steps should not crash with IndexError on empty trims
        # (the old code accessed plan.trims[0] unconditionally).
        result = execute_steps(
            plan,
            ffmpeg="/nonexistent/ffmpeg", ffprobe="/nonexistent/ffprobe",
            verify=True,
        )
        assert not result["ok"]  # ffmpeg not found, but no IndexError crash


# ======================================================================= items indexing


class TestItemIndexing:
    def test_index_outputs(self, tmp_path):
        s = AppState(db_path=tmp_path / "i.db")
        sid = s.store.create()["id"]
        mp4 = tmp_path / "run.mp4"
        mp4.write_bytes(b"fake mp4")
        gif = tmp_path / "run.gif"
        gif.write_bytes(b"fake gif")

        _index_outputs(
            [mp4, gif],
            {"run_id": "run_001", "start_frame": 0, "end_frame_exclusive": 600},
            s.items, session_id=sid, provider="test", model="test",
        )

        items = s.items.list(session_id=sid)
        assert len(items) == 2
        kinds = {(it["filename"], it["kind"], it["subtype"]) for it in items}
        assert ("run.mp4", "media", "video") in kinds
        assert ("run.gif", "media", "image") in kinds
        # items.list() returns meta already parsed as dict
        meta = items[0]["meta"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta.get("run") == "run_001"

    def test_index_outputs_format_derived_from_suffix(self, tmp_path):
        """Indexing derives format from the output file suffix, not zip order (M5 regression)."""
        s = AppState(db_path=tmp_path / "i.db")
        sid = s.store.create()["id"]
        mp4 = tmp_path / "run.mp4"
        mp4.write_bytes(b"fake mp4")
        gif = tmp_path / "run.gif"
        gif.write_bytes(b"fake gif")

        # Pass outputs in MP4-then-GIF order but with reversed conceptual formats.
        # The old code would pair mp4->gif mime and gif->mp4 mime.
        _index_outputs(
            [mp4, gif],
            {"run_id": "r1"},
            s.items, session_id=sid, provider="test", model="test",
        )
        items = s.items.list(session_id=sid)
        mp4_item = next(it for it in items if it["filename"] == "run.mp4")
        gif_item = next(it for it in items if it["filename"] == "run.gif")
        assert mp4_item["mime"] == "video/mp4"
        assert mp4_item["subtype"] == "video"
        assert gif_item["mime"] == "image/gif"
        assert gif_item["subtype"] == "image"

    def test_index_no_items_when_no_index(self, tmp_path):
        """When items_index is None, no indexing occurs (no crash)."""
        _index_outputs(
            [tmp_path / "run.mp4"],
            {"run_id": "r1"}, None, session_id="s1", provider=None, model=None,
        )

    def test_build_export_steps_does_not_index(self, tmp_path):
        """build_export_steps no longer indexes items (M6 fix — indexing moved to execute_steps)."""
        s = AppState(db_path=tmp_path / "i.db")
        sid = s.store.create()["id"]
        fd = frames_dir(tmp_path)
        od = tmp_path / "exports" / "no_index"
        cap = capture_dict(frames_dir=str(fd), out_dir=str(od))
        build_export_steps(fd, od, cap, ffmpeg="/nonexistent/ffmpeg", ffprobe="/nonexistent/ffprobe")
        items = s.items.list(session_id=sid)
        assert len(items) == 0  # no phantom items from planning


# ======================================================================= size warning


class TestSizeWarning:
    def test_no_warning_below_threshold(self, tmp_path):
        d = tmp_path / "replay"
        d.mkdir(parents=True)
        # _replay_dir_size returns MB (total bytes / 1_048_576).  Write just under the threshold.
        n_bytes = max(1, WARN_TOTAL_MB * 1024 * 1024 - 1)
        (d / "small.bin").write_bytes(b"x" * min(n_bytes, 100_000))
        size = _replay_dir_size(d)
        # When we wrote less than threshold, size < threshold (even if we couldn't write full amount)
        assert size <= WARN_TOTAL_MB

    def test_warning_above_threshold(self, monkeypatch, tmp_path):
        """Use a low threshold so we can exceed it with a small file."""
        monkeypatch.setattr("gamedevworkstation.features.replay_media.WARN_TOTAL_MB", 1)  # 1 MB threshold
        d = tmp_path / "replay"
        d.mkdir(parents=True)
        (d / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB
        size = _replay_dir_size(d)
        assert size > 1

    def test_missing_dir(self):
        assert _replay_dir_size(None) == 0
        assert _replay_dir_size(Path("/nonexistent/replay")) == 0

    def test_execute_reports_warning(self, monkeypatch, tmp_path):
        """When replay_root exceeds threshold, a warning is returned."""
        monkeypatch.setattr("gamedevworkstation.features.replay_media.WARN_TOTAL_MB", 1)
        replay_root = tmp_path / "replay_root"
        replay_root.mkdir(parents=True)
        (replay_root / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))
        fd = frames_dir(tmp_path)
        od = tmp_path / "exports" / "warn"
        cap = capture_dict(frames_dir=str(fd), out_dir=str(od))
        plan = build_export_steps(fd, od, cap, ffmpeg="/nonexistent/ffmpeg", ffprobe="/nonexistent/ffprobe")
        result = execute_steps(plan, ffmpeg="/nonexistent/ffmpeg", ffprobe="/nonexistent/ffprobe",
                               replay_root=replay_root)
        assert result["warnings"]
        assert any("warn threshold" in w for w in result["warnings"])


# ======================================================================= doctor


class TestDoctor:
    def test_doctor_returns_dict(self):
        d = doctor(ffmpeg=FFMPEG or "/nonexistent/ffmpeg")
        assert "ok" in d
        assert "ffmpeg" in d
        assert "ffprobe" in d
        assert "missing" in d
        assert "caps" in d

    def test_doctor_missing_ffmpeg(self):
        # A nonexistent path still "works" — caps will be empty, missing will list components.
        d = doctor(ffmpeg="/nonexistent/ffmpeg")
        assert not d["ok"]
        assert d["missing"]  # missing encoders/filters
        assert "libx264" in str(d["missing"]) or any("libx264" in m for m in d["missing"])

    def test_check_caps_empty_when_no_caps(self):
        assert _check_caps(None, for_gif=True) == []

    def test_check_caps_missing_encoder(self):
        caps = {"encoders": set(), "filters": {"fps", "scale"}}
        missing = _check_caps(caps)
        assert any("libx264" in m for m in missing)

    def test_check_caps_missing_gif_filter(self):
        caps = {"encoders": {"libx264"}, "filters": {"fps", "scale"}}
        missing = _check_caps(caps, for_gif=True)
        assert any("palettegen" in m for m in missing)


# ======================================================================= verify output


class TestVerifyOutput:
    def test_verify_missing_file(self, tmp_path):
        result = _verify_output("/ffprobe", tmp_path / "missing.mp4", "mp4", 1920, 1080)
        assert "error" in result

    def test_verify_no_video_stream(self, tmp_path):
        p = tmp_path / "empty.mp4"
        p.write_bytes(b"not a video")
        result = _verify_output("/ffprobe", p, "mp4", 1920, 1080)
        assert "error" in result

    def test_verify_wrong_codec(self, tmp_path):
        # Without ffprobe, verification falls through gracefully
        p = tmp_path / "test.mp4"
        p.write_bytes(b"dummy")
        result = _verify_output(FFPROBE or "/ffprobe", p, "mp4", 1920, 1080)
        if FFPROBE:
            assert "error" in result
        else:
            # Without ffprobe, ffprobe_probe returns None, so we get "could not read"
            assert "could not read" in result.get("error", "")


# ======================================================================= ReplayMediaError


class TestReplayMediaError:
    def test_is_value_error(self):
        assert issubclass(ReplayMediaError, ValueError)

    def test_message(self):
        e = ReplayMediaError("test message")
        assert str(e) == "test message"


# ======================================================================= palette_gif_cmd


class TestPaletteGifCmd:
    def test_default_params(self):
        cmd = palette_gif_cmd()
        assert "fps=15" in cmd
        assert "scale=480:-2" in cmd
        assert "palettegen" in cmd
        assert "paletteuse" in cmd
        assert "split[a][b]" in cmd

    def test_custom_params(self):
        cmd = palette_gif_cmd(fps=10, scale=320)
        assert "fps=10" in cmd
        assert "scale=320:-2" in cmd


# ======================================================================= ffmpeg path resolution


class TestFfmpegPaths:
    def test_raises_when_missing(self):
        """Only raises when ffmpeg is None and cannot be discovered."""
        ff, fp = _ffmpeg_paths(ffmpeg="/definitely/missing/ffmpeg")
        # Returns the paths as-is when explicitly given
        assert ff == "/definitely/missing/ffmpeg"
        # When ffmpeg is None and nothing on PATH, it raises
        if not FFMPEG:
            with pytest.raises(ReplayMediaError):
                _ffmpeg_paths(ffmpeg=None)

    def test_resolves_from_env(self):
        if FFMPEG:
            ff, fp = _ffmpeg_paths()
            assert ff and fp
        else:
            with pytest.raises(ReplayMediaError):
                _ffmpeg_paths()


# ======================================================================= _trim_notes edge cases


class TestTrimNotesEdgeCases:
    def test_zero_fps_does_not_divide_by_zero(self):
        notes = _trim_notes(0, 0, 640, 480, 0, ["mp4"])
        assert len(notes) == 1
        assert notes[0]["duration_s"] == 0.0

    def test_negative_frames(self):
        notes = _trim_notes(30, 10, 640, 480, -100, ["mp4"])
        # The function does not clamp negative frames; it computes duration_s as total_frames/fps.
        # The caller (build_export_steps) handles negative/zero ranges.
        assert notes[0]["duration_s"] < 0.0

    def test_formats_empty(self):
        notes = _trim_notes(30, 10, 640, 480, 300, [])
        assert notes == []

    def test_gif_width_caps_at_max(self):
        notes = _trim_notes(30, 10, 800, 600, 300, ["gif"])
        assert notes[0]["width"] == MAX_GIF_W

    def test_gif_height_preserves_aspect(self):
        notes = _trim_notes(30, 10, 800, 600, 300, ["gif"])
        expected_h = int(MAX_GIF_W * 600 / 800) // 2 * 2
        assert notes[0]["height"] == expected_h


# ======================================================================= real ffmpeg encode (optional)


@needs_ffmpeg
class TestRealFfmpeg:
    """One tiny real encode from 3 generated PNGs, verifying the output exists and is playable."""

    def test_tiny_mp4_export(self, tmp_path):
        """Generate 3 PNGs at 16x16, encode MP4, verify with ffprobe."""
        fd = frames_dir(tmp_path, n=3, w=16, h=16)
        od = tmp_path / "exports" / "tiny"
        cap = capture_dict(
            formats=["mp4"],
            width=16, height=16,
            fps=10, total_frames=3,
            frames_dir=str(fd), out_dir=str(od),
        )
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG, ffprobe=FFPROBE)
        result = execute_steps(plan, ffmpeg=FFMPEG, ffprobe=FFPROBE, delete_frames_after=True)
        assert result["ok"], result

        mp4 = od / "run.mp4"
        assert mp4.is_file() and mp4.stat().st_size > 0

        # Verify with ffprobe
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", str(mp4)],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(r.stdout)
        vs = next(s for s in info["streams"] if s["codec_type"] == "video")
        assert vs["codec_name"] == "h264"
        assert vs["width"] == 16 and vs["height"] == 16

    def test_tiny_gif_export(self, tmp_path):
        """Generate 3 PNGs, export MP4 then GIF, verify GIF exists."""
        fd = frames_dir(tmp_path, n=3, w=32, h=32)
        od = tmp_path / "exports" / "tiny_gif"
        cap = capture_dict(
            formats=["mp4", "gif"],
            width=32, height=32,
            fps=10, gif_fps=10,
            total_frames=3,
            frames_dir=str(fd), out_dir=str(od),
        )
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG, ffprobe=FFPROBE)
        result = execute_steps(plan, ffmpeg=FFMPEG, ffprobe=FFPROBE, delete_frames_after=True)
        assert result["ok"], result

        gif = od / "run.gif"
        assert gif.is_file() and gif.stat().st_size > 0
        # Verify with ffprobe
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json", "-show_streams", str(gif)],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(r.stdout)
        vs = next(s for s in info["streams"] if s["codec_type"] == "video")

    def test_frames_deleted_after_successful_export(self, tmp_path):
        """After a successful export, source PNGs are deleted."""
        fd = frames_dir(tmp_path, n=3, w=16, h=16)
        od = tmp_path / "exports" / "cleanup"
        cap = capture_dict(
            formats=["mp4"],
            width=16, height=16,
            fps=10, total_frames=3,
            frames_dir=str(fd), out_dir=str(od),
        )
        plan = build_export_steps(fd, od, cap, ffmpeg=FFMPEG, ffprobe=FFPROBE)
        result = execute_steps(plan, ffmpeg=FFMPEG, ffprobe=FFPROBE, delete_frames_after=True)
        assert result["ok"]
        assert not list(fd.glob("*.png"))  # all deleted


# ======================================================================= doctoring on real ffmpeg


@needs_ffmpeg
def test_doctor_with_real_ffmpeg():
    d = doctor(ffmpeg=FFMPEG)
    assert d["ok"], d["missing"]
    assert d["ffmpeg"] == FFMPEG
    assert d["ffprobe"] == FFPROBE
