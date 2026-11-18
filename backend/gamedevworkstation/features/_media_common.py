"""Shared media helpers for replay and trailer features.

Re-exports ffmpeg discovery/probe from skills/trailer-maker/scripts/_trailer_common
via importlib (no permanent sys.path modification) and provides the palette-GIF
ffmpeg filter_complex builder.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_TRAILER_SCRIPTS = (
    Path(__file__).resolve().parents[3] / "skills" / "trailer-maker" / "scripts"
)

_spec = importlib.util.spec_from_file_location(
    "_trailer_common", _TRAILER_SCRIPTS / "_trailer_common.py"
)
_tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tc)

find_ffmpeg = _tc.find_ffmpeg
ffmpeg_caps = _tc.ffmpeg_caps
probe = _tc.probe

__all__ = ["find_ffmpeg", "ffmpeg_caps", "probe", "palette_gif_cmd", "REQUIRED_ENCODERS", "REQUIRED_FILTERS"]

# Minimum encoders/filters for replay export.
REQUIRED_ENCODERS = ("libx264",)
REQUIRED_FILTERS = ("palettegen", "paletteuse", "split", "fps", "scale")


def palette_gif_cmd(fps: int = 15, scale: int = 480) -> str:
    """FFmpeg filter_complex for a palette-based GIF.

    Produces an even height (scale=-2) via lanczos.  Returns a string suitable
    for ``-filter_complex``.
    """
    return (
        f"fps={fps},scale={scale}:-2:flags=lanczos,"
        f"split[a][b];[a]palettegen[p];[b][p]paletteuse"
    )


def _check_caps(caps: dict[str, Any] | None, *, for_gif: bool = False) -> list[str]:
    """Return a list of missing encoders/filters given ffmpeg caps."""
    if caps is None:
        return []
    missing: list[str] = []
    for enc in REQUIRED_ENCODERS:
        if enc not in caps.get("encoders", set()):
            missing.append(f"encoder {enc}")
    needed = REQUIRED_FILTERS if for_gif else {"fps", "scale"}
    for flt in needed:
        if flt not in caps.get("filters", set()):
            missing.append(f"filter {flt}")
    return missing
