"""MP4/GIF export of a replay's captured PNG frames, plus the ffmpeg doctor.

build_export_steps() produces shell-free argv lists and reuses the trailer-maker helpers
(_media_common.find_ffmpeg/ffmpeg_caps/probe and palette_gif_cmd); doctor() reports missing
executables/filters before a run.  Recorder capture itself lives in the Unity Editor package.

Owned by Task F.  See docs/plans/record-replay.md §"GIF/video on request" and Decisions #4/#5.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ._media_common import (
    REQUIRED_ENCODERS,
    REQUIRED_FILTERS,
    _check_caps,
    ffmpeg_caps,
    find_ffmpeg,
    palette_gif_cmd,
    probe as ffprobe_probe,
)

log = logging.getLogger(__name__)

# ── limits ──────────────────────────────────────────────────────────────────
MAX_VIDEO_W = 1920
MAX_VIDEO_H = 1080
MAX_VIDEO_FPS = 60
MAX_VIDEO_DURATION_S = 120

MAX_GIF_W = 480
MAX_GIF_FPS = 15
MAX_GIF_DURATION_S = 8

WARN_TOTAL_MB = 2048  # [unity.replay] warn_total_mb default


class ReplayMediaError(ValueError):
    """An unusable capture range/format or missing encoder; message names the problem."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class ExportPlan:
    """Ordered export steps, their expected outputs, trim notes and the resolved frame rates."""

    frames_dir: Path
    out_dir: Path
    steps: tuple[tuple[str, ...], ...]
    outputs: tuple[Path, ...]
    trims: tuple[dict, ...]
    fps: int
    gif_fps: int


# ── helpers ─────────────────────────────────────────────────────────────────


def _even_dim(w: int, h: int) -> tuple[int, int]:
    """Round width and height down to the nearest even integer."""
    return w - (w & 1), h - (h & 1)


def _ffmpeg_paths(
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> tuple[str, str]:
    """Resolve ffmpeg/ffprobe; raise ReplayMediaError if not found."""
    if not ffmpeg:
        ffmpeg, ffprobe = find_ffmpeg() or (None, None)
    elif not ffprobe:
        # Derive ffprobe from the given ffmpeg path.
        candidate = Path(ffmpeg).parent / "ffprobe"
        ffprobe = str(candidate) if candidate.is_file() else shutil.which("ffprobe")
    if not ffmpeg:
        raise ReplayMediaError("ffmpeg not found (install it with `brew install ffmpeg`)")
    return ffmpeg, ffprobe or ffmpeg.replace("ffmpeg", "ffprobe")


def _trim_notes(
    fps: int, gif_fps: int, w: int, h: int,
    total_frames: int, formats: Sequence[str],
) -> list[dict]:
    """Return trim notes per format: dicts with format, original values, clamped values and a note string."""
    notes: list[dict] = []
    total_s = total_frames / max(fps, 1)

    if "mp4" in formats:
        trim: dict[str, Any] = {"format": "mp4"}
        trim["fps"] = min(fps, MAX_VIDEO_FPS)
        trim["width"], trim["height"] = _even_dim(min(w, MAX_VIDEO_W), min(h, MAX_VIDEO_H))
        trim["duration_s"] = min(total_s, MAX_VIDEO_DURATION_S)
        msg_parts: list[str] = []
        if fps > MAX_VIDEO_FPS:
            msg_parts.append(f"fps {fps} -> {trim['fps']}")
        if w > MAX_VIDEO_W or h > MAX_VIDEO_H:
            msg_parts.append(f"size {w}x{h} -> {trim['width']}x{trim['height']}")
        if total_s > MAX_VIDEO_DURATION_S:
            msg_parts.append(f"duration {total_s:.1f}s -> {trim['duration_s']:.1f}s")
        trim["note"] = "; ".join(msg_parts) if msg_parts else ""
        notes.append(trim)

    if "gif" in formats:
        gtrim: dict[str, Any] = {"format": "gif"}
        gtrim["fps"] = min(gif_fps, MAX_GIF_FPS)
        gtrim["width"] = min(w, MAX_GIF_W)
        gtrim["height"] = int(gtrim["width"] * h / max(w, 1)) // 2 * 2  # even, preserve aspect
        gtrim["duration_s"] = min(total_s, MAX_GIF_DURATION_S)
        msg_parts = []
        if gif_fps > MAX_GIF_FPS:
            msg_parts.append(f"fps {gif_fps} -> {gtrim['fps']}")
        if w > MAX_GIF_W:
            msg_parts.append(f"width {w} -> {gtrim['width']}")
        if total_s > MAX_GIF_DURATION_S:
            msg_parts.append(f"duration {total_s:.1f}s -> {gtrim['duration_s']:.1f}s")
        gtrim["note"] = "; ".join(msg_parts) if msg_parts else ""
        notes.append(gtrim)

    return notes


def _mp4_argv(
    ffmpeg: str, frames_dir: str | Path, out: str | Path,
    fps: int, w: int, h: int, duration_s: float,
) -> tuple[str, ...]:
    """Build the MP4 export argv (no shell)."""
    return (
        ffmpeg, "-hide_banner", "-n",
        "-framerate", str(fps),
        "-i", str(Path(frames_dir) / "frame-%06d.png"),
        "-t", f"{duration_s:.3f}",
        "-vf", f"scale={w}:{h}:flags=lanczos",
        "-c:v", "libx264", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out),
    )


