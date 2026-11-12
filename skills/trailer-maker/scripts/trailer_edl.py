#!/usr/bin/env python3
"""Trailer edit-list tool: validates trailer plans and renders a JSON EDL with ffmpeg.

Subcommands (run from anywhere; paths in an EDL are relative to the EDL's folder):
  doctor                                  find ffmpeg/ffprobe and check the filters and encoders it needs
  check [edl.json] [--beats B] [--shots S] [--capture report.json]
                                          validate beats.json / shots.json / capture report / edl.json
  plan <edl.json> [--json] [--proxy] [--platform P]
                                          print the ffmpeg commands render/export would run (dry run)
  render <edl.json> [--proxy] [--jobs N]  build/clips/*.mov -> build/picture.mov -> build/master.wav
                                          -> build/master.mov (or build/proxy.mp4 with --proxy)
  export <edl.json> [--platform P ...] [--all] [--encoder x264|videotoolbox] [--max S] [--x-720]
                                          exports/<id>-<platform>.mp4 (steam, youtube, x, shorts, tiktok)
                                          and exports/<id>-loop.webm/.gif (loop); steam adds poster.png
  qc <exports-dir|file> [--edl edl.json] [--beats B] [--platform P]
                                          ffprobe + loudness + black/freeze/flash checks -> review/qc.json
  sheet <video> [--fps 1] [--cols 6] [--rows 5] [--first5] [--scenes] [--out-dir D]
                                          contact sheets for reviewers (review/sheet-NN.png, first5.png)
  srt <transcript.json|vo-script.md> --out captions/en.srt [--offset S] [--cards cards.json]
                                          block captions (<= 42 chars/line, <= 2 lines, 1-6 s)
  poster <edl.json> [--at T]              exports/poster.png, a 1920x1080 frame of build/master.mov

Every run ends with `RESULT: OK|FAIL <summary>`. Exit codes: 0 ok, 1 fail, 2 usage, 3 ffmpeg missing.
Files written are announced as `TRAILER_OUTPUT: <absolute path>` (the app indexes media ones as items).
Python 3.9+ standard library only. ffmpeg is an external program found on PATH (never bundled).
"""
import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _trailer_common import (  # noqa: E402
    DEFAULT_EXPORTS, EXIT_FAIL, EXIT_NO_FFMPEG, EXIT_OK, EXIT_USAGE, FFMPEG_HINT, OPTIONAL_ENCODERS,
    OPTIONAL_FILTERS, PLATFORMS, POSITIONS, REQUIRED_ENCODERS, REQUIRED_FILTERS, SCALE_FILTERS, TRANSITIONS,
    TYPES, ffmpeg_caps, find_ffmpeg, frames, hms, is_end_slate_beat, is_hook_beat, load_json, media_duration,
    num, parse_hms, png_info, probe, probe_ffmpeg, rate, result, stream, under_assets, write_json)

AR = 48000                 # audio sample rate of every intermediate and export
DEFAULT_TRANSITION_S = 0.25
HOOK_WARN_S, HOOK_FAIL_S = 10.0, 15.0
SOCIAL_MAX_S = 180.0


# ======================================================================= EDL model


def _color(c, default="0x000000"):
    s = str(c or "").strip()
    m = re.fullmatch(r"#?(?:0x)?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", s)
    if not m:
        return None if s else default
    return "0x" + m.group(1).lower()


def _num(v, where, default, errs, integer=False):
    """A user-supplied number, or default (with an error recorded) when it isn't one. None/'' -> default."""
    if v is None or v == "":
        return default
    try:
        if isinstance(v, bool):
            raise ValueError
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            raise ValueError
        return int(f) if integer else f
    except (TypeError, ValueError):
        errs.append("%s must be a number (got %r)" % (where, v))
        return default


def _obj(v, where, errs):
    """A user-supplied object (dict), or {} (with an error recorded) when it is something else. None -> {}."""
    if v is None:
        return {}
    if not isinstance(v, dict):
        errs.append("%s must be an object" % where)
        return {}
    return v


def load_edl(path):
    """(edl dict with derived fields, errors, warnings). Pure: no filesystem access beyond reading the file."""
    data, err = load_json(path, "EDL")
    if err:
        return None, [err], []
    return normalize_edl(data, os.path.dirname(os.path.abspath(path))), None, None


def normalize_edl(data, root):
    """Turn raw edl.json into a normalized dict; problems go to e['errors'] / e['warnings']."""
    errs, warns = [], []
    e = {"root": root, "errors": errs, "warnings": warns}
    if not isinstance(data, dict):
        errs.append("edl.json must be an object")
        data = {}
    e["id"] = str(data.get("id") or "trailer")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", e["id"]):
        errs.append("id must be letters, digits, '.', '_' or '-' (it names the export files)")
    e["type"] = data.get("type") or "gameplay"
    if not isinstance(e["type"], str) or e["type"] not in TYPES:
        errs.append("type %r is not one of %s" % (e["type"], ", ".join(TYPES)))
        if not isinstance(e["type"], str):
            e["type"] = "gameplay"
    fps = data.get("fps", 60)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not 24 <= fps <= 120:
        errs.append("fps must be a number from 24 to 120")
        fps = 60
    e["fps"] = fps
    if fps not in (30, 60):
        warns.append("fps %s: Steam and YouTube expect 30 or 60" % num(fps))
    cv = data.get("canvas") or {"w": 1920, "h": 1080}
    try:
        e["w"], e["h"] = int(cv["w"]), int(cv["h"])
        if e["w"] < 16 or e["h"] < 16 or e["w"] % 2 or e["h"] % 2:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        errs.append("canvas must be {\"w\": even int, \"h\": even int}")
        e["w"], e["h"] = 1920, 1080
    e["scale_filter"] = data.get("scale_filter") or "lanczos"
    if e["scale_filter"] not in SCALE_FILTERS:
        errs.append("scale_filter must be one of %s (neighbor for pixel art)" % ", ".join(SCALE_FILTERS))
        e["scale_filter"] = "lanczos"
    src = data.get("sources") or {}
    if not isinstance(src, dict):
        errs.append("sources must map a source id to a file path")
        src = {}
    e["sources"] = {str(k): str(v) for k, v in src.items()}

    # ---- video track
    items = []
    raw = data.get("video")
    if not isinstance(raw, list) or not raw:
        errs.append("video needs at least one clip or card")
        raw = []
    seen = set()
    for i, v in enumerate(raw):
        where = "video[%d]" % i
        if not isinstance(v, dict):
            errs.append(where + ": must be an object")
            continue
        it = {"id": str(v.get("id") or "c%02d" % (i + 1)), "beat": v.get("beat")}
        where = "video[%d] %s" % (i, it["id"])
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", it["id"]):
            errs.append(where + ": id must be letters, digits, '_' or '-'")
        if it["id"] in seen:
            errs.append(where + ": duplicate id")
        seen.add(it["id"])
        if "card" in v:
            it["kind"] = "card"
            it["card"] = str(v.get("card") or "")
            it["bg"] = _color(v.get("bg"))
            if it["bg"] is None:
                errs.append(where + ": bg must be a #RRGGBB color")
                it["bg"] = "0x000000"
            dur = v.get("dur")
            if isinstance(dur, bool) or not isinstance(dur, (int, float)) or dur <= 0:
                errs.append(where + ": a card needs dur > 0 (seconds)")
                dur = 1.0
            it["dur"] = float(dur)
            it["n"] = frames(dur, fps)
            it["speed"], it["freeze"] = 1.0, 0.0
        else:
            it["kind"] = "clip"
            it["src"] = str(v.get("src") or "")
            if it["src"] not in e["sources"]:
                errs.append(where + ": unknown src %r (add it to sources)" % it["src"])
            try:
                it["in"], it["out"] = float(v.get("in", 0)), float(v["out"])
            except (KeyError, TypeError, ValueError):
                errs.append(where + ": needs numeric in and out (seconds in the source)")
                it["in"], it["out"] = 0.0, 1.0
            if it["in"] < 0:
                errs.append(where + ": in must be >= 0")
            if it["out"] <= it["in"]:
                errs.append(where + ": out (%s) must be greater than in (%s)" % (num(it["out"]), num(it["in"])))
                it["out"] = it["in"] + 1.0 / fps
            sp = v.get("speed", 1.0)
            if isinstance(sp, bool) or not isinstance(sp, (int, float)) or not 0.1 <= sp <= 4:
                errs.append(where + ": speed must be from 0.1 to 4")
                sp = 1.0
            it["speed"] = float(sp)
            fr = v.get("freeze_end", 0)
            if isinstance(fr, bool) or not isinstance(fr, (int, float)) or fr < 0:
                errs.append(where + ": freeze_end must be >= 0 seconds")
                fr = 0
            it["freeze"] = float(fr)
            it["body"] = max(1, frames((it["out"] - it["in"]) / it["speed"], fps))
            it["n"] = it["body"] + frames(it["freeze"], fps)
            vc = v.get("vcrop")
            it["vcrop"] = None
            if vc is not None:
                x = vc.get("x") if isinstance(vc, dict) else None
                if isinstance(x, bool) or not isinstance(x, (int, float)) or not 0 <= x <= 1:
                    errs.append(where + ": vcrop must be {\"x\": 0..1} (horizontal focus for vertical cuts)")
                else:
                    it["vcrop"] = float(x)
            it["layout"] = v.get("layout") or ("crop" if it["vcrop"] is not None else "blurpad")
            if it["layout"] not in ("crop", "blurpad"):
                errs.append(where + ": layout must be crop or blurpad")
                it["layout"] = "blurpad"
        tr = v.get("transition_in") or {"type": "cut"}
        t = tr.get("type", "cut") if isinstance(tr, dict) else None
        if t not in TRANSITIONS:
            errs.append(where + ": transition_in.type must be one of %s" % ", ".join(TRANSITIONS))
            t = "cut"
        d = 0
        if t != "cut":
            ds = tr.get("dur", DEFAULT_TRANSITION_S)
            if isinstance(ds, bool) or not isinstance(ds, (int, float)) or ds <= 0:
                errs.append(where + ": transition_in.dur must be > 0")
                ds = DEFAULT_TRANSITION_S
            d = max(1, frames(ds, fps))
        if not items and t != "cut":
            warns.append(where + ": the first item can't have a transition_in (ignored; open on gameplay)")
            t, d = "cut", 0
        it["trans"], it["d"] = t, d
        items.append(it)

    # ---- timeline: positions follow from lengths and transitions (no gaps or overlaps possible)
    pos = 0
    for k, it in enumerate(items):
        if k and it["d"]:
            prev = items[k - 1]
            # the previous item must also hold both of its transitions (in and out) without them overlapping
            if it["d"] >= it["n"] or it["d"] >= prev["n"] or prev["d"] + it["d"] >= prev["n"]:
                errs.append("video[%d] %s: transition %s s is as long as a neighbouring item (%s s / %s s), or "
                            "overlaps the previous item's own transition in" % (
                                k, it["id"], num(it["d"] / fps), num(prev["n"] / fps), num(it["n"] / fps)))
        it["start"] = pos - (it["d"] if k else 0)
        it["end"] = it["start"] + it["n"]
        pos = it["end"]
    e["items"] = items
    e["total_n"] = pos
    e["total"] = pos / float(fps)

    # ---- rules on the cut as a whole
    lo, hi = TYPES.get(e["type"], (0, 1e9))
    if items and not lo <= e["total"] <= hi:
        warns.append("length %s s is outside the %s range %d-%d s" % (num(e["total"]), e["type"], lo, hi))
    if e["type"] == "social" and e["total"] > SOCIAL_MAX_S:
        errs.append("a social cut must be <= %d s (it is %s s)" % (SOCIAL_MAX_S, num(e["total"])))
    if items and items[0]["kind"] == "card" and items[0]["n"] > frames(1.0, fps):
        errs.append("hook rule: the trailer opens on a %s s card; open on gameplay in motion (a card first may "
                    "last 1.0 s at most)" % num(items[0]["n"] / fps))

    # ---- overlays
    ovs = []
    raw_ovs = data.get("overlays") or []
    if not isinstance(raw_ovs, list):
        errs.append("overlays must be a list")
        raw_ovs = []
    for i, o in enumerate(raw_ovs):
        where = "overlays[%d]" % i
        if not isinstance(o, dict) or not o.get("image"):
            errs.append(where + ": needs image")
            continue
        try:
            a, b = float(o["start"]), float(o["end"])
        except (KeyError, TypeError, ValueError):
            errs.append(where + ": needs numeric start and end")
            continue
        if a < 0 or b <= a or b > e["total"] + 0.5 / fps:
            errs.append(where + ": %s-%s s is outside the timeline (0-%s s)" % (num(a), num(b), num(e["total"])))
        p = o.get("pos", "center")
        if p not in POSITIONS:
            errs.append(where + ": pos must be one of %s" % ", ".join(POSITIONS))
            p = "center"
        fade = _num(o.get("fade"), where + ": fade", 0.0, errs)
        if fade < 0 or fade * 2 > (b - a):
            errs.append(where + ": fade must be >= 0 and at most half the overlay's length")
            fade = 0.0
        margin = _num(o.get("margin"), where + ": margin", 48, errs, integer=True)
        if margin < 0:
            errs.append(where + ": margin must be >= 0 pixels")
            margin = 48
        ovs.append({"image": str(o["image"]), "start": a, "end": b, "pos": p, "margin": margin,
                    "fade": fade, "vertical": bool(o.get("vertical", True))})
    e["overlays"] = ovs
    last = items[-1] if items else None
    end_slate = (last is not None and last["kind"] == "card") or any(
        o["end"] >= e["total"] - 1.0 / fps and o["start"] >= e["total"] - 6.0 - 1e-6 for o in ovs)
    if items and not end_slate:
        warns.append("no end slate in the last 6 s (logo + platforms + CTA): end on a card or an overlay")

    # ---- audio
    au = _obj(data.get("audio"), "audio", errs)
    g = _obj(au.get("game"), "audio.game", errs)
    e["game"] = {"enabled": bool(g.get("enabled", True)),
                 "gain_db": _num(g.get("gain_db"), "audio.game.gain_db", 0.0, errs)}
    m = au.get("music")
    e["music"] = None
    if m:
        if not isinstance(m, dict) or not m.get("path"):
            errs.append("audio.music needs path")
        else:
            e["music"] = {"path": str(m["path"])}
            for k in ("in", "at", "gain_db", "fade_in", "fade_out"):
                e["music"][k] = _num(m.get(k), "audio.music." + k, 0.0, errs)
            for k in ("in", "at", "fade_in", "fade_out"):
                if e["music"][k] < 0:
                    errs.append("audio.music.%s must be >= 0 seconds" % k)
                    e["music"][k] = 0.0
            if e["music"]["at"] >= e["total"] > 0:
                errs.append("audio.music.at is beyond the end of the cut")
    for kind in ("vo", "sfx"):
        lst = []
        raw_a = au.get(kind) or []
        if not isinstance(raw_a, list):
            errs.append("audio.%s must be a list" % kind)
            raw_a = []
        for i, x in enumerate(raw_a):
            where = "audio.%s[%d]" % (kind, i)
            if not isinstance(x, dict) or not x.get("path"):
                errs.append(where + ": needs path")
                continue
            try:
                at = float(x.get("at", 0))
            except (TypeError, ValueError):
                errs.append(where + ": at must be seconds")
                continue
            if at < 0 or at >= e["total"]:
                errs.append(where + ": at %s s is beyond the end of the cut (%s s)" % (num(at), num(e["total"])))
            lst.append({"path": str(x["path"]), "at": at,
                        "gain_db": _num(x.get("gain_db"), where + ".gain_db", 0.0, errs)})
        e[kind] = lst
    dk = _obj(au.get("duck"), "audio.duck", errs)
    e["duck"] = {"enabled": bool(dk.get("enabled", True))}
    for k, dv in (("threshold", 0.03), ("ratio", 8.0), ("attack_ms", 20.0), ("release_ms", 300.0)):
        e["duck"][k] = _num(dk.get(k), "audio.duck." + k, dv, errs)
    if not 0.000976563 <= e["duck"]["threshold"] <= 1 or not 1 <= e["duck"]["ratio"] <= 20:
        errs.append("audio.duck: threshold must be 0.001-1 (linear) and ratio 1-20")
    ld = _obj(au.get("loudness"), "audio.loudness", errs)
    e["loudness"] = {k: _num(ld.get(k), "audio.loudness." + k, dv, errs)
                     for k, dv in (("i", -14.0), ("tp", -1.0), ("lra", 11.0))}
    if not -70 <= e["loudness"]["i"] <= -5 or not -9 <= e["loudness"]["tp"] <= 0 or not 1 <= e["loudness"]["lra"] <= 50:
        errs.append("audio.loudness: i -70..-5 LUFS, tp -9..0 dBTP, lra 1..50 LU")

    # ---- captions, poster, exports, snapping
    cap = _obj(data.get("captions"), "captions", errs)
    bif = cap.get("burn_in_for") or []
    if not isinstance(bif, list):
        errs.append("captions.burn_in_for must be a list")
        bif = []
    srt = cap.get("srt")
    if srt is not None and not isinstance(srt, str):
        errs.append("captions.srt must be a path")
        srt = None
    png_dir = cap.get("png_dir") or "captions/png"
    if not isinstance(png_dir, str):
        errs.append("captions.png_dir must be a path")
        png_dir = "captions/png"
    e["captions"] = {"srt": srt, "burn_in_for": [p for p in bif if isinstance(p, str)], "png_dir": png_dir}
    for p in bif:
        if not isinstance(p, str) or p not in PLATFORMS or not PLATFORMS[p]["vertical"]:
            errs.append("captions.burn_in_for: %r is not a vertical platform (shorts, tiktok)" % (p,))
    pa = data.get("poster_at")
    e["poster_at"] = float(pa) if isinstance(pa, (int, float)) and not isinstance(pa, bool) else None
    if e["poster_at"] is not None and not 0 <= e["poster_at"] < e["total"]:
        errs.append("poster_at is outside the timeline")
    ex = data.get("exports", DEFAULT_EXPORTS)
    if not isinstance(ex, list):
        ex = []
        errs.append("exports must be a list")
    for p in ex:
        if not isinstance(p, str) or p not in PLATFORMS:
            errs.append("unknown export %r (one of %s)" % (p, ", ".join(PLATFORMS)))
    e["exports"] = [p for p in ex if isinstance(p, str) and p in PLATFORMS]
    vt = _obj(data.get("vertical"), "vertical", errs)
    e["vertical_max"] = _num(vt.get("max_s"), "vertical.max_s", 60.0, errs)
    if e["vertical_max"] <= 0:
        errs.append("vertical.max_s must be > 0 seconds")
        e["vertical_max"] = 60.0
    for k in ("beats_file", "beat_grid"):
        v = data.get(k)
        if v is not None and not isinstance(v, str):
            errs.append("%s must be a path" % k)
            v = None
        e[k] = v
    e["snap_tol"] = _num(data.get("snap_tolerance_frames"), "snap_tolerance_frames", 1, errs, integer=True)
    if e["snap_tol"] < 0:
        errs.append("snap_tolerance_frames must be >= 0")
        e["snap_tol"] = 1
    return e


