"""Shared helpers for the trailer-maker scripts: ffmpeg discovery, ffprobe JSON, PNG headers,
frame math and the RESULT line. Python 3.9+ standard library only.

Imported by trailer_edl.py, beat_grid.py and trailer_review.py (they put their own folder on sys.path).
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_NO_FFMPEG = 0, 1, 2, 3

# Trailer types: (min_s, max_s) of the finished cut. See references/beat-sheets.md.
TYPES = {
    "gameplay": (45, 75),
    "announce": (30, 60),
    "launch": (60, 90),
    "festival": (30, 45),
    "tell-show-repeat": (45, 75),
    "social": (15, 30),
}

# Export targets. See references/platform-specs.md (house defaults, not platform rules, where noted).
PLATFORMS = {
    "steam": {"w": 1920, "h": 1080, "vertical": False, "crf": 16, "maxrate": "24M", "bufsize": "48M",
              "ab": "192k", "vt_rate": "20M", "max_fps": 60, "srt": False, "poster": True},
    "youtube": {"w": 1920, "h": 1080, "vertical": False, "crf": 16, "maxrate": "16M", "bufsize": "32M",
                "ab": "384k", "vt_rate": "16M", "max_fps": 60, "srt": True, "poster": False},
    "x": {"w": 1920, "h": 1080, "vertical": False, "crf": 18, "maxrate": "12M", "bufsize": "24M",
          "ab": "128k", "vt_rate": "12M", "max_fps": 60, "srt": True, "poster": False},
    "shorts": {"w": 1080, "h": 1920, "vertical": True, "crf": 18, "maxrate": "16M", "bufsize": "32M",
               "ab": "192k", "vt_rate": "16M", "max_fps": 60, "srt": False, "poster": False},
    "tiktok": {"w": 1080, "h": 1920, "vertical": True, "crf": 18, "maxrate": "16M", "bufsize": "32M",
               "ab": "192k", "vt_rate": "16M", "max_fps": 60, "srt": False, "poster": False},
    "loop": {"w": 640, "h": 0, "vertical": False},
}
DEFAULT_EXPORTS = ["steam", "youtube", "shorts"]

TRANSITIONS = ("cut", "fade", "fadeblack", "fadewhite", "wipeleft", "wiperight", "slideleft", "slideright")
SCALE_FILTERS = ("lanczos", "bicubic", "bilinear", "neighbor")
POSITIONS = ("center", "top-left", "top-center", "top-right", "middle-left", "middle-right",
             "bottom-left", "bottom-center", "bottom-right")

REQUIRED_FILTERS = ("xfade", "loudnorm", "sidechaincompress", "overlay", "tile", "ebur128", "amix", "acrossfade",
                    "tpad", "gblur", "alimiter", "adelay", "blackdetect", "freezedetect", "signalstats")
REQUIRED_ENCODERS = ("libx264", "prores_ks", "aac")
OPTIONAL_FILTERS = ("drawtext", "subtitles")
OPTIONAL_ENCODERS = ("h264_videotoolbox", "libvpx-vp9", "libvpx")

FFMPEG_HINT = "Install it with `brew install ffmpeg` (or set TRAILER_FFMPEG to the ffmpeg binary)."


def result(ok, summary):
    """Print the final RESULT line and return the exit code."""
    print("RESULT: %s %s" % ("OK" if ok else "FAIL", summary))
    return EXIT_OK if ok else EXIT_FAIL


# ------------------------------------------------------------------ ffmpeg discovery


def find_ffmpeg():
    """(ffmpeg, ffprobe) paths, or (None, None). TRAILER_FFMPEG may name the binary or its folder;
    TRAILER_FFMPEG=none hides ffmpeg (tests)."""
    env = os.environ.get("TRAILER_FFMPEG", "").strip()
    if env.lower() == "none":
        return None, None
    cands = [env] if env else []
    w = shutil.which("ffmpeg")
    if w:
        cands.append(w)
    cands += ["/opt/homebrew/bin/ffmpeg", "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    for c in cands:
        if os.path.isdir(c):
            c = os.path.join(c, "ffmpeg")
        if os.path.isfile(c) and os.access(c, os.X_OK):
            probe = os.path.join(os.path.dirname(c), "ffprobe")
            if not (os.path.isfile(probe) and os.access(probe, os.X_OK)):
                probe = shutil.which("ffprobe")
            return c, probe
    return None, None


def ffmpeg_caps(ffmpeg):
    """{'version': str, 'filters': set, 'encoders': set} of an ffmpeg binary."""
    def out(*args):
        try:
            return subprocess.run([ffmpeg, "-hide_banner"] + list(args), capture_output=True, text=True,
                                  timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    ver = out("-version").splitlines()
    filters = set(re.findall(r"^\s*[A-Z.|]{2,3}\s+(\S+)\s", out("-filters"), re.M))
    encoders = set(re.findall(r"^\s*[VAS][A-Z.]{5}\s+(\S+)\s", out("-encoders"), re.M))
    return {"version": ver[0] if ver else "", "filters": filters, "encoders": encoders}


def probe(ffprobe, path):
    """ffprobe JSON (format + streams) of a media file, or None."""
    if not ffprobe:
        return None
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        return None


def parse_ffmpeg_info(stderr):
    """A minimal ffprobe-like dict from `ffmpeg -i FILE` stderr (format.duration, streams with codec_type,
    width/height for video), or None when ffmpeg found no streams."""
    streams = []
    for m in re.finditer(r"^\s*Stream #\d+:\d+[^:]*:\s*(Video|Audio|Subtitle|Data):\s*(.*)$", stderr or "", re.M):
        s = {"codec_type": m.group(1).lower(), "codec_name": m.group(2).split()[0].strip(",") if m.group(2) else ""}
        if s["codec_type"] == "video":
            wh = re.search(r"\b(\d{2,5})x(\d{2,5})\b", m.group(2))
            if wh:
                s["width"], s["height"] = int(wh.group(1)), int(wh.group(2))
        streams.append(s)
    if not streams:
        return None
    info = {"format": {}, "streams": streams, "probed_with": "ffmpeg"}
    d = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr or "")
    if d:
        info["format"]["duration"] = str(int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)))
    return info


def probe_ffmpeg(ffmpeg, path):
    """Stream layout of a media file from `ffmpeg -i` when ffprobe is missing, or None."""
    if not ffmpeg:
        return None
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_ffmpeg_info(r.stderr)


def stream(info, kind):
    for s in (info or {}).get("streams", []):
        if s.get("codec_type") == kind:
            return s
    return None


def media_duration(info):
    try:
        return float((info or {}).get("format", {}).get("duration"))
    except (TypeError, ValueError):
        return None


def rate(s):
    """'60/1' -> 60.0; None when unknown."""
    try:
        n, d = str(s).split("/")
        return float(n) / float(d) if float(d) else None
    except (ValueError, ZeroDivisionError):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None


# ------------------------------------------------------------------ PNG header


def png_info(path):
    """(width, height, has_alpha) from a PNG header, or None if it isn't a PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(33)
            if len(head) < 33 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
                return None
            w, h, _depth, ctype = struct.unpack(">IIBB", head[16:26])
            alpha = ctype in (4, 6)
            if not alpha:  # a tRNS chunk before IDAT also gives transparency
                f.seek(33)
                while True:
                    hdr = f.read(8)
                    if len(hdr) < 8:
                        break
                    n, t = struct.unpack(">I4s", hdr)
                    if t == b"tRNS":
                        alpha = True
                        break
                    if t in (b"IDAT", b"IEND"):
                        break
                    f.seek(n + 4, 1)
            return w, h, alpha
    except OSError:
        return None


