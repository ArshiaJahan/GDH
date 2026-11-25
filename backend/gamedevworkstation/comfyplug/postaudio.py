"""Sound post-processing: seamless loops and loudness normalising (needs numpy and ffmpeg).

- measure(path): duration, integrated LUFS (EBU R128 via ffmpeg ebur128), true peak, sample peak, RMS.
  Clips shorter than ~1.2 s are tiled back to back before measuring, so the LUFS is the K-weighted energy mean
  over the clip as it is (ends included), which a plain ebur128 run cannot give for clips under 400 ms.
- make_loop(src, out, ...): pick the steadiest stretch, crossfade its end into its start, normalise, verify the join.
- verify_loop(path): numeric check of the wrap-around join.
- normalize_file / normalize_rules: gain-only loudness changes, never clipping, with a backup of the originals.
Everything works on 16-bit PCM WAV and keeps sample rate and channel count.
"""
import fnmatch
import json
import math
import os
import re
import shutil
import subprocess
import wave

from . import client

PEAK_CEILING_DB = -1.2   # peak ceiling used when a gain would clip (a little under -1 dBTP)


def _np():
    import numpy as np
    return np


# ---------------------------------------------------------------- wav io
def read_wav(path):
    """-> (sample_rate, channels, float32 array shape (n, ch) in -1..1)"""
    np = _np()
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise client.ComfyError(f"{path}: only 16-bit PCM wav is supported")
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return rate, ch, x.reshape(-1, ch)


def write_wav(path, rate, x):
    np = _np()
    client.ensure_parent(path)
    x = np.asarray(x, dtype=np.float64)
    pcm = np.clip(np.round(x * 32768.0), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _db(v):
    return 20 * math.log10(v) if v > 1e-9 else -120.0


# ---------------------------------------------------------------- measuring
def _ebur128(path, tile_samples=None):
    ffmpeg = client.find_ffmpeg()
    af = "ebur128=peak=true"
    if tile_samples:
        af = f"aloop=loop=-1:size={tile_samples},atrim=0:2.4," + af
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", path, "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    mi = re.search(r"\n\s*I:\s*(-?[\d.]+|-inf)\s*LUFS", tail)
    mp = re.search(r"True peak:\s*\n\s*Peak:\s*(-?[\d.]+|-inf)\s*dBFS", tail)
    return (float(mi.group(1)) if mi else -70.0), (float(mp.group(1)) if mp else None)


def measure(path):
    """-> dict(duration, rate, channels, lufs, true_peak, peak, rms, tiled)"""
    np = _np()
    rate, ch, x = read_wav(path)
    n = len(x)
    dur = n / rate
    peak = _db(float(np.abs(x).max())) if n else -120.0
    rms = _db(float(np.sqrt((x.astype(np.float64) ** 2).mean()))) if n else -120.0
    tiled = dur < 1.2
    lufs, tp = _ebur128(path, n if tiled else None)
    if tp is None or tp < peak:
        tp = peak
    return {"duration": round(dur, 3), "rate": rate, "channels": ch, "lufs": round(lufs, 1),
            "true_peak": round(tp, 1), "peak": round(peak, 1), "rms": round(rms, 1), "tiled": tiled}


# ---------------------------------------------------------------- gain
def apply_gain(path, gain_db, out=None):
    """Scale a wav by gain_db (refuses a gain that would clip). Writes to out (default in place)."""
    np = _np()
    rate, ch, x = read_wav(path)
    y = x.astype(np.float64) * (10 ** (gain_db / 20))
    if float(np.abs(y).max()) > 0.99997:
        raise client.ComfyError(f"{path}: gain {gain_db:+.2f} dB would clip")
    write_wav(out or path, rate, y)


def gain_for(m, target_lufs, ceiling_db=PEAK_CEILING_DB):
    """Gain (dB) that brings measurement m to target_lufs, limited so the peak stays under ceiling_db.
    -> (gain_db, peak_limited)"""
    want = target_lufs - m["lufs"]
    room = ceiling_db - max(m["true_peak"], m["peak"])
    if want > room:
        return round(room - 0.005, 2), True
    return round(want, 2), False


def fit_gain(path, target_lufs, ceiling_db=PEAK_CEILING_DB, tmp=None):
    """Find the gain for `path` that lands on target_lufs (re-measuring a scaled copy, because the -70 LUFS
    absolute gate makes very quiet material read differently once it is louder), capped by the peak ceiling.
    -> (gain_db, peak_limited, before_measure)"""
    before = measure(path)
    g, lim = gain_for(before, target_lufs, ceiling_db)
    room = ceiling_db - max(before["true_peak"], before["peak"]) - 0.005
    tmp = tmp or path + ".fit.tmp.wav"
    try:
        for _ in range(3):
            if lim:
                break
            apply_gain(path, g, tmp)
            err = target_lufs - measure(tmp)["lufs"]
            if abs(err) < 0.15:
                break
            g = round(g + err, 2)
            if g > room:
                g, lim = round(room, 2), True
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return g, lim, before


def normalize_file(path, target_lufs, out=None, ceiling_db=PEAK_CEILING_DB, backup_dir=None):
    """Gain-only normalise to target_lufs. Returns dict(before, after, gain, peak_limited)."""
    g, limited, before = fit_gain(path, target_lufs, ceiling_db)
    if backup_dir:
        dst = os.path.join(backup_dir, os.path.basename(path))
        if not os.path.exists(dst):          # never overwrite an earlier backup
            client.ensure_parent(dst)
            shutil.copy2(path, dst)
    apply_gain(path, g, out)
    after = measure(out or path)
    return {"before": before, "after": after, "gain": g, "peak_limited": limited}


def fit_clip(src, out, max_ms=None, fade_ms=20.0):
    """Copy a one-shot, optionally cutting it to max_ms, and end it with a raised-cosine fade-out of fade_ms
    (so a cut never clicks). Python helper for picking a take; no CLI."""
    np = _np()
    rate, ch, x = read_wav(src)
    if max_ms:
        x = x[: int(rate * max_ms / 1000)]
    y = x.astype(np.float64)
    f = min(len(y), int(rate * fade_ms / 1000))
    if f > 1:
        y[-f:] *= (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, f)))[:, None]
    write_wav(out, rate, y)
    return out