def item_at(e, t):
    """The video item visible at time t (the later one during a transition)."""
    f = frames(t, e["fps"])
    hit = None
    for it in e["items"]:
        if it["start"] <= f < it["end"]:
            hit = it
    return hit


def cut_points(e):
    """Timeline seconds where a new item starts (middle of a transition for dissolves)."""
    fps = e["fps"]
    return [(it["id"], (it["start"] + it["d"] / 2.0) / fps) for it in e["items"][1:]]


# ======================================================================= file checks


def resolve(root, p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(root, p))


def probe_source(ffprobe, ffmpeg, path):
    """ffprobe info, or the stream layout `ffmpeg -i` reports when ffprobe is missing, or None."""
    if ffprobe:
        return probe(ffprobe, path)
    return probe_ffmpeg(ffmpeg, path)


def check_edl_files(e, ffprobe, ffmpeg=None):
    """File existence, durations (ffprobe), PNG sizes. Adds to e['errors'] / e['warnings'];
    returns {source id: probe info or None}. Without ffprobe, ffmpeg -i still tells which streams exist."""
    errs, warns, root = e["errors"], e["warnings"], e["root"]
    probes = {}
    used = {it["src"] for it in e["items"] if it["kind"] == "clip"}
    for sid, rel in sorted(e["sources"].items()):
        p = resolve(root, rel)
        if sid not in used:
            continue
        if not os.path.isfile(p):
            errs.append("source %s: file missing: %s" % (sid, rel))
            probes[sid] = None
            continue
        proj = _project_root(root)
        if proj and under_assets(os.path.relpath(p, proj)):
            warns.append("source %s is under Assets/ (capture outside Assets/ to avoid imports)" % sid)
        probes[sid] = probe_source(ffprobe, ffmpeg, p)
        if probes[sid] is None and (ffprobe or ffmpeg):
            errs.append("source %s: %s can't read %s" % (sid, "ffprobe" if ffprobe else "ffmpeg", rel))
    if not ffprobe:
        warns.append("ffprobe not found: %s. %s" % (
            "stream layout and durations came from ffmpeg -i (frame rates not checked)" if ffmpeg else
            "source durations and audio streams were not checked", FFMPEG_HINT))
    for k, it in enumerate(e["items"]):
        where = "video[%d] %s" % (k, it["id"])
        if it["kind"] == "clip":
            info = probes.get(it["src"])
            dur = media_duration(info)
            vs = stream(info, "video")
            if info is not None and vs is None:
                errs.append(where + ": source %s has no video stream" % it["src"])
            if vs is not None:
                vd = vs.get("duration")
                try:
                    dur = float(vd)
                except (TypeError, ValueError):
                    pass
                fr_avg, fr_r = rate(vs.get("avg_frame_rate")), rate(vs.get("r_frame_rate"))
                if fr_avg and fr_r and abs(fr_avg - fr_r) > 0.01 * fr_r:
                    warns.append(where + ": source %s looks variable-frame-rate (%s vs %s fps); recapture at a "
                                         "constant rate" % (it["src"], num(fr_avg), num(fr_r)))
            if dur is not None and it["out"] > dur + 0.5 / e["fps"]:
                errs.append(where + ": out %s s is beyond the source's %s s" % (num(it["out"]), num(dur)))
        else:
            p = resolve(e["root"], it["card"])
            info = png_info(p) if os.path.isfile(p) else None
            if not os.path.isfile(p):
                errs.append(where + ": card file missing: %s" % it["card"])
            elif info is None:
                errs.append(where + ": card %s is not a PNG" % it["card"])
            elif (info[0], info[1]) != (e["w"], e["h"]):
                errs.append(where + ": card %s is %dx%d, not the canvas size %dx%d" % (
                    it["card"], info[0], info[1], e["w"], e["h"]))
    for i, o in enumerate(e["overlays"]):
        p = resolve(root, o["image"])
        info = png_info(p) if os.path.isfile(p) else None
        if not os.path.isfile(p):
            errs.append("overlays[%d]: image missing: %s" % (i, o["image"]))
        elif info is None:
            errs.append("overlays[%d]: %s is not a PNG" % (i, o["image"]))
        else:
            if not info[2]:
                errs.append("overlays[%d]: %s has no alpha channel (export it as RGBA PNG)" % (i, o["image"]))
            if info[0] > e["w"] or info[1] > e["h"]:
                errs.append("overlays[%d]: %s (%dx%d) is larger than the canvas" % (i, o["image"], info[0], info[1]))
    for kind, lst in (("music", [e["music"]] if e["music"] else []), ("vo", e["vo"]), ("sfx", e["sfx"])):
        for x in lst:
            if not os.path.isfile(resolve(root, x["path"])):
                errs.append("audio.%s: file missing: %s" % (kind, x["path"]))
    srt = e["captions"]["srt"]
    if srt and not os.path.isfile(resolve(root, srt)):
        warns.append("captions.srt %s does not exist yet (trailer_edl.py srt makes it)" % srt)
    if not srt and any(p in e["exports"] for p in ("youtube", "x")):
        warns.append("no captions.srt: YouTube and X uploads should get hand-checked .srt captions")
    if e["poster_at"] is not None:
        it = item_at(e, e["poster_at"])
        if it and it["kind"] == "card":
            warns.append("poster_at %s s is on card %s: Steam posters should avoid text" % (num(e["poster_at"]),
                                                                                          it["id"]))
    return probes