def _gif_argv(
    ffmpeg: str, mp4_path: str | Path, out: str | Path,
    fps: int, w: int, h: int, duration_s: float,
) -> tuple[str, ...]:
    """Build the GIF export argv (palette-based, no shell)."""
    # Even height: scale=-2 ensures even.  If caller already gave an even w, honour it.
    scale_w = w - (w & 1)
    return (
        ffmpeg, "-hide_banner", "-n",
        "-t", f"{duration_s:.3f}",
        "-i", str(mp4_path),
        "-filter_complex",
        f"fps={fps},scale={scale_w}:-2:flags=lanczos,"
        f"split[a][b];[a]palettegen[p];[b][p]paletteuse",
        "-loop", "0",
        str(out),
    )


def _verify_output(
    ffprobe: str, path: Path, fmt: str, expected_w: int, expected_h: int,
) -> dict[str, Any]:
    """Verify a media file with ffprobe; return {} on success or a dict with 'error'."""
    info = ffprobe_probe(ffprobe, str(path))
    if info is None:
        return {"error": f"ffprobe could not read {path.name}"}
    vs = None
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            vs = s
            break
    if vs is None:
        return {"error": f"{path.name} has no video stream"}
    actual_w = vs.get("width", 0)
    actual_h = vs.get("height", 0)
    if actual_w != expected_w or actual_h != expected_h:
        return {"error": f"{path.name}: expected {expected_w}x{expected_h}, got {actual_w}x{actual_h}"}
    if fmt == "mp4" and vs.get("codec_name") != "h264":
        return {"error": f"{path.name}: expected h264, got {vs.get('codec_name')}"}
    return {}


def _delete_frames(frames_dir: Path) -> None:
    """Delete all PNG files in *frames_dir* (called only after a successful export).

    Safety: refuses paths whose resolved form does not end with ``capture/frames``
    (Decision 5 — frame deletion only inside a run's own capture directory).
    """
    resolved = frames_dir.resolve()
    parts = resolved.parts
    if len(parts) < 2 or parts[-2] != "capture" or parts[-1] != "frames":
        raise ReplayMediaError(
            f"refusing to delete frames outside capture/frames: {frames_dir}"
        )
    if not frames_dir.is_dir():
        return
    for p in frames_dir.iterdir():
        if p.suffix.lower() == ".png" and p.is_file():
            p.unlink()


def _replay_dir_size(replay_root: Path | None) -> int:
    """Total size in MB of a replay Logs/harness/replay/ directory, or 0."""
    if replay_root is None or not replay_root.is_dir():
        return 0
    total = 0
    for p in replay_root.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total // (1024 * 1024)


# ── public API ──────────────────────────────────────────────────────────────


