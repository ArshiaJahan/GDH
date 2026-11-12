#!/usr/bin/env python3
"""Beat grid for a trailer's music: tempo, beat times, downbeats, onsets and sections -> JSON.

Usage:
  beat_grid.py <music.wav|.mp3|...> [--bpm N] [--sections composition_plan.json|beats.json] [--out FILE]

WAV is read with the standard library; other formats are decoded by ffmpeg (exit 3 if it is missing).
Method: RMS-flux onset envelope (~11.6 ms hop), tempo by autocorrelation over 70-180 BPM (mild prior
around 120), grid phase by maximizing the onset sum, then each beat is snapped to its local onset peak
and the grid is refit by least squares (sub-frame accuracy); downbeat = the strongest of the 4 phases.
`--bpm` skips tempo estimation (phase and downbeats are still estimated).

Output (default: beats_grid.json next to the music file):
  {"bpm": 120.0, "beats": [...], "downbeats": [...], "onsets": [...], "sections": [...], "confidence": 0.9}
Last line: RESULT: OK|FAIL. FAIL when confidence < 0.4 without --bpm (pass --bpm, or cut to the section
lengths of the composition plan instead). Python 3.9+ standard library only.
"""
import argparse
import array
import json
import math
import os
import re
import subprocess
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _trailer_common import EXIT_NO_FFMPEG, EXIT_USAGE, FFMPEG_HINT, find_ffmpeg, load_json, result, write_json  # noqa: E402

HOP_S = 256.0 / 22050.0     # ~11.6 ms analysis hop
MIN_BPM, MAX_BPM = 70.0, 180.0
MIN_CONFIDENCE = 0.4


# ------------------------------------------------------------------ audio input