def snap_report(e, grid_path=None):
    """Cut points vs the beat grid (beat_grid.py output): warnings for cuts off the grid.

    Grid beats are times in the music file; the music starts playing at audio.music.at on the timeline from
    audio.music.in in the file, so a beat b lands at b - in + at. Without music there is nothing to snap to."""
    gp = grid_path or e.get("beat_grid")
    if not gp:
        return []
    m = e.get("music")
    if not m:
        return []
    grid, err = load_json(resolve(e["root"], gp), "beat grid")
    if err:
        return ["beat grid: " + err]
    raw = (grid or {}).get("beats", []) if isinstance(grid, dict) else []
    file_beats = []
    for b in raw if isinstance(raw, list) else []:
        try:
            file_beats.append(float(b))
        except (TypeError, ValueError):
            continue
    beats = sorted(tl for tl in (b - m["in"] + m["at"] for b in file_beats) if m["at"] <= tl <= e["total"])
    if not beats:
        return ["beat grid %s has no beats inside the music on the timeline" % gp]
    tol = (e["snap_tol"] + 0.5) / e["fps"]
    out = []
    for iid, t in cut_points(e):
        near = min(beats, key=lambda b: abs(b - t))
        if abs(near - t) > tol:
            out.append("cut into %s at %s s is %d frame(s) off the nearest beat %s s" % (
                iid, num(t), int(round(abs(near - t) * e["fps"])), num(near)))
    return out


# ======================================================================= beats / shots / capture checks


def check_beats(b):
    errs, warns = [], []
    if not isinstance(b, dict):
        return ["beats.json must be an object"], []
    t = b.get("type")
    if t not in TYPES:
        errs.append("beats: type %r is not one of %s" % (t, ", ".join(TYPES)))
    if not str(b.get("core_message") or "").strip():
        errs.append("beats: core_message (one sentence) is required")
    if not str(b.get("cta") or "").strip():
        warns.append("beats: no cta (e.g. \"Wishlist on Steam\")")
    beats = b.get("beats")
    if not isinstance(beats, list) or not beats:
        return errs + ["beats: needs a non-empty beats list"], warns
    ids, prev_end = set(), 0.0
    for i, x in enumerate(beats):
        where = "beats[%d] %s" % (i, x.get("id") if isinstance(x, dict) else "?")
        if not isinstance(x, dict):
            errs.append(where + ": must be an object")
            continue
        try:
            s, en = float(x["start"]), float(x["end"])
        except (KeyError, TypeError, ValueError):
            errs.append(where + ": needs numeric start and end")
            continue
        if not x.get("id"):
            errs.append(where + ": needs an id")
        elif x["id"] in ids:
            errs.append(where + ": duplicate id")
        ids.add(x.get("id"))
        if abs(s - prev_end) > 1e-3:
            errs.append(where + ": starts at %s s but the previous beat ends at %s s (beats must be contiguous)" % (
                num(s), num(prev_end)))
        if en <= s:
            errs.append(where + ": end must be after start")
        if not str(x.get("intent") or "").strip():
            warns.append(where + ": no intent")
        sh = x.get("shots", [])
        if not isinstance(sh, list) or not all(isinstance(v, str) for v in sh):
            errs.append(where + ": shots must be a list of shot ids")
        card = x.get("card")
        if card:
            words = len(str(card).split())
            if words > 7:
                errs.append(where + ": card %r has %d words (7 at most)" % (card, words))
            need = 0.5 + 0.33 * words
            if en - s < need:
                warns.append(where + ": a %d-word card needs %s s on screen" % (words, num(need)))
        prev_end = en
    total = prev_end
    lo, hi = TYPES.get(t, (0, 1e9))
    if not lo <= total <= hi:
        warns.append("beats: total %s s is outside the %s range %d-%d s" % (num(total), t, lo, hi))
    if t == "social" and total > SOCIAL_MAX_S:
        errs.append("beats: a social cut must be <= %d s" % SOCIAL_MAX_S)
    hooks = [x for x in beats if isinstance(x, dict) and is_hook_beat(x)]
    if not hooks:
        errs.append("beats: no hook beat (an id containing 'hook', or \"hook\": true)")
    else:
        hs = float(hooks[0].get("start", 0))
        if hs > HOOK_FAIL_S:
            errs.append("beats: the hook starts at %s s (hard limit %d s; aim for <= %d s)" % (
                num(hs), HOOK_FAIL_S, HOOK_WARN_S))
        elif hs > HOOK_WARN_S:
            warns.append("beats: the hook starts at %s s (aim for <= %d s)" % (num(hs), HOOK_WARN_S))
    first = beats[0] if isinstance(beats[0], dict) else {}
    if first.get("card") and float(first.get("end", 0)) - float(first.get("start", 0)) > 1.0 and not first.get("shots"):
        errs.append("beats: the first beat is a card; open on gameplay in motion")
    lastb = beats[-1] if isinstance(beats[-1], dict) else {}
    if not is_end_slate_beat(lastb):
        errs.append("beats: the last beat must be the end slate (id containing 'slate' or \"end_slate\": true)")
    else:
        d = float(lastb.get("end", 0)) - float(lastb.get("start", 0))
        lo_s, hi_s = (2, 3) if t == "social" else (3, 6)
        if not lo_s - 1e-6 <= d <= hi_s + 1e-6:
            warns.append("beats: end slate is %s s (aim for %d-%d s)" % (num(d), lo_s, hi_s))
    return errs, warns


def check_shots(s, beats=None):
    errs, warns = [], []
    if not isinstance(s, dict):
        return ["shots.json must be an object"], []
    fps = s.get("fps", 60)
    if fps not in (30, 60):
        warns.append("shots: fps %s (capture at 60 constant; 30 is the fallback)" % fps)
    r = s.get("resolution") or {}
    if not (isinstance(r.get("w"), int) and isinstance(r.get("h"), int) and r["w"] > 0 and r["h"] > 0
            and r["w"] % 2 == 0 and r["h"] % 2 == 0):
        errs.append("shots: resolution must be {\"w\": even int, \"h\": even int}")
    if s.get("source", "game_view") not in ("game_view", "render_texture"):
        errs.append("shots: source must be game_view or render_texture")
    if s.get("codec", "mp4") not in ("mp4", "prores"):
        errs.append("shots: codec must be mp4 or prores")
    od = str(s.get("output_dir") or "")
    if not od:
        errs.append("shots: output_dir is required (e.g. Trailer/<slug>/capture)")
    elif os.path.isabs(od) or ".." in re.split(r"[\\/]", od):
        errs.append("shots: output_dir must be relative to the Unity project root")
    elif under_assets(od):
        errs.append("shots: output_dir must be outside Assets/ (import churn, quality-ladder visual gate)")
    au = s.get("audio") or {}
    if au and not isinstance(au.get("capture", True), bool):
        errs.append("shots: audio.capture must be true or false")
    shots = s.get("shots")
    if not isinstance(shots, list) or not shots:
        return errs + ["shots: needs a non-empty shots list"], warns
    ids = set()
    beat_ids = {b.get("id") for b in (beats or {}).get("beats", []) if isinstance(b, dict)} if beats else None
    for i, x in enumerate(shots):
        where = "shots[%d] %s" % (i, x.get("id") if isinstance(x, dict) else "?")
        if not isinstance(x, dict):
            errs.append(where + ": must be an object")
            continue
        sid = x.get("id")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", sid):
            errs.append(where + ": id must be letters, digits, '_' or '-'")
        elif sid in ids:
            errs.append(where + ": duplicate id")
        ids.add(sid)
        sc = str(x.get("scene") or "")
        if not (sc.startswith("Assets/") and sc.endswith(".unity")):
            errs.append(where + ": scene must be an Assets/... .unity path")
        st = x.get("setup")
        if st and not re.fullmatch(r"[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+", str(st)):
            errs.append(where + ": setup must be Namespace.Type.Method (a static void M(string) method)")
        d = x.get("duration_s")
        if isinstance(d, bool) or not isinstance(d, (int, float)) or not 0 < d <= 120:
            errs.append(where + ": duration_s must be > 0 and <= 120")
        w = x.get("warmup_s", 0)
        if isinstance(w, bool) or not isinstance(w, (int, float)) or w < 0:
            errs.append(where + ": warmup_s must be >= 0")
        tk = x.get("takes", 1)
        if isinstance(tk, bool) or not isinstance(tk, int) or not 1 <= tk <= 20:
            errs.append(where + ": takes must be 1-20")
        ts = x.get("time_scale", 1.0)
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not 0 < ts <= 4:
            errs.append(where + ": time_scale must be > 0 and <= 4")
        elif ts != 1:
            warns.append(where + ": time_scale %s (slow motion is usually done in the edit with speed)" % num(ts))
        hide = x.get("hide") or {}
        if not isinstance(hide, dict) or not isinstance(hide.get("objects", []), list):
            errs.append(where + ": hide must be {\"objects\": [...], \"cursor\": bool}")
        cam = x.get("camera") or {}
        if not isinstance(cam, dict) or ("ortho_size" in cam and (isinstance(cam["ortho_size"], bool) or
                                                                   not isinstance(cam["ortho_size"], (int, float)))):
            errs.append(where + ": camera.ortho_size must be a number (0 = leave the camera alone; Unity's "
                                "JsonUtility can't read null)")
        if beat_ids is not None and x.get("beat") and x["beat"] not in beat_ids:
            errs.append(where + ": beat %r is not in beats.json" % x["beat"])
    if beats:
        for b in beats.get("beats", []):
            for sh in (b.get("shots") or []) if isinstance(b, dict) else []:
                if sh not in ids:
                    errs.append("beats %s lists shot %r, which shots.json doesn't have" % (b.get("id"), sh))
    return errs, warns


def _project_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, "ProjectSettings")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            return None
        d = nd


def check_capture(rep, rep_path, shots=None, ffprobe=None):
    errs, warns = [], []
    if not isinstance(rep, dict) or not isinstance(rep.get("shots"), list):
        return ["capture report must be {\"shots\": [...]}"], []
    base = os.path.dirname(os.path.abspath(rep_path))
    roots = [base, _project_root(base) or base, os.getcwd()]
    ok_shots = set()
    for s in rep["shots"]:
        if not isinstance(s, dict):
            errs.append("capture report: every shot must be an object")
            continue
        sid = s.get("id")
        takes = s.get("takes") or []
        for t in takes if isinstance(takes, list) else []:
            if not isinstance(t, dict):
                errs.append("capture %s: every take must be an object" % sid)
                continue
            if t.get("status") != "ok":
                warns.append("capture %s take %s: %s %s" % (sid, t.get("take"), t.get("status"),
                                                            t.get("message") or ""))
                continue
            f = str(t.get("file") or "")
            path = next((resolve(r, f) for r in roots if f and os.path.isfile(resolve(r, f))), None)
            if not path:
                errs.append("capture %s take %s: file missing: %s" % (sid, t.get("take"), f))
                continue
            if int(t.get("errors") or 0):
                warns.append("capture %s take %s logged %s error(s)" % (sid, t.get("take"), t.get("errors")))
            want = float(t.get("duration_s") or 0) * float(t.get("fps") or 0)
            if want and int(t.get("frames") or 0) < want - 1:
                warns.append("capture %s take %s: %s frames, expected %d" % (sid, t.get("take"), t.get("frames"),
                                                                             int(want)))
            info = probe(ffprobe, path) if ffprobe else None
            vs = stream(info, "video")
            if vs:
                a, r = rate(vs.get("avg_frame_rate")), rate(vs.get("r_frame_rate"))
                if a and r and abs(a - r) > 0.01 * r:
                    warns.append("capture %s take %s looks variable-frame-rate" % (sid, t.get("take")))
            ok_shots.add(sid)
    if shots:
        for x in shots.get("shots") or []:
            if isinstance(x, dict) and x.get("id") not in ok_shots:
                errs.append("capture: shot %s has no ok take" % x.get("id"))
    if not ok_shots:
        errs.append("capture: no ok takes")
    return errs, warns