# ---------------------------------------------------------------- loops
def _envelope_db(mono, rate, frame_ms=20):
    np = _np()
    f = max(1, int(rate * frame_ms / 1000))
    n = len(mono) // f
    e = np.sqrt((mono[: n * f].reshape(n, f) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(e, 1e-6)), f


def _steadiest_start(mono, rate, win, skip):
    """Start sample of the window (win seconds) whose loudness is the steadiest: smallest spread (max - min) of the
    100 ms loudness envelope, plus a little of the 20 ms envelope's jitter. Ignores `skip` s at both ends."""
    np = _np()
    hop, blk = int(0.02 * rate), int(0.1 * rate)
    c = np.concatenate([[0.0], np.cumsum(mono.astype(np.float64) ** 2)])
    starts = np.arange(0, len(mono) - blk, hop)
    env = 10 * np.log10(np.maximum((c[starts + blk] - c[starts]) / blk, 1e-12))     # dB, 100 ms blocks every 20 ms
    wf = int(win / 0.02)
    lo, hi = int(skip / 0.02), len(env) - wf - int(skip / 0.02)
    if hi <= lo:
        return max(0, int(skip * rate))
    best, bi = 1e9, lo
    for i in range(lo, hi + 1):
        seg = env[i:i + wf]
        score = float(seg.max() - seg.min() + 0.3 * seg.std())
        if score < best:
            best, bi = score, i
    return bi * hop


def _wobble(path):
    """Std-dev (dB) of the 50 ms loudness envelope: how steady a loop is (lower = steadier)."""
    rate, _, x = read_wav(path)
    env, _ = _envelope_db(x[:, 0].astype(float), rate, 50)
    return round(float(env.std()), 2)


def verify_loop(path, edge_ms=10):
    """Numeric join check of a loop file. Compares the wrap step (last sample -> first sample) with the file's
    normal sample-to-sample steps, the RMS and coarse spectrum of the first and last edge_ms, and the worst step
    across the seam. ok = wrap step within 1.5x the file's 99.9th percentile step, seam no rougher than the
    rest of the file, edge levels within 1.5 dB."""
    np = _np()
    rate, ch, x = read_wav(path)
    m = x[:, 0].astype(np.float64)
    e = max(8, int(rate * edge_ms / 1000))
    first, last = m[:e], m[-e:]
    step = abs(float(m[0] - m[-1]))
    steps = np.abs(np.diff(m))
    p999 = float(np.percentile(steps, 99.9)) + 1e-9
    r1, r2 = float(np.sqrt((first ** 2).mean())), float(np.sqrt((last ** 2).mean()))

    def bands(s):
        sp = np.abs(np.fft.rfft(s * np.hanning(len(s)))) ** 2
        return np.array([_db(math.sqrt(v.sum() / len(v) + 1e-18)) for v in np.array_split(sp, 8)])

    sd = float(np.abs(bands(first) - bands(last)).mean())
    seam_max = float(np.abs(np.diff(np.concatenate([m[-e:], m[:e]]))).max())
    res = {"wrap_step": round(step, 5), "step_p99.9": round(p999, 5), "wrap_vs_p99.9": round(step / p999, 2),
           "seam_max_step": round(seam_max, 5), "file_max_step": round(float(steps.max()), 5),
           "edge_rms_first_db": round(_db(r1), 1), "edge_rms_last_db": round(_db(r2), 1),
           "edge_rms_diff_db": round(abs(_db(r1) - _db(r2)), 2), "edge_band_diff_db": round(sd, 1)}
    res["ok"] = bool(step <= 1.5 * p999 and seam_max <= 1.05 * float(steps.max()) + 1e-9
                     and res["edge_rms_diff_db"] < 1.5)
    return res


def make_loop(src, out, seconds=4.0, crossfade=0.5, lufs=-22.0, skip=0.3, ceiling_db=PEAK_CEILING_DB, highpass=30.0):
    """Turn a raw sound (length >= seconds + crossfade + ~0.5 s + 2*skip; 6 s is comfortable) into a seamless
    loop of `seconds`: mono, remove DC and rumble below `highpass` Hz, pick the steadiest stretch, crossfade its
    tail into its head (the loop end is picked up to 160 ms early where the tail best matches the head), normalise to `lufs` (gain only,
    capped by the peak ceiling), write 16-bit mono WAV at the source sample rate and verify the join.
    Returns a report dict (including `join`, the verify_loop result)."""
    np = _np()
    ffmpeg = client.find_ffmpeg()
    client.ensure_parent(out)
    tmp = out + ".tmp.wav"
    r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-af", f"highpass=f={highpass}",
                        "-c:a", "pcm_s16le", tmp], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise client.ComfyError("ffmpeg failed:\n" + r.stderr[-1500:])
    try:
        rate, _, x = read_wav(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    s = x[:, 0].astype(np.float64)
    T, X = int(seconds * rate), int(crossfade * rate)
    sl = int(0.16 * rate)                           # loop length may shrink by up to 160 ms to find a waveform match
    need = T + X
    if len(s) < need + 2 * int(skip * rate):
        raise client.ComfyError(f"source is {len(s) / rate:.2f}s, need at least {need / rate + 2 * skip:.2f}s "
                                f"for a {seconds}s loop with a {crossfade}s crossfade")
    a = _steadiest_start(s, rate, need / rate, skip)
    seg = s[a:a + need]
    head = seg[:X]                                  # the loop starts by fading in this, from the end
    hn = head / (np.linalg.norm(head) + 1e-12)
    best, Tb = -2.0, T
    for Tc in range(T, T - sl - 1, -2):
        cand = seg[Tc:Tc + X]                       # natural continuation of a body ending at Tc
        c = float(np.dot(cand, hn) / (np.linalg.norm(cand) + 1e-12))
        if c > best + 1e-6:
            best, Tb = c, Tc
    tail = seg[Tb:Tb + X]
    t = np.linspace(0, np.pi / 2, X)
    if best > 0.7:                                  # similar waveforms: linear fade keeps the level
        fi = t / (np.pi / 2)
        fo = 1 - fi
    else:                                           # unrelated waveforms: equal power
        fi, fo = np.sin(t), np.cos(t)
    mix = head * fi + tail * fo
    body = seg[X:Tb]
    y = np.concatenate([mix, body])
    y -= y.mean()
    write_wav(out, rate, y[:, None])
    g, limited, _ = fit_gain(out, lufs, ceiling_db)
    apply_gain(out, g)
    after = measure(out)
    return {"out": out, "seconds": round(len(y) / rate, 3), "rate": rate, "source_window_start_s": round(a / rate, 2),
            "loop_shortened_ms": round((T - Tb) / rate * 1000, 1), "match_corr": round(best, 2), "gain_db": g,
            "peak_limited": limited, "level_wobble_db": _wobble(out), "lufs": after["lufs"], "true_peak": after["true_peak"], "join": verify_loop(out)}


# ---------------------------------------------------------------- normalising whole trees
def normalize_rules(rules_path, root=None, backup=None, report=None, dry_run=False, toys=()):
    """rules json: {"root": ".../Games", "backup": "...", "ceiling_db": -1.2, "classes": {"impact": -16, ...},
    "toys": {"<id>": {"main": ["pop_*"], "offset_main": -2.0, "rules": [["pattern", "class" or lufs], ...]}}}
    A file takes the first matching rule; files matching a toy's "main" patterns get offset_main dB added to
    their target. Files with no rule are reported and left alone. Returns the list of result rows."""
    with open(rules_path, encoding="utf-8") as f:
        cfg = json.load(f)
    root = root or cfg["root"]
    backup = backup or cfg.get("backup")
    ceiling = cfg.get("ceiling_db", PEAK_CEILING_DB)
    classes = cfg["classes"]
    rows = []
    for toy, tc in cfg["toys"].items():
        if toys and toy not in toys:
            continue
        adir = os.path.join(root, toy, "Audio")
        for fn in sorted(os.listdir(adir)):
            if not fn.lower().endswith(".wav"):
                continue
            tgt = None
            for pat, cls in tc["rules"]:
                if fnmatch.fnmatch(fn, pat):
                    tgt = classes[cls] if isinstance(cls, str) else float(cls)
                    kind = cls if isinstance(cls, str) else "custom"
                    break
            if tgt is None:
                rows.append({"toy": toy, "file": fn, "skipped": "no rule"})
                continue
            main = any(fnmatch.fnmatch(fn, p) for p in tc.get("main", []))
            ceil = ceiling
            if main:                                   # the most frequent sound sits a little under the rare ones,
                tgt += tc.get("offset_main", -2.0)     # also when the peak ceiling (not the LUFS target) is what
                ceil += tc.get("offset_main", -2.0)    # limits the gain
            if kind == "soft":
                ceil += cfg.get("soft_ceiling_offset", -3.0)
            path = os.path.join(adir, fn)
            if dry_run:
                m = measure(path)
                g, lim = gain_for(m, tgt, ceil)
                rows.append({"toy": toy, "file": fn, "class": kind, "main": main, "target": tgt, "ceiling": ceil,
                             "before": m, "gain": g, "peak_limited": lim})
                continue
            res = normalize_file(path, tgt, ceiling_db=ceil,
                                 backup_dir=os.path.join(backup, toy) if backup else None)
            rows.append({"toy": toy, "file": fn, "class": kind, "main": main, "target": tgt, "ceiling": ceil, **res})
    if report:
        write_report(rows, report, dry_run)
    return rows


def write_report(rows, path, dry_run=False):
    out = ["# Sound batch: loudness before / after", "",
           "Gain-only pass (`comfyplug normalize`), sample rate and channels untouched. LUFS is integrated EBU R128; clips "
           "under 1.2 s are tiled before measuring, so their LUFS is the energy mean over the clip. TP = true peak "
           "(dBTP), RMS = whole-file RMS (dBFS). `lim` = gain capped by the peak ceiling (-1.2 dB; main sounds -3.2, soft sounds a further -3), so the LUFS target "
           "was not reached (short, spiky clips cannot reach -16 LUFS by gain alone without clipping). Judged by numbers only, not by ear.", ""]
    toys = []
    for r in rows:
        if r["toy"] not in toys:
            toys.append(r["toy"])
    for toy in toys:
        rs = [r for r in rows if r["toy"] == toy]
        meas = [r for r in rs if "before" in r]
        if meas:
            b = [r["before"]["lufs"] for r in meas]
            a = [r["after"]["lufs"] if r.get("after") else r["before"]["lufs"] + r["gain"] for r in meas]
            out.append(f"## {toy}: {min(b):.1f}..{max(b):.1f} LUFS -> {min(a):.1f}..{max(a):.1f} LUFS")
        else:
            out.append(f"## {toy}")
        out += ["", "| file | class (target) | dur s | LUFS before | TP before | RMS before | gain dB | LUFS after | TP after | RMS after | note |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in rs:
            if "skipped" in r:
                out.append(f"| {r['file']} | - | | | | | | | | | {r['skipped']} |")
                continue
            b, af = r["before"], r.get("after")
            note = ("main" if r["main"] else "") + (" lim" if r["peak_limited"] else "")
            out.append(f"| {r['file']} | {r['class']} ({r['target']:.1f}, pk {r['ceiling']:.1f}) | {b['duration']} | {b['lufs']} | {b['true_peak']} "
                       f"| {b['rms']} | {r['gain']:+.1f} | {af['lufs'] if af else ''} | {af['true_peak'] if af else ''} "
                       f"| {af['rms'] if af else ''} | {note.strip()} |")
        out.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