def read_wav_mono(path):
    """(samples as floats in -1..1, sample rate) of a PCM WAV, mixed to mono."""
    with wave.open(path, "rb") as w:
        ch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        a = array.array("h")
        a.frombytes(raw)
        scale = 32768.0
    elif width == 4:
        a = array.array("i")
        a.frombytes(raw)
        scale = 2147483648.0
    elif width == 1:
        a = array.array("h", [(b - 128) << 8 for b in raw])
        scale = 32768.0
    elif width == 3:
        a = array.array("i", [int.from_bytes(raw[k:k + 3], "little", signed=True) for k in range(0, len(raw), 3)])
        scale = 8388608.0
    else:
        raise ValueError("unsupported WAV sample width %d" % width)
    if sys.byteorder == "big" and width in (2, 4):
        a.byteswap()
    if ch == 1:
        return [x / scale for x in a], sr
    mono = [0.0] * (len(a) // ch)
    for c in range(ch):
        part = a[c::ch]
        for k in range(len(mono)):
            mono[k] += part[k]
    s = scale * ch
    return [x / s for x in mono], sr


def decode_ffmpeg(path, ffmpeg, sr=22050):
    r = subprocess.run([ffmpeg, "-hide_banner", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "s16le",
                        "-"], capture_output=True)
    if r.returncode != 0:
        raise ValueError("ffmpeg could not decode %s: %s" % (path, r.stderr.decode(errors="replace").strip()[-300:]))
    a = array.array("h")
    a.frombytes(r.stdout[: len(r.stdout) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    return [x / 32768.0 for x in a], sr


# ------------------------------------------------------------------ analysis


def onset_envelope(x, sr):
    """Half-wave rectified RMS difference per hop; returns (envelope, hop seconds)."""
    hop = max(1, int(round(sr * HOP_S)))
    rms = []
    for k in range(0, len(x) - hop + 1, hop):
        seg = x[k:k + hop]
        rms.append(math.sqrt(sum(v * v for v in seg) / hop))
    env = [0.0] + [max(0.0, rms[k] - rms[k - 1]) for k in range(1, len(rms))]
    return env, hop / float(sr)


def _autocorr(env, lag):
    n = len(env) - lag
    return sum(env[k] * env[k + lag] for k in range(n)) / n if n > 0 else 0.0


def estimate_period(env, hop):
    """Best beat period in frames (float) by autocorrelation of the mean-removed envelope, plus the
    normalized peak (0..1) as a periodicity measure."""
    m = sum(env) / len(env)
    c = [v - m for v in env]
    var = sum(v * v for v in c) / len(c) or 1e-12
    lo, hi = int(math.floor(60.0 / MAX_BPM / hop)), int(math.ceil(60.0 / MIN_BPM / hop))
    ac = {lag: _autocorr(c, lag) for lag in range(max(1, lo - 1), hi + 2)}
    best, best_score = None, -1e9
    for lag in range(lo, hi + 1):
        bpm = 60.0 / (lag * hop)
        prior = math.exp(-0.5 * (math.log2(bpm / 120.0) / 1.0) ** 2)
        score = ac[lag] * (0.5 + 0.5 * prior)
        if score > best_score:
            best, best_score = lag, score
    # parabolic refinement of the peak
    a, b, cc = ac.get(best - 1, 0.0), ac[best], ac.get(best + 1, 0.0)
    den = a - 2 * b + cc
    off = 0.5 * (a - cc) / den if den < 0 else 0.0
    return best + max(-0.5, min(0.5, off)), max(0.0, min(1.0, b / var))


def _peak_near(env, center, radius):
    lo, hi = max(0, int(center - radius)), min(len(env) - 1, int(center + radius) + 1)
    if lo > hi:
        return None, 0.0
    k = max(range(lo, hi + 1), key=lambda i: env[i])
    if env[k] <= 0:
        return None, 0.0
    a = env[k - 1] if k > 0 else 0.0
    c = env[k + 1] if k + 1 < len(env) else 0.0
    den = a - 2 * env[k] + c
    off = 0.5 * (a - c) / den if den < 0 else 0.0
    return k + max(-0.5, min(0.5, off)), env[k]


def fit_grid(env, period):
    """(phase frames, refined period frames, beat frame list, confidence 0..1)."""
    n = len(env)
    best_phase, best_sum = 0, -1.0
    for ph in range(int(math.ceil(period))):
        s, t = 0.0, float(ph)
        while t < n:
            s += env[int(t)]
            t += period
        if s > best_sum:
            best_phase, best_sum = ph, s
    # snap each grid beat to its local peak, then least-squares refit t = t0 + k * P
    pts, k, t = [], 0, float(best_phase)
    radius = max(1.0, 0.12 * period)
    while t < n:
        p, h = _peak_near(env, t, radius)
        if p is not None:
            pts.append((k, p, h))
        k += 1
        t = best_phase + k * period
    t0, per = float(best_phase), period
    if len(pts) >= 4:
        top = sorted(h for _k, _p, h in pts)
        cut = top[len(top) // 4]  # ignore the weakest quarter (off-beat bleed, rests)
        use = [(kk, p) for kk, p, h in pts if h >= cut]
        if len(use) >= 3:
            mk = sum(kk for kk, _p in use) / len(use)
            mp = sum(p for _kk, p in use) / len(use)
            sxx = sum((kk - mk) ** 2 for kk, _p in use)
            if sxx > 0:
                per = sum((kk - mk) * (p - mp) for kk, p in use) / sxx
                t0 = mp - per * mk
    beats = []
    k = 0
    while t0 + k * per < n:
        if t0 + k * per >= 0:
            beats.append(t0 + k * per)
        k += 1
    return t0, per, beats, grid_confidence(env, beats, per)


def grid_confidence(env, beats, per):
    """0..1: how much more onset energy sits near the grid (beats, or beats + eighths for busy music)
    than a random grid of the same density would catch. Noise scores ~0, a click track ~1."""
    tot = max(1e-12, sum(env))
    win = max(1, int(round(0.06 * per)))
    best = 0.0
    for pts in (beats, beats + [b + per / 2.0 for b in beats]):
        taken = set()
        for b in pts:
            c = int(round(b))
            taken.update(range(max(0, c - win), min(len(env), c + win + 1)))
        share = sum(env[i] for i in taken) / tot
        expect = len(taken) / float(len(env))
        best = max(best, (share - expect) / max(1e-9, 1.0 - expect))
    return max(0.0, min(1.0, best))


def downbeat_phase(env, beats):
    sums = [0.0] * 4
    for k, b in enumerate(beats):
        i = int(round(b))
        if 0 <= i < len(env):
            sums[k % 4] += max(env[max(0, i - 1):i + 2])
    return max(range(4), key=lambda p: sums[p])


def onsets(env, hop, thresh_ratio=0.3):
    peak = max(env) if env else 0.0
    out = []
    for k in range(1, len(env) - 1):
        if env[k] > thresh_ratio * peak and env[k] >= env[k - 1] and env[k] > env[k + 1]:
            out.append(round((k + 0.5) * hop, 4))
    return out


def sections_from(path, total):
    data, err = load_json(path, "sections")
    if err:
        raise ValueError(err)
    out = []
    if isinstance(data, dict) and isinstance(data.get("chunks") or data.get("sections"), list):
        t = 0.0
        for k, c in enumerate(data.get("chunks") or data.get("sections")):
            if not isinstance(c, dict):
                continue
            try:
                d = float(c.get("duration_ms") or 0) / 1000.0
            except (TypeError, ValueError):
                d = 0.0
            m = re.match(r"^\s*\[([^\]]{1,100})\]", str(c.get("text") or c.get("section_name") or ""))
            name = m.group(1) if m else str(c.get("section_name") or "section-%d" % (k + 1))
            out.append({"name": name, "start": round(t, 4), "end": round(t + d, 4)})
            t += d
    elif isinstance(data, dict) and isinstance(data.get("beats"), list):
        for b in data["beats"]:
            if not isinstance(b, dict):
                continue
            out.append({"name": str(b.get("id")), "start": float(b.get("start", 0)), "end": float(b.get("end", 0))})
    else:
        raise ValueError("%s is neither a composition plan (chunks) nor a beats.json" % path)
    return out


def analyze(samples, sr, bpm=None):
    env, hop = onset_envelope(samples, sr)
    if len(env) < 16 or max(env) <= 0:
        return {"bpm": bpm, "beats": [], "downbeats": [], "onsets": [], "confidence": 0.0,
                "duration_s": round(len(samples) / float(sr), 4)}
    period = 60.0 / bpm / hop if bpm else estimate_period(env, hop)[0]
    t0, per, beats, conf = fit_grid(env, period)
    if bpm:
        per = 60.0 / bpm / hop  # the user's tempo is authoritative; keep the fitted phase
        beats = [t0 + k * per for k in range(int((len(env) - t0) / per) + 1) if t0 + k * per >= 0]
        conf = grid_confidence(env, beats, per)
    ph = downbeat_phase(env, beats)
    to_s = lambda f: round((f + 0.5) * hop, 4)  # noqa: E731  frame center
    beat_s = [to_s(b) for b in beats]
    return {"bpm": round(60.0 / (per * hop), 2), "beats": beat_s, "downbeats": beat_s[ph::4],
            "onsets": onsets(env, hop), "confidence": round(conf, 3),
            "duration_s": round(len(samples) / float(sr), 4)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music")
    ap.add_argument("--bpm", type=float, help="known tempo (skips estimation)")
    ap.add_argument("--sections", help="ElevenLabs composition plan JSON or beats.json, for named sections")
    ap.add_argument("--out", help="output JSON (default: beats_grid.json next to the music)")
    a = ap.parse_args(argv)
    if a.bpm is not None and not 30 <= a.bpm <= 300:
        print("--bpm must be 30-300")
        print("RESULT: FAIL bad --bpm")
        return EXIT_USAGE
    if not os.path.isfile(a.music):
        return result(False, "%s does not exist" % a.music)
    try:
        try:
            samples, sr = read_wav_mono(a.music)
        except (wave.Error, EOFError, ValueError):
            ff, _ = find_ffmpeg()
            if not ff:
                print("%s is not a PCM WAV and ffmpeg is needed to decode it. %s" % (a.music, FFMPEG_HINT))
                print("RESULT: FAIL ffmpeg not found")
                return EXIT_NO_FFMPEG
            samples, sr = decode_ffmpeg(a.music, ff)
        r = analyze(samples, sr, a.bpm)
        r["sections"] = sections_from(a.sections, r["duration_s"]) if a.sections else []
    except (OSError, ValueError) as ex:
        return result(False, str(ex))
    r["source"] = os.path.abspath(a.music)
    r["bpm_given"] = a.bpm is not None
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.music)), "beats_grid.json")
    write_json(out, r)
    print("bpm %s, %d beats, %d downbeats, %d onsets, confidence %s" % (
        r["bpm"], len(r["beats"]), len(r["downbeats"]), len(r["onsets"]), r["confidence"]))
    if r["downbeats"]:
        print("first downbeat %s s; grid written to %s" % (r["downbeats"][0], out))
    if not r["beats"]:
        return result(False, "no beats found (silent or too short)")
    if r["confidence"] < MIN_CONFIDENCE and not a.bpm:
        return result(False, "low confidence %s: pass --bpm, or cut to the composition plan's sections" %
                      r["confidence"])
    return result(True, "%s BPM, %d beats -> %s" % (r["bpm"], len(r["beats"]), out))


if __name__ == "__main__":
    sys.exit(main())