def cmd_check(a):
    if not (a.edl or a.beats or a.shots or a.capture):
        print("usage: trailer_edl.py check [edl.json] [--beats beats.json] [--shots shots.json] "
              "[--capture report.json]")
        return result(False, "nothing to check") and EXIT_USAGE
    errs, warns, done = [], [], []
    beats = shots = None
    if a.beats:
        beats, err = load_json(a.beats, "beats")
        if err:
            errs.append(err)
        else:
            e2, w2 = check_beats(beats)
            errs += e2
            warns += w2
            done.append("beats")
    if a.shots:
        shots, err = load_json(a.shots, "shots")
        if err:
            errs.append(err)
        else:
            e2, w2 = check_shots(shots, beats if not errs else None)
            errs += e2
            warns += w2
            done.append("shots")
    ffmpeg, ffprobe = find_ffmpeg()
    if a.capture:
        rep, err = load_json(a.capture, "capture report")
        if err:
            errs.append(err)
        else:
            e2, w2 = check_capture(rep, a.capture, shots, ffprobe)
            errs += e2
            warns += w2
            done.append("capture")
    if a.edl:
        e, lerr, _ = load_edl(a.edl)
        if lerr:
            errs += lerr
        else:
            check_edl_files(e, ffprobe, ffmpeg)
            errs += e["errors"]
            warns += e["warnings"]
            if beats:
                warns += _beats_vs_edl(e, beats)
            warns += snap_report(e, a.grid)
            print("timeline: %d item(s), %s s (%d frames at %s fps)" % (len(e["items"]), num(e["total"]),
                                                                       e["total_n"], num(e["fps"])))
            for it in e["items"]:
                print("  %-10s %-5s %8s-%-8s s  %s" % (it["id"], it["kind"], num(it["start"] / e["fps"]),
                                                       num(it["end"] / e["fps"]),
                                                       it["trans"] if it["d"] else ""))
            done.append("edl")
    for w in warns:
        print("WARN  " + w)
    for x in errs:
        print("ERROR " + x)
    if errs:
        return result(False, "%s: %d error(s), %d warning(s)" % ("+".join(done) or "check", len(errs), len(warns)))
    return result(True, "%s valid, %d warning(s)" % ("+".join(done), len(warns)))


def _beats_vs_edl(e, beats):
    warns = []
    bl = [b for b in beats.get("beats", []) if isinstance(b, dict)]
    if bl:
        end = float(bl[-1].get("end", 0))
        if abs(end - e["total"]) > 2.0:
            warns.append("the cut is %s s but beats.json plans %s s" % (num(e["total"]), num(end)))
        hooks = [b for b in bl if is_hook_beat(b)]
        if hooks:
            hb = hooks[0]["id"]
            first = next((it for it in e["items"] if it.get("beat") == hb), None)
            if first and first["start"] / e["fps"] > HOOK_FAIL_S:
                warns.append("the first %s clip starts at %s s (hook must land by %d s)" % (
                    hb, num(first["start"] / e["fps"]), HOOK_FAIL_S))
    return warns


# ======================================================================= command building


def intermediate(proxy=False, caps=None):
    """(encoder args, pixel format) of the build/ intermediates: ProRes 422 HQ (Apple's hardware encoder when this
    ffmpeg has it, about 5x faster; TRAILER_INTERMEDIATE=prores_ks forces software), or small H.264 for --proxy."""
    if proxy:
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p"], "yuv420p"
    want = os.environ.get("TRAILER_INTERMEDIATE", "").strip()
    if want != "prores_ks" and caps and "prores_videotoolbox" in caps["encoders"]:
        return ["-c:v", "prores_videotoolbox", "-profile:v", "hq", "-pix_fmt", "p210le"], "p210le"
    return ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"], "yuv422p10le"


def _fit(e, w, h, it, vertical):
    sf = e["scale_filter"]
    if not vertical:
        return ("scale=%d:%d:force_original_aspect_ratio=decrease:flags=%s,"
                "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black" % (w, h, sf, w, h)), False
    if it.get("layout") == "crop":
        return "scale=-2:%d:flags=%s,crop=%d:%d:(iw-ow)*%s:0" % (h, sf, w, h, num(it["vcrop"])), False
    return None, True  # blurpad needs split/overlay


def _atempo(speed):
    out, s = [], speed
    while s < 0.5 - 1e-9:
        out.append("atempo=0.5")
        s /= 0.5
    while s > 2.0 + 1e-9:
        out.append("atempo=2")
        s /= 2.0
    if abs(s - 1.0) > 1e-9:
        out.append("atempo=" + num(s))
    return out


def clip_step(e, it, probes, out, w, h, vertical=False, proxy=False, caps=None):
    """Pass 1: one video item -> an intermediate .mov of exactly it['n'] frames with stereo 48 kHz audio."""
    fps, n = e["fps"], it["n"]
    samples = int(round(n * AR / float(fps)))
    vcodec, pixfmt = intermediate(proxy, caps)
    tail = ",setsar=1,trim=end_frame=%d,setpts=PTS-STARTPTS,format=%s[v]" % (n, pixfmt)
    if it["kind"] == "card":
        argv = ["ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=%s:s=%dx%d:r=%s" % (it["bg"], w, h, num(fps)),
                "-loop", "1", "-framerate", num(fps), "-i", it["card"]]
        fc = ("[1:v]scale=%d:%d:force_original_aspect_ratio=decrease:flags=%s,format=rgba[c];"
              "[0:v][c]overlay=(W-w)/2:(H-h)/2" % (w, h, e["scale_filter"])) + tail
        fc += ";anullsrc=r=%d:cl=stereo,atrim=end_sample=%d[a]" % (AR, samples)
        files = [it["card"]]
    else:
        src = e["sources"][it["src"]]
        info = probes.get(it["src"]) if probes else None
        # unprobed (no ffprobe and no ffmpeg -i result): the command maps [0:a] and render_steps says so
        has_audio = True if info is None else stream(info, "audio") is not None
        argv = ["ffmpeg", "-hide_banner", "-y", "-i", src]
        sp = it["speed"]
        head = "[0:v]trim=start=%s:end=%s,setpts=%s,fps=%s" % (
            num(it["in"]), num(it["out"]), "PTS-STARTPTS" if sp == 1 else "(PTS-STARTPTS)/" + num(sp), num(fps))
        freeze = ",tpad=stop_mode=clone:stop_duration=%s" % num(it["freeze"] + 2.0 / fps)
        fit, blur = _fit(e, w, h, it, vertical)
        if blur:
            fc = (head + ",split=2[s0][s1];"
                  "[s0]scale=%d:%d:force_original_aspect_ratio=increase:flags=bilinear,crop=%d:%d,gblur=sigma=30[bg];"
                  "[s1]scale=%d:-2:flags=%s[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2" % (w, h, w, h, w, e["scale_filter"])
                  + freeze + tail)
        else:
            fc = head + "," + fit + freeze + tail
        if has_audio and e["game"]["enabled"] and sp >= 0.25:
            fc += (";[0:a]atrim=start=%s:end=%s,asetpts=PTS-STARTPTS,%saresample=%d,"
                   "aformat=sample_fmts=s16:channel_layouts=stereo,apad,atrim=end_sample=%d[a]" % (
                       num(it["in"]), num(it["out"]), "".join(x + "," for x in _atempo(sp)), AR, samples))
        else:
            fc += ";anullsrc=r=%d:cl=stereo,atrim=end_sample=%d[a]" % (AR, samples)
        files = [src]
    argv += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]"] + vcodec + [
        "-c:a", "pcm_s16le", "-ar", str(AR), "-ac", "2", out]
    return {"name": "clip " + it["id"], "argv": argv, "outputs": [out], "inputs": files, "cache": True}


def _ov_xy(pos, m):
    v, _, hz = pos.partition("-") if pos != "center" else ("middle", "", "center")
    x = {"left": str(m), "center": "(W-w)/2", "right": "W-w-%d" % m}[hz or "center"]
    y = {"top": str(m), "middle": "(H-h)/2", "bottom": "H-h-%d" % m}[v]
    return x, y


def join_step(e, clip_files, out, w, h, overlays, proxy=False, caps=None):
    """Pass 2: cuts (concat) and dissolves (xfade/acrossfade) in timeline order, then overlays."""
    fps, items = e["fps"], e["items"]
    argv = ["ffmpeg", "-hide_banner", "-y"]
    for f in clip_files:
        argv += ["-i", f]
    parts = []
    for k in range(len(items)):
        parts.append("[%d:v]settb=1/%s,setpts=N/(%s*TB)[v%d]" % (k, num(fps), num(fps), k))
    acc_v, acc_a, run = "v0", "0:a", items[0]["n"] if items else 0
    for k in range(1, len(items)):
        it = items[k]
        nv, na = "j%d" % k, "ja%d" % k
        if it["d"] == 0:
            # concat outputs a microsecond timebase; xfade needs both inputs on 1/fps again
            parts.append("[%s][%s][v%d][%d:a]concat=n=2:v=1:a=1[c%d][%s]" % (acc_v, acc_a, k, k, k, na))
            parts.append("[c%d]settb=1/%s,setpts=N/(%s*TB)[%s]" % (k, num(fps), num(fps), nv))
            run += it["n"]
        else:
            d = it["d"]
            parts.append("[%s][v%d]xfade=transition=%s:duration=%s:offset=%s[%s]" % (
                acc_v, k, it["trans"], num(d / float(fps)), num((run - d) / float(fps)), nv))
            parts.append("[%s][%d:a]acrossfade=ns=%d:c1=tri:c2=tri[%s]" % (
                acc_a, k, int(round(d * AR / float(fps))), na))
            run += it["n"] - d
        acc_v, acc_a = nv, na
    total_s = num(e["total_n"] / float(fps))
    base = len(clip_files)
    for j, o in enumerate(overlays):
        argv += ["-loop", "1", "-framerate", num(fps), "-t", total_s, "-i", o["image"]]
        chain = ["format=rgba"]
        if o.get("scale_w"):
            chain.append("scale=%d:-2" % o["scale_w"])
        if o["fade"] > 0:
            chain.append("fade=t=in:st=%s:d=%s:alpha=1" % (num(o["start"]), num(o["fade"])))
            chain.append("fade=t=out:st=%s:d=%s:alpha=1" % (num(o["end"] - o["fade"]), num(o["fade"])))
        parts.append("[%d:v]%s[o%d]" % (base + j, ",".join(chain), j))
        x, y = _ov_xy(o["pos"], o["margin"])
        nv = "ov%d" % j
        parts.append("[%s][o%d]overlay=x=%s:y=%s:eof_action=pass:enable='between(t,%s,%s)'[%s]" % (
            acc_v, j, x, y, num(o["start"]), num(o["end"]), nv))
        acc_v = nv
    vcodec, pixfmt = intermediate(proxy, caps)
    parts.append("[%s]trim=end_frame=%d,format=%s[vout]" % (acc_v, e["total_n"], pixfmt))
    parts.append("[%s]atrim=end_sample=%d[aout]" % (acc_a, int(round(e["total_n"] * AR / float(fps)))))
    argv += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]"] + vcodec + [
        "-c:a", "pcm_s16le", "-ar", str(AR), "-ac", "2", out]
    return {"name": "join", "argv": argv, "outputs": [out], "inputs": clip_files + [o["image"] for o in overlays]}


