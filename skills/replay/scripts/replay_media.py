#!/usr/bin/env python3
"""CLI for replay-media export: doctor | plan | export.

Usage::

    replay_media.py doctor                             # check ffmpeg readiness
    replay_media.py plan <capture.json>                # dry-run: print plan
    replay_media.py export <capture.json> <frames_dir> <out_dir>   # execute

Capture JSON shape (see ``build_export_steps`` docstring)::

    {
      "formats": ["mp4", "gif"],
      "width": 1920, "height": 1080,
      "fps": 60, "gif_fps": 15,
      "total_frames": 1200,
      "start_frame": 0, "end_frame_exclusive": 1200,
      "backend": "png",
      "run_id": "run_abc123"
    }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the backend package is importable.
_BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(_BACKEND))

from gamedevworkstation.features.replay_media import (  # noqa: E402
    ExportPlan,
    ReplayMediaError,
    build_export_steps,
    doctor as doctor_fn,
    execute_steps,
)


def _load_capture(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_doctor() -> int:
    """Check ffmpeg/ffprobe and required encoders/filters."""
    try:
        d = doctor_fn()
    except ReplayMediaError as e:
        print(f"RESULT: FAIL {e}")
        return 3
    if d["ok"]:
        print(f"RESULT: OK ffmpeg ready ({d['ffmpeg']})")
        return 0
    for m in d["missing"]:
        print(f"MISSING: {m}")
    print("RESULT: FAIL missing components")
    return 1


def cmd_plan(capture_path: str) -> int:
    """Dry-run: print the export plan without executing."""
    try:
        capture = _load_capture(capture_path)
        plan = build_export_steps(
            capture.get("frames_dir", "frames"),
            capture.get("out_dir", "out"),
            capture,
        )
    except (ReplayMediaError, OSError, ValueError) as e:
        print(f"RESULT: FAIL {e}")
        return 1

    print(f"frames_dir: {plan.frames_dir}")
    print(f"out_dir:    {plan.out_dir}")
    print(f"fps:        {plan.fps}")
    print(f"gif_fps:    {plan.gif_fps}")
    for i, argv in enumerate(plan.steps):
        print(f"\nstep[{i}]:")
        print("  " + " ".join(str(a) for a in argv))
    for out in plan.outputs:
        print(f"\noutput: {out}")
    for t in plan.trims:
        if t.get("note"):
            print(f"\nTRIM: [{t['format']}] {t['note']}")
    print("\nRESULT: OK plan ready")
    return 0


def cmd_export(capture_path: str, frames_dir: str, out_dir: str) -> int:
    """Execute the export plan."""
    try:
        capture = _load_capture(capture_path)
        capture.setdefault("frames_dir", frames_dir)
        capture.setdefault("out_dir", out_dir)
        plan = build_export_steps(frames_dir, out_dir, capture)
        result = execute_steps(plan)
    except (ReplayMediaError, OSError, ValueError) as e:
        print(f"RESULT: FAIL {e}")
        return 1

    for r in result["results"]:
        out = r.get("output") or "?"
        if r.get("ok"):
            print(f"  OK  {out}")
        else:
            print(f"  FAIL  {out}: {r.get('error', 'unknown')}")

    for v in result["verifications"]:
        if v.get("error"):
            print(f"  VERIFY FAIL: {v['error']}")

    for w in result["warnings"]:
        print(f"  WARN: {w}")

    print(f"\nRESULT: {'OK' if result['ok'] else 'FAIL'} export {'completed' if result['ok'] else 'failed'}")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if not args:
        print("Usage: replay_media.py doctor|plan|export [...]", file=sys.stderr)
        return 2

    cmd = args[0]
    if cmd == "doctor":
        return cmd_doctor()
    elif cmd == "plan":
        if len(args) < 2:
            print("Usage: replay_media.py plan <capture.json>", file=sys.stderr)
            return 2
        return cmd_plan(args[1])
    elif cmd == "export":
        if len(args) < 4:
            print("Usage: replay_media.py export <capture.json> <frames_dir> <out_dir>", file=sys.stderr)
            return 2
        return cmd_export(args[1], args[2], args[3])
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