def build_export_steps(
    frames_dir: str | Path,
    out_dir: str | Path,
    capture: Mapping[str, Any],
    *,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    caps: Mapping[str, Any] | None = None,
    replay_root: Path | None = None,
) -> ExportPlan:
    """Plan MP4 (H.264/yuv420p/faststart) then GIF (palette, 480-wide/15 fps/8 s) argv lists.

    Pure planning function — no filesystem side effects (no mkdir, no item indexing).
    Callers run the plan through ``execute_steps`` for actual execution.

    Parameters
    ----------
    frames_dir
        Directory containing ``frame-*.png`` files named ``frame-%06d.png``.
    out_dir
        Unique export output directory (e.g. ``.../exports/<export_id>/``).
    capture
        User-facing capture spec with keys:
        - ``formats``: list of ``"mp4"`` and/or ``"gif"``
        - ``width``, ``height``: frame dimensions
        - ``fps``: source frame rate
        - ``gif_fps``: separate GIF frame rate (default *fps*)
        - ``total_frames``: number of captured frames (or ``start_frame``/``end_frame_exclusive``)
        - ``start_frame``, ``end_frame_exclusive``: optional range (default 0, *total_frames*)
        - ``backend``: ``"png"``, ``"recorder"``, or ``"auto"``
    ffmpeg, ffprobe
        Override paths.
    caps
        Pre-computed ffmpeg caps dict (avoids re-probing).
    replay_root
        ``Logs/harness/replay/`` path; checked for size warning.

    Returns
    -------
    ExportPlan with steps, outputs, trim notes.
    """
    ffmpeg_bin, ffprobe_bin = _ffmpeg_paths(ffmpeg, ffprobe)
    fd = Path(frames_dir)
    od = Path(out_dir)

    formats = list(capture.get("formats", ["mp4"]))
    fps = int(capture.get("fps", 60))
    gif_fps = int(capture.get("gif_fps", fps))
    w = int(capture.get("width", 1920))
    h = int(capture.get("height", 1080))
    total_frames = int(capture.get("total_frames", 0))
    start_frame = int(capture.get("start_frame", 0))
    end_frame = int(capture.get("end_frame_exclusive", total_frames))
    if end_frame <= start_frame:
        end_frame = total_frames
    range_frames = end_frame - start_frame

    # Validate dimensions.
    if w < 2 or h < 2:
        raise ReplayMediaError(f"dimensions {w}x{h} are too small")

    # Build trim notes.
    trims = _trim_notes(fps, gif_fps, w, h, range_frames, formats)

    # Resolve final values from trims (clamped).
    mp4_w, mp4_h = _even_dim(min(w, MAX_VIDEO_W), min(h, MAX_VIDEO_H))
    mp4_fps = min(fps, MAX_VIDEO_FPS)
    mp4_dur = min(range_frames / max(fps, 1), MAX_VIDEO_DURATION_S)

    gif_trim = next((t for t in trims if t["format"] == "gif"), None)
    gif_w = gif_trim["width"] if gif_trim else min(w, MAX_GIF_W)
    gif_h = gif_trim["height"] if gif_trim else _even_dim(min(h, MAX_VIDEO_H), min(h, MAX_VIDEO_H))[1]
    gif_fps_out = gif_trim["fps"] if gif_trim else min(gif_fps, MAX_GIF_FPS)
    gif_dur = gif_trim["duration_s"] if gif_trim else min(range_frames / max(fps, 1), MAX_GIF_DURATION_S)

    steps: list[tuple[str, ...]] = []
    outputs: list[Path] = []

    # MP4 step.
    mp4_path = od / "run.mp4"
    steps.append(
        _mp4_argv(ffmpeg_bin, fd, mp4_path, mp4_fps, mp4_w, mp4_h, mp4_dur)
    )
    outputs.append(mp4_path)

    # GIF step (re-encodes from the MP4).
    if "gif" in formats:
        gif_path = od / "run.gif"
        steps.append(
            _gif_argv(ffmpeg_bin, mp4_path, gif_path, gif_fps_out, gif_w, gif_h, gif_dur)
        )
        outputs.append(gif_path)

    return ExportPlan(
        frames_dir=fd,
        out_dir=od,
        steps=tuple(steps),
        outputs=tuple(outputs),
        trims=tuple(trims),
        fps=mp4_fps,
        gif_fps=gif_fps_out,
    )