def mix_steps(e, picture, bdir):
    """Pass 3: game audio + music (ducked under VO) + VO + SFX -> limiter -> two-pass loudnorm."""
    fps, total = e["fps"], e["total_n"]
    S = int(round(total * AR / float(fps)))
    T = total / float(fps)
    fmt = "aresample=%d,aformat=sample_fmts=fltp:channel_layouts=stereo" % AR
    pad = "apad=whole_len=%d,atrim=end_sample=%d" % (S, S)
    argv = ["ffmpeg", "-hide_banner", "-y", "-i", picture]
    parts = ["anullsrc=r=%d:cl=stereo,atrim=end_sample=%d[bed]" % (AR, S)]
    mix = ["bed"]
    idx = 1
    if e["game"]["enabled"]:
        parts.append("[0:a]%s,volume=%sdB,%s[game]" % (fmt, num(e["game"]["gain_db"]), pad))
        mix.append("game")
    music = None
    if e["music"]:
        m = e["music"]
        argv += ["-i", m["path"]]
        length = max(1.0 / fps, T - m["at"])
        ch = ["atrim=start=%s:duration=%s" % (num(m["in"]), num(length)), "asetpts=PTS-STARTPTS", fmt]
        if m["fade_in"] > 0:
            ch.append("afade=t=in:st=0:d=%s" % num(m["fade_in"]))
        if m["fade_out"] > 0:
            ch.append("afade=t=out:st=%s:d=%s" % (num(max(0.0, length - m["fade_out"])), num(m["fade_out"])))
        ch.append("volume=%sdB" % num(m["gain_db"]))
        if m["at"] > 0:
            ch.append("adelay=delays=%d:all=1" % int(round(m["at"] * 1000)))
        parts.append("[%d:a]%s,%s[music]" % (idx, ",".join(ch), pad))
        music = "music"
        idx += 1
    vo_labels = []
    for k, v in enumerate(e["vo"]):
        argv += ["-i", v["path"]]
        parts.append("[%d:a]%s,volume=%sdB,adelay=delays=%d:all=1,%s[vo%d]" % (
            idx, fmt, num(v["gain_db"]), int(round(v["at"] * 1000)), pad, k))
        vo_labels.append("vo%d" % k)
        idx += 1
    if vo_labels:
        if len(vo_labels) > 1:
            parts.append("%samix=inputs=%d:normalize=0:duration=longest[vo]" % (
                "".join("[%s]" % x for x in vo_labels), len(vo_labels)))
        else:
            parts.append("[vo0]anull[vo]")
        if music and e["duck"]["enabled"]:
            dk = e["duck"]
            parts.append("[vo]asplit=2[vomix][vosc]")
            parts.append("[music][vosc]sidechaincompress=threshold=%s:ratio=%s:attack=%s:release=%s[musicd]" % (
                num(dk["threshold"]), num(dk["ratio"]), num(dk["attack_ms"]), num(dk["release_ms"])))
            music = "musicd"
            mix.append("vomix")
        else:
            mix.append("vo")
    if music:
        mix.append(music)
    for k, x in enumerate(e["sfx"]):
        argv += ["-i", x["path"]]
        parts.append("[%d:a]%s,volume=%sdB,adelay=delays=%d:all=1,%s[sfx%d]" % (
            idx, fmt, num(x["gain_db"]), int(round(x["at"] * 1000)), pad, k))
        mix.append("sfx%d" % k)
        idx += 1
    # latency=1: alimiter's lookahead would otherwise delay the mix against the picture
    parts.append("%samix=inputs=%d:normalize=0:duration=first,alimiter=limit=0.891:level=0:latency=1,"
                 "atrim=end_sample=%d[mix]" % ("".join("[%s]" % x for x in mix), len(mix), S))
    premix = bdir + "/premix.wav"
    master = bdir + "/master.wav"
    argv += ["-filter_complex", ";".join(parts), "-map", "[mix]", "-c:a", "pcm_f32le", "-ar", str(AR), "-ac", "2",
             premix]
    ld = e["loudness"]
    target = "loudnorm=I=%s:TP=%s:LRA=%s" % (num(ld["i"]), num(ld["tp"]), num(ld["lra"]))
    measure = ["ffmpeg", "-hide_banner", "-nostats", "-i", premix, "-af", target + ":print_format=json", "-f", "null",
               "-"]
    apply_ = ["ffmpeg", "-hide_banner", "-y", "-i", premix, "-af",
              target + ":measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}"
                       ":measured_thresh={input_thresh}:offset={target_offset}:linear=true:print_format=summary,"
                       "aresample=%d,atrim=end_sample=%d" % (AR, S),
              "-c:a", "pcm_s24le", "-ar", str(AR), "-ac", "2", master]
    return [{"name": "mix", "argv": argv, "outputs": [premix], "inputs": [picture]},
            {"name": "loudness measure", "argv": measure, "outputs": [], "parse": "loudnorm"},
            {"name": "loudness apply", "argv": apply_, "outputs": [master], "template": True}]


def overlays_for(e, w, h, scale=1.0, vertical=False):
    out = []
    for o in e["overlays"]:
        if vertical and not o.get("vertical", True):
            continue
        o2 = dict(o)
        o2["margin"] = int(round(o["margin"] * scale))
        info = png_info(resolve(e["root"], o["image"]))
        if info:
            ow = int(round(info[0] * scale))
            maxw = w - 2 * o2["margin"]
            if ow > maxw:
                ow = maxw
            if ow != info[0]:
                o2["scale_w"] = ow - ow % 2
        out.append(o2)
    return out


def caption_overlays(e, w, h):
    """Burned-in captions for vertical cuts: captions/png/cue-NNN.png per SRT cue (TrailerCards renders
    them), placed above the bottom 20 % safe zone."""
    srt = e["captions"]["srt"]
    if not srt:
        return [], "no captions.srt"
    path = resolve(e["root"], srt)
    if not os.path.isfile(path):
        return [], "captions.srt %s is missing" % srt
    cues = read_srt(path)
    out, missing = [], []
    for k, (a, b, _text) in enumerate(cues, 1):
        rel = "%s/cue-%03d.png" % (e["captions"]["png_dir"].rstrip("/"), k)
        if not os.path.isfile(resolve(e["root"], rel)):
            missing.append(rel)
            continue
        out.append({"image": rel, "start": a, "end": min(b, e["total"]), "pos": "bottom-center",
                    "margin": int(round(h * 0.22)), "fade": 0.0})
    if missing:
        return [], "%d caption PNG(s) missing (e.g. %s); render them with TrailerCards.Render" % (len(missing),
                                                                                              missing[0])
    return [o for o in out if o["end"] > o["start"]], None