# ------------------------------------------------------------------ numbers and time


def frames(t, fps):
    """Seconds -> whole frames (round half up)."""
    return int(float(t) * fps + 0.5 + 1e-9)


def num(x):
    """Stable short decimal for argv and JSON: 2.0 -> '2', 0.25 -> '0.25', 1/3 -> '0.333333'."""
    s = ("%.6f" % float(x)).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def db_to_lin(db):
    return 10 ** (float(db) / 20.0)


def hms(t):
    """Seconds -> SRT timestamp HH:MM:SS,mmm."""
    ms = int(round(max(0.0, float(t)) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def parse_hms(s):
    m = re.match(r"^\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*$", s)
    if not m:
        raise ValueError("bad timestamp %r" % s)
    h, mi, se, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, "0")) / 1000.0


def load_json(path, what="JSON"):
    """(data, error)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except OSError as e:
        return None, "%s %s: %s" % (what, path, e.strerror or e)
    except ValueError as e:
        return None, "%s %s is not valid JSON: %s" % (what, path, e)


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def under_assets(rel):
    parts = [p for p in re.split(r"[\\/]+", str(rel)) if p not in ("", ".")]
    return bool(parts) and parts[0] == "Assets"


def is_hook_beat(b):
    return bool(b.get("hook")) or "hook" in str(b.get("id", "")).lower()


def is_end_slate_beat(b):
    i = str(b.get("id", "")).lower()
    return bool(b.get("end_slate")) or "slate" in i or i in ("end", "endcard", "end-card")


def eprint(*a):
    print(*a, file=sys.stderr)