def _index_outputs(
    outputs: list[Path],
    capture: Mapping[str, Any],
    items_index: Any,
    session_id: str | None,
    provider: str | None,
    model: str | None,
) -> None:
    """Index export outputs via ItemIndex.

    Format (mp4/gif) is derived from each output's file suffix rather than
    relying on caller-ordered lists — outputs are always MP4-then-GIF in the
    plan but ``capture.formats`` may list them in any order (fixes M5).
    """
    if items_index is None:
        return
    meta: dict[str, Any] = {
        "run": capture.get("run_id"),
        "range": {
            "start_frame": capture.get("start_frame", 0),
            "end_frame": capture.get("end_frame_exclusive", capture.get("total_frames", 0)),
        },
        "verification": "pending",
    }
    for path in outputs:
        fmt = "mp4" if path.suffix == ".mp4" else "gif"
        mime = "video/mp4" if fmt == "mp4" else "image/gif"
        subtype = "video" if fmt == "mp4" else "image"
        try:
            items_index.add(
                kind="media",
                subtype=subtype,
                source="tool",
                session_id=session_id,
                provider=provider,
                model=model,
                title=path.name,
                path=str(path),
                size=path.stat().st_size if path.is_file() else None,
                mime=mime,
                meta=meta,
            )
        except Exception:  # noqa: BLE001
            log.warning("replay_media: could not index %s", path)


def execute_steps(
    plan: ExportPlan,
    *,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    verify: bool = True,
    delete_frames_after: bool = True,
    replay_root: Path | None = None,
    capture: Mapping[str, Any] | None = None,
    items_index: Any = None,
    session_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Execute the export steps and return a result dict.

    Returns ``{"ok": bool, "results": list[dict], "warnings": list[str], "verifications": list[dict]}``.
    Each result dict has ``step`` (index), ``output`` (Path or None), ``ok``, and optional ``error``.
    """
    ffmpeg_bin, ffprobe_bin = _ffmpeg_paths(ffmpeg, ffprobe)

    # Create output directory (planning function is pure — M6 fix).
    plan.out_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    results: list[dict] = []
    verifications: list[dict] = []

    for i, argv in enumerate(plan.steps):
        out_path = plan.outputs[i] if i < len(plan.outputs) else None
        result: dict[str, Any] = {"step": i, "output": out_path, "ok": False}

        try:
            r = subprocess.run(
                argv,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
            )
            if r.returncode != 0:
                error = r.stderr.strip() or f"ffmpeg exit code {r.returncode}"
                result["error"] = error
                results.append(result)
                # Stop on first failure: later steps depend on earlier ones.
                break
        except (OSError, subprocess.SubprocessError) as e:
            result["error"] = str(e)
            results.append(result)
            break

        result["ok"] = True
        results.append(result)

        # Verify with ffprobe — look up the correct trim for this output format (M4 fix).
        if verify and out_path and out_path.is_file():
            fmt = "mp4" if out_path.suffix == ".mp4" else "gif"
            trim = next((t for t in plan.trims if t["format"] == fmt), None)
            if trim:
                ew, eh = trim["width"], trim["height"]
            else:
                ew, eh = 0, 0
            v = _verify_output(ffprobe_bin, out_path, fmt, ew, eh)
            verifications.append(v)

    # Check replay root size.
    total_mb = _replay_dir_size(replay_root)
    if total_mb > WARN_TOTAL_MB:
        warnings.append(
            f"Logs/harness/replay/ is {total_mb} MB (warn threshold: {WARN_TOTAL_MB} MB)"
        )

    # Index outputs only on full success (M6 fix — no phantom items from dry-run plan).
    all_ok = all(r.get("ok") for r in results)
    if all_ok and capture is not None and items_index is not None:
        _index_outputs(list(plan.outputs), capture, items_index, session_id, provider, model)

    # Delete source PNGs only on full success.
    if all_ok and delete_frames_after:
        _delete_frames(plan.frames_dir)

    return {
        "ok": all_ok,
        "results": results,
        "warnings": warnings,
        "verifications": verifications,
    }


def doctor(ffmpeg: str | None = None) -> dict:
    """Check ffmpeg/ffprobe and required encoders/filters; returns ``{ok, ffmpeg, ffprobe, missing, caps}``."""
    ff, fp = _ffmpeg_paths(ffmpeg)
    caps = ffmpeg_caps(ff)
    missing = _check_caps(caps, for_gif=True)
    return {
        "ok": not missing,
        "ffmpeg": ff,
        "ffprobe": fp,
        "missing": missing,
        "caps": caps,
    }