def render_steps(e, probes, proxy=False, vertical=False, caps=None):
    """Ordered steps for a render. Paths are relative to the EDL folder (commands run there)."""
    if vertical:
        w, h, bdir, scale = 1080, 1920, "build/vertical", 1.0
    elif proxy:
        w, h, bdir, scale = e["w"] // 4 * 2, e["h"] // 4 * 2, "build/proxy", 0.5
    else:
        w, h, bdir, scale = e["w"], e["h"], "build", 1.0
    steps, clip_files = [], []
    for it in e["items"]:
        out = "%s/clips/%s.mov" % (bdir, it["id"])
        steps.append(clip_step(e, it, probes, out, w, h, vertical=vertical, proxy=proxy, caps=caps))
        clip_files.append(out)
    ovs = overlays_for(e, w, h, scale, vertical)
    notes = []
    unprobed = sorted({it["src"] for it in e["items"] if it["kind"] == "clip" and
                       e["game"]["enabled"] and (probes or {}).get(it["src"]) is None})
    if unprobed:
        notes.append("source(s) %s could not be probed (no ffprobe/ffmpeg result): their game audio is assumed "
                     "to exist; a source without audio will fail the clip step" % ", ".join(unprobed))
    if vertical and any(p in e["captions"]["burn_in_for"] for p in ("shorts", "tiktok")):
        caps_ov, why = caption_overlays(e, w, h)
        if why:
            notes.append("captions not burned in: " + why)
        ovs += caps_ov
    picture = bdir + "/picture.mov"
    steps.append(join_step(e, clip_files, picture, w, h, ovs, proxy=proxy, caps=caps))
    if vertical:
        return steps, notes
    steps += mix_steps(e, picture, bdir)
    if proxy:
        steps.append({"name": "proxy mux", "argv": [
            "ffmpeg", "-hide_banner", "-y", "-i", picture, "-i", bdir + "/master.wav", "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "build/proxy.mp4"],
            "outputs": ["build/proxy.mp4"], "announce": True})
    else:
        steps.append({"name": "master mux", "argv": [
            "ffmpeg", "-hide_banner", "-y", "-i", picture, "-i", bdir + "/master.wav", "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "pcm_s24le", "build/master.mov"], "outputs": ["build/master.mov"], "announce": True})
    return steps, notes


X_720 = (1280, 720)  # X's frame for accounts without a subscription (export --x-720)


def encode_args(e, p, encoder="x264", preset="slow", size=None):
    spec = PLATFORMS[p]
    fps = e["fps"]
    g = max(1, int(round(min(fps, spec["max_fps"]) / 2.0)))
    w, h = size or (spec["w"], spec["h"])
    vf = "scale=%d:%d:flags=%s,setsar=1" % (w, h, "neighbor" if e["scale_filter"] == "neighbor" else "lanczos")
    if fps > spec["max_fps"]:
        vf += ",fps=%d" % spec["max_fps"]
    vf += ",format=yuv420p"
    if encoder == "videotoolbox":
        v = ["-c:v", "h264_videotoolbox", "-profile:v", "high", "-b:v", spec["vt_rate"], "-maxrate", spec["maxrate"],
             "-bufsize", spec["bufsize"]]
    else:
        v = ["-c:v", "libx264", "-profile:v", "high", "-preset", preset, "-crf", str(spec["crf"]), "-maxrate",
             spec["maxrate"], "-bufsize", spec["bufsize"]]
    return ["-vf", vf] + v + ["-pix_fmt", "yuv420p", "-g", str(g), "-bf", "2", "-flags", "+cgop",
                              "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                              "-c:a", "aac", "-b:a", spec["ab"], "-ar", str(AR), "-ac", "2",
                              "-movflags", "+faststart"]


def export_steps(e, p, probes, encoder="x264", preset="slow", caps=None, x_720=False):
    out = "exports/%s-%s.mp4" % (e["id"], p)
    steps, notes = [], []
    spec = PLATFORMS[p]
    size = X_720 if (x_720 and p == "x") else None
    if p == "loop":
        start = e["poster_at"] or 0.0
        dur = min(8.0, max(1.0, e["total"] - start))
        enc = caps["encoders"] if caps else {"libvpx-vp9"}
        steps.append({"name": "loop webm", "argv": [
            "ffmpeg", "-hide_banner", "-y", "-ss", num(start), "-t", num(dur), "-i", "build/master.mov", "-an",
            "-vf", "fps=30,scale=640:-2:flags=lanczos"] + (
            ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "34", "-row-mt", "1"] if "libvpx-vp9" in enc else
            ["-c:v", "libvpx", "-b:v", "1M", "-crf", "10"]) + ["exports/%s-loop.webm" % e["id"]],
            "outputs": ["exports/%s-loop.webm" % e["id"]], "announce": True})
        steps.append({"name": "loop gif", "argv": [
            "ffmpeg", "-hide_banner", "-y", "-ss", num(start), "-t", num(dur), "-i", "build/master.mov",
            "-filter_complex", "fps=15,scale=480:-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
            "exports/%s-loop.gif" % e["id"]], "outputs": ["exports/%s-loop.gif" % e["id"]], "announce": True})
        return steps, notes
    if spec["vertical"]:
        vsteps, notes = render_steps(e, probes, vertical=True, caps=caps)
        steps += vsteps
        steps.append({"name": "export " + p, "argv": [
            "ffmpeg", "-hide_banner", "-y", "-i", "build/vertical/picture.mov", "-i", "build/master.wav",
            "-map", "0:v", "-map", "1:a"] + encode_args(e, p, encoder, preset) + [out],
            "outputs": [out], "announce": True})
    else:
        steps.append({"name": "export " + p, "argv": [
            "ffmpeg", "-hide_banner", "-y", "-i", "build/master.mov", "-map", "0:v", "-map", "0:a"] +
            encode_args(e, p, encoder, preset, size=size) + [out], "outputs": [out], "announce": True})
        if size:
            notes.append("%s exported at %dx%d (--x-720)" % (p, size[0], size[1]))
    if spec.get("poster"):
        steps.append(poster_step(e, e["poster_at"] if e["poster_at"] is not None else _default_poster(e)))
    if spec.get("srt") and e["captions"]["srt"]:
        steps.append({"name": "captions " + p, "copy": [e["captions"]["srt"], "exports/%s.srt" % e["id"]],
                      "outputs": ["exports/%s.srt" % e["id"]]})
    return steps, notes


def _default_poster(e):
    """First clip frame after the opening seconds (posters avoid text)."""
    for it in e["items"]:
        if it["kind"] == "clip" and it["end"] / float(e["fps"]) > 2.0:
            return max(it["start"] / float(e["fps"]), 2.0) + 0.5 / e["fps"]
    return 0.0


def poster_step(e, at):
    return {"name": "poster", "argv": ["ffmpeg", "-hide_banner", "-y", "-ss", num(at), "-i", "build/master.mov",
                                       "-frames:v", "1", "-vf", "scale=1920:1080:flags=lanczos,format=rgb24",
                                       "exports/poster.png"],
            "outputs": ["exports/poster.png"], "announce": True}


# ======================================================================= running


def _stat_key(root, files):
    h = []
    for f in files:
        p = resolve(root, f)
        try:
            st = os.stat(p)
            h.append("%s:%d:%d" % (f, st.st_size, int(st.st_mtime)))
        except OSError:
            h.append("%s:missing" % f)
    return h


def cache_key(e, step):
    payload = json.dumps({"argv": step["argv"], "files": _stat_key(e["root"], step.get("inputs", []))},
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _need_ffmpeg():
    ff, fp = find_ffmpeg()
    if not ff:
        print("ffmpeg not found. " + FFMPEG_HINT)
        print("RESULT: FAIL ffmpeg not found")
        return None, None
    return ff, fp


def _announce(root, rel):
    print("TRAILER_OUTPUT: " + resolve(root, rel))


def run_steps(e, steps, ffmpeg, jobs=1, quiet=False):
    """Run steps in order (pass-1 clips in parallel); returns (ok, message)."""
    root = e["root"]

    def argv_of(st):
        return [ffmpeg if st["argv"][0] == "ffmpeg" else st["argv"][0]] + st["argv"][1:]

    def run_one(st):
        for o in st.get("outputs", []):
            os.makedirs(os.path.dirname(resolve(root, o)) or root, exist_ok=True)
        if "copy" in st:
            src, dst = (resolve(root, x) for x in st["copy"])
            if not os.path.isfile(src):
                return False, "%s: %s missing" % (st["name"], st["copy"][0])
            shutil.copyfile(src, dst)
            return True, ""
        key = cache_key(e, st) if st.get("cache") else None
        out0 = resolve(root, st["outputs"][0]) if st.get("outputs") else None
        if key and out0 and os.path.isfile(out0):
            try:
                with open(out0 + ".key") as f:
                    if f.read().strip() == key:
                        return True, "cached"
            except OSError:
                pass
        if key and out0:
            # drop the old key first: an interrupted render must not leave a partial output marked as cached
            try:
                os.remove(out0 + ".key")
            except FileNotFoundError:
                pass
        r = subprocess.run(argv_of(st), cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            tail = "\n".join((r.stderr or "").strip().splitlines()[-12:])
            return False, "%s failed (exit %d):\n%s" % (st["name"], r.returncode, tail)
        if key and out0:
            with open(out0 + ".key", "w") as f:
                f.write(key + "\n")
        st["_stderr"] = r.stderr
        return True, ""

    clips = [s for s in steps if s.get("cache")]
    rest = [s for s in steps if not s.get("cache")]
    if clips:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            for st, (ok, msg) in zip(clips, ex.map(run_one, clips)):
                if not quiet:
                    print("  %-22s %s" % (st["name"], "ok" if ok and not msg else (msg if ok else "FAILED")))
                if not ok:
                    return False, msg
    measured = None
    for st in rest:
        if st.get("template"):
            if not measured:
                return False, "loudness measurement missing"
            argv = []
            for a in st["argv"]:
                if measured.get("silent") and "print_format=summary," in a:
                    a = a.split("print_format=summary,", 1)[1]  # nothing to normalize: keep only resample + trim
                for k, v in measured.items():
                    a = a.replace("{%s}" % k, str(v))
                argv.append(a)
            st = dict(st, argv=argv)
        ok, msg = run_one(st)
        if not quiet:
            print("  %-22s %s" % (st["name"], "ok" if ok else "FAILED"))
        if not ok:
            return False, msg
        if st.get("parse") == "loudnorm":
            measured = parse_loudnorm(st.get("_stderr", ""))
            if measured is None:
                return False, "could not read loudnorm measurement"
            if float(measured["input_i"]) < -70:
                print("WARN  the mix is silent (%s LUFS); loudness left as is" % measured["input_i"])
                measured["silent"] = True
        if st.get("announce"):
            for o in st["outputs"]:
                _announce(root, o)
    return True, ""


def parse_loudnorm(stderr):
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr or "")
    if not blocks:
        return None
    try:
        d = json.loads(blocks[-1])
    except ValueError:
        return None
    keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    out = {}
    for k in keys:
        v = str(d.get(k, "0")).strip()
        try:
            f = float(v)
            if math.isinf(f) or math.isnan(f):
                raise ValueError
        except ValueError:
            v = {"input_i": "-99", "input_tp": "-99", "input_lra": "0", "input_thresh": "-99",
                 "target_offset": "0"}[k]
        out[k] = v
    return out


# ======================================================================= subcommands


def cmd_doctor(_a):
    ff, fp = find_ffmpeg()
    if not ff:
        print("ffmpeg: not found (looked at $TRAILER_FFMPEG, PATH, /opt/homebrew/bin, "
              "/opt/homebrew/opt/ffmpeg-full/bin, /usr/local/bin)")
        print(FFMPEG_HINT)
        print("RESULT: FAIL ffmpeg not found")
        return EXIT_NO_FFMPEG
    caps = ffmpeg_caps(ff)
    print("ffmpeg:  %s" % ff)
    print("ffprobe: %s" % (fp or "not found"))
    print("version: %s" % caps["version"])
    missing = [f for f in REQUIRED_FILTERS if f not in caps["filters"]] + \
              [x for x in REQUIRED_ENCODERS if x not in caps["encoders"]]
    for f in REQUIRED_FILTERS:
        print("  %-8s filter  %s" % ("ok" if f in caps["filters"] else "MISSING", f))
    for x in REQUIRED_ENCODERS:
        print("  %-8s encoder %s" % ("ok" if x in caps["encoders"] else "MISSING", x))
    for f in OPTIONAL_FILTERS:
        print("  %-8s filter  %s (optional%s)" % ("ok" if f in caps["filters"] else "absent", f,
                                                  "; text and captions are PNG overlays anyway"))
    for x in OPTIONAL_ENCODERS:
        print("  %-8s encoder %s (optional)" % ("ok" if x in caps["encoders"] else "absent", x))
    if not fp:
        missing.append("ffprobe")
    if missing:
        print(FFMPEG_HINT)
        return result(False, "missing: " + ", ".join(missing))
    return result(True, "ffmpeg ready (%s)" % caps["version"].replace("ffmpeg version ", "").split(" ")[0])


def _load_checked(path, need_files=True):
    e, lerr, _ = load_edl(path)
    if lerr:
        for x in lerr:
            print("ERROR " + x)
        return None, None
    ff, fp = find_ffmpeg()
    probes = check_edl_files(e, fp, ff) if need_files else {}
    if e["errors"]:
        for x in e["errors"]:
            print("ERROR " + x)
        return None, None
    return e, probes


def cmd_plan(a):
    e, lerr, _ = load_edl(a.edl)
    if lerr:
        for x in lerr:
            print("ERROR " + x)
        return result(False, "EDL unreadable")
    if e["errors"]:
        for x in e["errors"]:
            print("ERROR " + x)
        return result(False, "%d error(s) in the EDL" % len(e["errors"]))
    ff, fp = find_ffmpeg()
    caps = ffmpeg_caps(ff) if ff else None
    probes = {}
    for sid, rel in e["sources"].items():
        p = resolve(e["root"], rel)
        probes[sid] = probe_source(fp, ff, p) if os.path.isfile(p) else None
    if a.platform:
        steps, notes = [], []
        for p in a.platform:
            s, n = export_steps(e, p, probes, preset=a.x264_preset, caps=caps, x_720=getattr(a, "x_720", False))
            steps += s
            notes += n
    else:
        steps, notes = render_steps(e, probes, proxy=a.proxy, caps=caps)
    for s in steps:
        if s.get("cache"):
            s["key"] = cache_key(e, s)
    if a.json:
        print(json.dumps({"id": e["id"], "fps": e["fps"], "total_frames": e["total_n"], "total_s": e["total"],
                          "timeline": [{"id": it["id"], "start": it["start"], "end": it["end"], "frames": it["n"],
                                        "transition": it["trans"], "transition_frames": it["d"]}
                                       for it in e["items"]],
                          "steps": [{k: s[k] for k in ("name", "argv", "outputs", "key", "copy") if k in s}
                                    for s in steps], "notes": notes}, indent=1))
    else:
        for s in steps:
            print("# " + s["name"] + (" (cache %s)" % s["key"] if s.get("key") else ""))
            if "copy" in s:
                print("cp %s %s" % tuple(s["copy"]))
            else:
                print(" ".join(_shq(x) for x in s["argv"]))
        for n in notes:
            print("NOTE  " + n)
    return result(True, "%d step(s), %s s timeline" % (len(steps), num(e["total"])))


def _shq(s):
    return s if re.fullmatch(r"[A-Za-z0-9_./:=+,-]+", s) else "'" + s.replace("'", "'\\''") + "'"


def cmd_render(a):
    ff, _fp = _need_ffmpeg()
    if not ff:
        return EXIT_NO_FFMPEG
    e, probes = _load_checked(a.edl)
    if e is None:
        return result(False, "fix the EDL errors first (trailer_edl.py check)")
    for w in e["warnings"]:
        print("WARN  " + w)
    steps, notes = render_steps(e, probes, proxy=a.proxy, caps=ffmpeg_caps(ff))
    for n in notes:
        print("NOTE  " + n)
    print("render %s: %d items, %s s%s" % (e["id"], len(e["items"]), num(e["total"]), " (proxy)" if a.proxy else ""))
    ok, msg = run_steps(e, steps, ff, jobs=a.jobs)
    if not ok:
        print(msg)
        return result(False, "render failed: " + msg.splitlines()[0])
    out = "build/proxy.mp4" if a.proxy else "build/master.mov"
    return result(True, "rendered %s (%s s, %d frames)" % (out, num(e["total"]), e["total_n"]))


def cmd_export(a):
    ff, _fp = _need_ffmpeg()
    if not ff:
        return EXIT_NO_FFMPEG
    e, probes = _load_checked(a.edl)
    if e is None:
        return result(False, "fix the EDL errors first (trailer_edl.py check)")
    plats = list(dict.fromkeys((a.platform or []) + (e["exports"] if a.all or not a.platform else [])))
    if not plats:
        return result(False, "no platforms (use --platform or list exports in the EDL)")
    if not os.path.isfile(resolve(e["root"], "build/master.mov")):
        return result(False, "build/master.mov is missing: run trailer_edl.py render first")
    caps = ffmpeg_caps(ff)
    if a.encoder == "videotoolbox" and "h264_videotoolbox" not in caps["encoders"]:
        return result(False, "this ffmpeg has no h264_videotoolbox encoder")
    vmax = a.max if a.max else e["vertical_max"]
    done = []
    for p in plats:
        if PLATFORMS[p]["vertical"] and e["total"] > vmax + 1e-6:
            print("ERROR %s: the cut is %s s, longer than %s s for vertical (use --max, or cut a social EDL)" % (
                p, num(e["total"]), num(vmax)))
            return result(False, "%s export too long" % p)
        steps, notes = export_steps(e, p, probes, encoder=a.encoder, preset=a.x264_preset, caps=caps,
                                    x_720=getattr(a, "x_720", False))
        for n in notes:
            print("NOTE  " + n)
        print("export %s" % p)
        ok, msg = run_steps(e, steps, ff, jobs=a.jobs)
        if not ok:
            print(msg)
            return result(False, "%s export failed" % p)
        done.append(p)
    return result(True, "exported %s to %s" % (", ".join(done), resolve(e["root"], "exports")))


# ----------------------------------------------------------------------- qc


def _mp4_faststart(path):
    """True when the moov atom comes before mdat (top-level atoms)."""
    try:
        with open(path, "rb") as f:
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return False
                size = int.from_bytes(hdr[:4], "big")
                t = hdr[4:8]
                if t == b"moov":
                    return True
                if t == b"mdat":
                    return False
                if size == 1:
                    size = int.from_bytes(f.read(8), "big")
                    f.seek(size - 16, 1)
                elif size == 0:
                    return False
                else:
                    f.seek(size - 8, 1)
    except OSError:
        return False


def _ff_run(ff, args):
    """(stdout, stderr) of an ffmpeg run."""
    r = subprocess.run([ff, "-hide_banner", "-nostats"] + args, capture_output=True, text=True)
    return r.stdout or "", r.stderr or ""


def _ff_stderr(ff, args, stdout=False):
    out, err = _ff_run(ff, args)
    return out if stdout else err


def loudness(ff, path):
    err = _ff_stderr(ff, ["-i", path, "-vn", "-filter_complex", "ebur128=peak=true", "-f", "null", "-"])
    tail = err[err.rfind("Summary:"):] if "Summary:" in err else err
    i = re.search(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", tail)
    tp = re.search(r"Peak:\s+(-?[\d.]+|-inf)\s+dBFS", tail)
    f = lambda m: (float(m.group(1)) if m and m.group(1) != "-inf" else None)  # noqa: E731
    return f(i), f(tp)


def video_scan(ff, path, first_s=2.0):
    """(black segments starting in the first first_s s, freeze segments, flash times) of a video."""
    black = re.findall(r"black_start:\s*([\d.]+)", _ff_stderr(ff, [
        "-t", num(first_s), "-i", path, "-an", "-vf", "blackdetect=d=0.05:pix_th=0.10", "-f", "null", "-"]))
    # one decode: freezedetect logs to stderr, the YAVG metadata goes to stdout
    out, err = _ff_run(ff, ["-i", path, "-an", "-vf",
                            "scale=160:-2,freezedetect=n=0.003:d=2,signalstats,"
                            "metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"])
    freezes = [float(x) for x in re.findall(r"freeze_start:\s*([\d.]+)", err)]
    ts, ys, cur = [], [], None
    for line in out.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            cur = float(m.group(1))
            continue
        m = re.search(r"YAVG=([\d.]+)", line)
        if m and cur is not None:
            ts.append(cur)
            ys.append(float(m.group(1)))
    jumps = [ts[k] for k in range(1, len(ys)) if abs(ys[k] - ys[k - 1]) > 0.2 * 255]
    flashes = []
    for k, t in enumerate(jumps):
        n = sum(1 for u in jumps[k:] if u - t < 1.0)
        if n > 3 and (not flashes or t - flashes[-1] > 1.0):
            flashes.append(t)
    return [float(b) for b in black], freezes, flashes


def qc_file(ff, fp, path, platform, e=None):
    checks = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    info = probe(fp, path)
    if info is None:
        add("probe", "fail", "ffprobe can't read the file")
        return checks, {}
    vs, au = stream(info, "video"), stream(info, "audio")
    spec = PLATFORMS.get(platform)
    if vs is None:
        add("video", "fail", "no video stream")
    else:
        w, h = vs.get("width"), vs.get("height")
        if spec:
            okdims = (w, h) == (spec["w"], spec["h"]) or (platform == "x" and (w, h) == (1280, 720)) or \
                     (platform == "youtube" and (w, h) == (3840, 2160))
            add("dimensions", "ok" if okdims else "fail", "%sx%s (want %dx%d)" % (w, h, spec["w"], spec["h"]))
        fr = rate(vs.get("avg_frame_rate")) or rate(vs.get("r_frame_rate")) or 0
        want = min(e["fps"], 60) if e else None
        if fr > 60.5:
            add("fps", "fail", "%s fps (60 at most)" % num(fr))
        elif want and abs(fr - want) > 0.05:
            add("fps", "fail", "%s fps (EDL %s)" % (num(fr), num(want)))
        elif platform == "steam" and round(fr) not in (30, 60):
            add("fps", "fail", "%s fps (Steam wants 30 or 60)" % num(fr))
        else:
            add("fps", "ok", "%s fps" % num(fr))
        prof = str(vs.get("profile"))
        add("codec", "fail" if vs.get("codec_name") != "h264" else ("ok" if prof == "High" else "warn"),
            "%s %s (H.264 High wanted)" % (vs.get("codec_name"), prof))
        add("pix_fmt", "ok" if vs.get("pix_fmt") == "yuv420p" else "fail", str(vs.get("pix_fmt")))
        if e:
            nf = vs.get("nb_frames")
            try:
                nf = int(nf)
            except (TypeError, ValueError):
                nf = None
            exp = e["total_n"] if e["fps"] <= 60 else int(round(e["total"] * 60))
            if nf is not None:
                add("duration", "ok" if abs(nf - exp) <= 1 else "fail", "%d frames (EDL %d)" % (nf, exp))
    if au is None:
        add("audio", "fail", "no audio stream")
    else:
        okau = au.get("codec_name") == "aac" and au.get("profile") == "LC" and str(au.get("sample_rate")) == "48000" \
            and int(au.get("channels") or 0) == 2
        add("audio", "ok" if okau else "fail", "%s %s %s Hz %s ch" % (au.get("codec_name"), au.get("profile"),
                                                                     au.get("sample_rate"), au.get("channels")))
    add("faststart", "ok" if _mp4_faststart(path) else "fail", "moov before mdat")
    target_i, target_tp = (e["loudness"]["i"], e["loudness"]["tp"]) if e else (-14.0, -1.0)
    li, tp = loudness(ff, path) if au is not None else (None, None)
    meas = {"integrated_lufs": li, "true_peak_dbtp": tp}
    if li is None:
        add("loudness", "fail", "no measurable audio")
    else:
        add("loudness", "ok" if abs(li - target_i) <= 1.0 else "fail", "%s LUFS (target %s +/- 1)" % (
            num(round(li, 1)), num(target_i)))
        if tp is not None:
            st = "ok" if tp <= target_tp + 0.05 else ("warn" if tp <= target_tp + 0.5 else "fail")
            add("true peak", st, "%s dBTP (max %s)" % (num(round(tp, 1)), num(target_tp)))
    if vs is not None:
        black, freezes, flashes = video_scan(ff, path)
        add("black start", "fail" if black else "ok",
            ("black at %s s in the first 2 s" % ", ".join(num(b) for b in black)) if black else "no black in 0-2 s")
        add("freeze", "warn" if freezes else "ok",
            ("frozen picture >= 2 s at %s s" % ", ".join(num(round(f, 2)) for f in freezes)) if freezes else "none")
        add("flashes", "warn" if flashes else "ok",
            ("more than 3 large luma flashes per second at %s s" % ", ".join(num(round(f, 2)) for f in flashes))
            if flashes else "none")
    return checks, meas


def cmd_qc(a):
    ff, fp = _need_ffmpeg()
    if not ff:
        return EXIT_NO_FFMPEG
    e = None
    if a.edl:
        e, lerr, _ = load_edl(a.edl)
        if lerr or e["errors"]:
            for x in (lerr or e["errors"]):
                print("ERROR " + x)
            return result(False, "EDL has errors")
    target = os.path.abspath(a.target)
    if os.path.isdir(target):
        files = sorted(os.path.join(target, f) for f in os.listdir(target) if f.endswith((".mp4", ".mov")))
    elif os.path.isfile(target):
        files = [target]
    else:
        return result(False, "%s does not exist" % a.target)
    if not files:
        return result(False, "no .mp4/.mov files in %s" % a.target)
    report = {"files": [], "edl": os.path.abspath(a.edl) if a.edl else None}
    fails = warns = 0
    rule_checks = []
    if e:
        if e["items"] and e["items"][0]["kind"] == "card" and e["items"][0]["n"] > frames(1.0, e["fps"]):
            rule_checks.append({"name": "hook rule", "status": "fail", "detail": "opens on a card longer than 1 s"})
        if a.beats:
            b, err = load_json(a.beats, "beats")
            if not err:
                hooks = [x for x in b.get("beats", []) if isinstance(x, dict) and is_hook_beat(x)]
                if hooks:
                    hs = float(hooks[0].get("start", 0))
                    st = "fail" if hs > HOOK_FAIL_S else ("warn" if hs > HOOK_WARN_S else "ok")
                    rule_checks.append({"name": "hook by 10 s", "status": st, "detail": "hook at %s s" % num(hs)})
    for f in files:
        m = re.search(r"-(steam|youtube|x|shorts|tiktok)\.mp4$", os.path.basename(f))
        plat = a.platform or (m.group(1) if m else None)
        checks, meas = qc_file(ff, fp, f, plat, e)
        checks += rule_checks
        report["files"].append({"file": f, "platform": plat, "checks": checks, "measured": meas})
        print("%s (%s)" % (os.path.basename(f), plat or "generic"))
        for c in checks:
            print("  %-4s %-12s %s" % (c["status"].upper(), c["name"], c["detail"]))
            fails += c["status"] == "fail"
            warns += c["status"] == "warn"
    if e:
        qpath = os.path.join(e["root"], "review", "qc.json")
    elif os.path.basename(target if os.path.isdir(target) else os.path.dirname(target)) == "exports":
        base = target if os.path.isdir(target) else os.path.dirname(target)
        qpath = os.path.join(os.path.dirname(base), "review", "qc.json")
    else:
        qpath = os.path.join(target if os.path.isdir(target) else os.path.dirname(target), "qc.json")
    report["failures"], report["warnings"] = fails, warns
    write_json(qpath, report)
    print("qc report: %s" % qpath)
    if fails:
        return result(False, "%d file(s), %d failed check(s), %d warning(s)" % (len(files), fails, warns))
    return result(True, "%d file(s) pass, %d warning(s)" % (len(files), warns))


# ----------------------------------------------------------------------- sheet / poster


def _review_dir(path):
    d = os.path.dirname(os.path.abspath(path))
    if os.path.basename(d) in ("exports", "build"):
        return os.path.join(os.path.dirname(d), "review")
    return os.path.join(d, "review")


def cmd_sheet(a):
    ff, fp = _need_ffmpeg()
    if not ff:
        return EXIT_NO_FFMPEG
    if not os.path.isfile(a.video):
        return result(False, "%s does not exist" % a.video)
    out = os.path.abspath(a.out_dir) if a.out_dir else _review_dir(a.video)
    os.makedirs(out, exist_ok=True)
    written = []
    if a.first5:
        dst = os.path.join(out, "first5.png")
        r = subprocess.run([ff, "-hide_banner", "-y", "-t", "5", "-i", a.video, "-vf",
                            "fps=2,scale=480:-2,tile=5x2", "-frames:v", "1", dst], capture_output=True, text=True)
        if r.returncode != 0:
            return result(False, "first5 sheet failed: " + (r.stderr or "").strip().splitlines()[-1:][0])
        written.append(dst)
    else:
        dur = media_duration(probe(fp, a.video)) or 0
        per = a.cols * a.rows
        n = max(1, int(math.ceil(dur * a.fps / per)))
        prefix = a.prefix or ("sheet" if os.path.basename(os.path.dirname(os.path.abspath(a.video))) in
                              ("exports", "build") else "sheet-" + os.path.splitext(os.path.basename(a.video))[0])
        r = subprocess.run([ff, "-hide_banner", "-y", "-i", a.video, "-vf",
                            "fps=%s,scale=%d:-2,tile=%dx%d" % (num(a.fps), a.width, a.cols, a.rows),
                            "-start_number", "1", os.path.join(out, prefix + "-%02d.png")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return result(False, "sheet failed: " + (r.stderr or "").strip().splitlines()[-1:][0])
        written += [os.path.join(out, "%s-%02d.png" % (prefix, k)) for k in range(1, n + 1)
                    if os.path.isfile(os.path.join(out, "%s-%02d.png" % (prefix, k)))]
    if a.scenes:
        o = _ff_stderr(ff, ["-i", a.video, "-an", "-vf", "scdet=threshold=10,metadata=print:key=lavfi.scd.time:file=-",
                            "-f", "null", "-"], stdout=True)
        times = [float(x) for x in re.findall(r"lavfi\.scd\.time=([\d.]+)", o)]
        for t in times:
            print("SCENE: %s" % num(round(t, 3)))
        sj = os.path.join(out, os.path.splitext(os.path.basename(a.video))[0] + "-scenes.json")
        write_json(sj, {"file": os.path.abspath(a.video), "scene_changes": times})
    for w in written:
        print("TRAILER_OUTPUT: " + w)
    return result(True, "%d sheet(s) in %s" % (len(written), out))


def cmd_poster(a):
    ff, _fp = _need_ffmpeg()
    if not ff:
        return EXIT_NO_FFMPEG
    e, _probes = _load_checked(a.edl, need_files=False)
    if e is None:
        return result(False, "fix the EDL errors first")
    if not os.path.isfile(resolve(e["root"], "build/master.mov")):
        return result(False, "build/master.mov is missing: run trailer_edl.py render first")
    at = a.at if a.at is not None else (e["poster_at"] if e["poster_at"] is not None else _default_poster(e))
    it = item_at(e, at)
    if it and it["kind"] == "card":
        print("WARN  %s s is on card %s: Steam posters should be a gameplay frame without text" % (num(at), it["id"]))
    ok, msg = run_steps(e, [poster_step(e, at)], ff)
    if not ok:
        print(msg)
        return result(False, "poster failed")
    return result(True, "poster at %s s -> exports/poster.png (1920x1080, avoid text)" % num(at))


# ----------------------------------------------------------------------- captions


def read_srt(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        txt = f.read()
    cues = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = block.strip().splitlines()
        k = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if k is None:
            continue
        a, b = lines[k].split("-->")
        cues.append((parse_hms(a), parse_hms(b.split()[0] if b.split() else b), "\n".join(lines[k + 1:])))
    return cues


MAX_LINE, MAX_CHARS, MIN_DUR, MAX_DUR = 42, 84, 1.0, 6.0


def wrap2(text):
    """<= 2 balanced lines of <= 42 chars (a single overlong word stays on its own line)."""
    text = " ".join(text.split())
    if len(text) <= MAX_LINE:
        return [text]
    words = text.split(" ")
    best = None
    for k in range(1, len(words)):
        l1, l2 = " ".join(words[:k]), " ".join(words[k:])
        score = (max(len(l1), len(l2)) > MAX_LINE, abs(len(l1) - len(l2)))
        if best is None or score < best[0]:
            best = (score, [l1, l2])
    return best[1]


def tokens_from_transcript(data):
    words = data.get("words") if isinstance(data, dict) else data
    if not isinstance(words, list):
        raise ValueError("transcript has no words list (ElevenLabs transcribe output)")
    out = []
    for w in words:
        if not isinstance(w, dict):
            continue
        typ = w.get("type", "word")
        text = str(w.get("text") or "").strip()
        if typ == "spacing" or not text:
            continue
        try:
            a, b = float(w["start"]), float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if typ == "audio_event":
            text = "[" + text.strip("()[]") + "]"
        out.append({"text": text, "start": a, "end": max(b, a), "event": typ == "audio_event"})
    return out


def cues_from_tokens(toks):
    cues, cur = [], []

    def flush():
        if cur:
            cues.append([cur[0]["start"], cur[-1]["end"], " ".join(t["text"] for t in cur)])
            cur.clear()

    def text_of(ts):
        return " ".join(x["text"] for x in ts)

    for t in toks:
        if cur:
            gap = t["start"] - cur[-1]["end"]
            long_ = t["end"] - cur[0]["start"] > MAX_DUR
            sentence = re.search(r"[.!?]$", cur[-1]["text"]) and cur[-1]["end"] - cur[0]["start"] >= MIN_DUR
            if long_ or gap > 0.8 or sentence or t["event"] or cur[-1]["event"]:
                flush()
            elif len(text_of(cur + [t])) > MAX_CHARS:
                # split the phrase in two balanced halves (after a comma when possible), not "…" + an orphan word
                best = None
                for k in range(1, len(cur) + 1):
                    left, right = cur[:k], cur[k:] + [t]
                    if len(text_of(left)) > MAX_CHARS or len(text_of(right)) > MAX_CHARS:
                        continue
                    comma = bool(re.search(r"[,;:]$", left[-1]["text"]))
                    score = abs(len(text_of(left)) - len(text_of(right))) - (15 if comma else 0)
                    if best is None or score < best[0]:
                        best = (score, k)
                k = best[1] if best else len(cur)
                rest = cur[k:]
                del cur[k:]
                flush()
                cur.extend(rest)
        cur.append(t)
    flush()
    return _settle(cues)


def _settle(cues):
    """Enforce 1-6 s per cue without overlapping the next one."""
    for k, c in enumerate(cues):
        nxt = cues[k + 1][0] if k + 1 < len(cues) else None
        if c[1] - c[0] < MIN_DUR:
            c[1] = c[0] + MIN_DUR if nxt is None else min(c[0] + MIN_DUR, nxt)
        if c[1] - c[0] > MAX_DUR:
            c[1] = c[0] + MAX_DUR
        if nxt is not None and c[1] > nxt:
            c[1] = nxt
    return cues


def split_balanced(words, limit=MAX_CHARS):
    """Words -> chunks of <= limit chars, halving (at a comma when close) instead of leaving an orphan word."""
    if len(" ".join(words)) <= limit or len(words) < 2:
        return [words]
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        score = abs(len(a) - len(b)) - (15 if re.search(r"[,;:]$", words[k - 1]) else 0)
        if best is None or score < best[0]:
            best = (score, k)
    k = best[1]
    return split_balanced(words[:k], limit) + split_balanced(words[k:], limit)


def cues_from_script(text):
    """VO script lines `@12.5 Every run rewrites the map.` (seconds on the trailer timeline)."""
    marks = []
    for line in text.splitlines():
        m = re.match(r"^\s*[-*]?\s*@(\d+(?:\.\d+)?)\s+(.+?)\s*$", line)
        if m:
            marks.append((float(m.group(1)), m.group(2)))
    if not marks:
        raise ValueError("no cue lines like `@12.5 Text` in the script")
    marks.sort()
    cues = []
    for k, (t, s) in enumerate(marks):
        nxt = marks[k + 1][0] if k + 1 < len(marks) else None
        # long lines become balanced chunks of <= 84 chars, timed at 0.33 s/word + 0.5 s
        chunks = split_balanced(s.split())
        at = t
        for ch in chunks:
            d = min(MAX_DUR, max(MIN_DUR, 0.5 + 0.33 * len(ch)))
            end = at + d if nxt is None else min(at + d, nxt)
            cues.append([at, end, " ".join(ch)])
            at = end
    return _settle(cues)


def cmd_srt(a):
    src = a.source
    try:
        if src.lower().endswith(".json"):
            data, err = load_json(src, "transcript")
            if err:
                return result(False, err)
            cues = cues_from_tokens(tokens_from_transcript(data))
        else:
            with open(src, "r", encoding="utf-8") as f:
                cues = cues_from_script(f.read())
    except (OSError, ValueError) as ex:
        return result(False, str(ex))
    cues = [[c[0] + a.offset, c[1] + a.offset, c[2]] for c in cues if c[2].strip()]
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bad = 0
    with open(out, "w", encoding="utf-8") as f:
        for k, (s, en, t) in enumerate(cues, 1):
            lines = wrap2(t)
            bad += len(lines) > 2 or any(len(x) > MAX_LINE for x in lines)
            f.write("%d\n%s --> %s\n%s\n\n" % (k, hms(s), hms(en), "\n".join(lines)))
    print("TRAILER_OUTPUT: " + out)
    if a.cards:
        root = _project_root(os.path.dirname(out))
        png_dir = os.path.join(os.path.dirname(out), "png")
        cards = {"font": a.font or "", "w": 1080, "h": 300,
                 "out_dir": os.path.relpath(png_dir, root) if root else png_dir,
                 "cards": [{"id": "cue-%03d" % k, "text": "\n".join(wrap2(t)), "size": 56, "color": "#ffffff",
                            "bg": "#000000A0", "align": "center", "valign": "middle", "margin": 24}
                           for k, (_s, _e, t) in enumerate(cues, 1)]}
        write_json(a.cards, cards)
        print("cards for TrailerCards.Render: %s (PNGs -> %s)" % (os.path.abspath(a.cards), cards["out_dir"]))
    if bad:
        return result(False, "%d caption(s) exceed 2 lines of 42 characters (shorten the words)" % bad)
    return result(True, "%d caption(s) -> %s" % (len(cues), out))


# ======================================================================= CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("doctor")
    p = sub.add_parser("check")
    p.add_argument("edl", nargs="?")
    p.add_argument("--beats")
    p.add_argument("--shots")
    p.add_argument("--capture")
    p.add_argument("--grid", help="beat_grid.py output to report cut snapping against")
    p = sub.add_parser("plan")
    p.add_argument("edl")
    p.add_argument("--json", action="store_true")
    p.add_argument("--proxy", action="store_true")
    p.add_argument("--platform", action="append", choices=sorted(PLATFORMS))
    p.add_argument("--x264-preset", default="slow")
    p.add_argument("--x-720", dest="x_720", action="store_true", help="plan the x export at 1280x720")
    p = sub.add_parser("render")
    p.add_argument("edl")
    p.add_argument("--proxy", action="store_true")
    p.add_argument("--jobs", type=int, default=max(1, min(4, (os.cpu_count() or 2) // 2)))
    p = sub.add_parser("export")
    p.add_argument("edl")
    p.add_argument("--platform", action="append", choices=sorted(PLATFORMS))
    p.add_argument("--all", action="store_true", help="every platform listed in the EDL's exports")
    p.add_argument("--encoder", choices=("x264", "videotoolbox"), default="x264")
    p.add_argument("--x264-preset", default="slow")
    p.add_argument("--max", type=float, help="longest vertical cut in seconds (default 60)")
    p.add_argument("--x-720", dest="x_720", action="store_true",
                   help="export the x platform at 1280x720 (X's size for accounts without a subscription)")
    p.add_argument("--jobs", type=int, default=2)
    p = sub.add_parser("qc")
    p.add_argument("target", help="exports folder or one file")
    p.add_argument("--edl")
    p.add_argument("--beats")
    p.add_argument("--platform", choices=sorted(k for k in PLATFORMS if k != "loop"))
    p = sub.add_parser("sheet")
    p.add_argument("video")
    p.add_argument("--fps", type=float, default=1.0)
    p.add_argument("--cols", type=int, default=6)
    p.add_argument("--rows", type=int, default=5)
    p.add_argument("--width", type=int, default=320)
    p.add_argument("--first5", action="store_true", help="10 frames of the first 5 s (the muted-scroll sheet)")
    p.add_argument("--scenes", action="store_true", help="list scene changes (shot logging of long takes)")
    p.add_argument("--out-dir")
    p.add_argument("--prefix")
    p = sub.add_parser("srt")
    p.add_argument("source", help="ElevenLabs transcript .json or a VO script .md with `@<seconds> text` lines")
    p.add_argument("--out", required=True)
    p.add_argument("--offset", type=float, default=0.0, help="seconds added to every cue (VO clip position)")
    p.add_argument("--cards", help="also write a cards.json for TrailerCards (vertical burn-in PNGs)")
    p.add_argument("--font", help="TMP font asset for --cards")
    p = sub.add_parser("poster")
    p.add_argument("edl")
    p.add_argument("--at", type=float)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        print("RESULT: FAIL no subcommand")
        return EXIT_USAGE
    fn = {"doctor": cmd_doctor, "check": cmd_check, "plan": cmd_plan, "render": cmd_render, "export": cmd_export,
          "qc": cmd_qc, "sheet": cmd_sheet, "srt": cmd_srt, "poster": cmd_poster}[a.cmd]
    try:
        return fn(a)
    except Exception as ex:  # last resort: every run ends with a RESULT line, even on a bug
        import traceback
        traceback.print_exc()
        return result(False, "%s crashed: %s: %s" % (a.cmd, type(ex).__name__, ex))


if __name__ == "__main__":
    sys.exit(main())
