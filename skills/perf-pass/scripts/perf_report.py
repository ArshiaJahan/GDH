#!/usr/bin/env python3
"""Compare a perf run against budgets and a baseline (PerfProbe CSV or [PERF] log lines). Python 3.8+ stdlib only.

Usage:
  perf_report.py --after AFTER [--baseline BASE] [--label L] [--budget KEY<=V]... [--budgets FILE.json]
                 [--no-default-budgets] [--accept KEY=reason]... [--watch KEY]... [--tolerance PCT]
                 [--floor FILE|BYTES] [--md OUT.md] [--json]

  AFTER / BASE: PerfProbe CSV (header starts with "kind,"), a Unity/Editor/Player log or text with
  "[PERF] kind=summary ..." lines, or a read_console JSON dump. The last kind=summary row/line is used
  (filtered by --label); without a summary the kind=window rows are aggregated (avg: frame-weighted mean,
  max: max, p95: max of window p95s = conservative).

Budgets (default = 2D roguelike at 60 fps; override per project with --budget / --budgets):
  cpu_main_ms_p95 <= 16.6   main-thread work per frame (falls back to frame_ms_p95 when cpu_main is missing/0)
  gc_alloc_avg    <= 0      steady-state managed allocation per frame (bytes)
  batches_avg     <= 100    render batches (skipped when the run rendered nothing, e.g. batchmode)
  setpass_avg     <= 30     SetPass calls
  p2d_ms_p95      <= 2.0    Physics2D.Simulate per frame (ms)
  Operators: <= < >= > ==. A budget whose metric is absent is reported n/a (not a failure).
  --budgets JSON: {"cpu_main_ms_p95": "<= 16.6", "batches_avg": "<= 80"}

Editor runs (editor=1 in the data): Unity's Editor + Test Runner allocate ~0.3-0.4 KB/frame even in an empty
scene (measured on 6000.3.21f1). Pass --floor <empty-scene run or bytes> to subtract it from gc_alloc_avg;
otherwise a failing gc_alloc budget in an Editor run is WARN ("confirm in a Development player").

Regression (needs --baseline): every budgeted key plus --watch keys; lower is better (fps: higher).
  REGRESSED when after is worse than baseline by more than --tolerance % (default 10) AND by more than a noise
  floor (ms 0.25, bytes 64, counts 2, MB 1).
--accept KEY=reason records a user-accepted exception: that key's budget failure / regression is reported as
ACCEPTED and does not fail the run. Only use it after the user agreed; put the reason in PERF.md.

Exit: 0 = budgets met (or accepted) and no regression; 1 = budget failure or regression; 2 = usage/input error.
Last line: "RESULT: OK" or "RESULT: FAIL budget=k1,k2 regress=k3" (with --json: on stderr, and in the JSON).
"""
import argparse
import csv
import io
import json
import os
import re
import sys

DEFAULT_BUDGETS = {
    "cpu_main_ms_p95": ("<=", 16.6),
    "gc_alloc_avg": ("<=", 0.0),
    "batches_avg": ("<=", 100.0),
    "setpass_avg": ("<=", 30.0),
    "p2d_ms_p95": ("<=", 2.0),
}
RENDER_KEYS = ("batches", "setpass", "drawcalls", "tris")
FLOOR_NOISE = 32
OPS = {
    "<=": lambda a, b: a <= b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b, "==": lambda a, b: abs(a - b) < 1e-9,
}
BUDGET_RE = re.compile(r"^\s*([A-Za-z0-9_.]+)\s*(<=|>=|==|<|>)\s*(-?[0-9.]+)\s*$")
PERF_RE = re.compile(r"\[PERF\]\s+(kind=\S+.*)")
KV_RE = re.compile(r"([A-Za-z0-9_.]+)=(\S+)")


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    print("RESULT: FAIL input")
    sys.exit(2)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- loading

def rows_from_csv(text):
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        rows.append({k: (num(v) if k not in ("kind", "label") else v) for k, v in r.items()
                     if k is not None and v not in (None, "")})
    return rows


def strings_in_json(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            strings_in_json(v, out)
    elif isinstance(obj, list):
        for v in obj:
            strings_in_json(v, out)


def rows_from_lines(lines):
    rows = []
    for line in lines:
        for part in line.splitlines():
            m = PERF_RE.search(part)
            if not m:
                continue
            row = {}
            for k, v in KV_RE.findall(m.group(1)):
                row[k] = v if k in ("kind", "label") else num(v)
            row = {k: v for k, v in row.items() if v is not None}
            if row.get("kind") in ("window", "summary"):
                rows.append(row)
    return rows


def load(path, label):
    if not os.path.isfile(path):
        die("no such file: %s" % path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if text.lstrip().startswith("kind,"):
        rows = rows_from_csv(text)
    else:
        try:
            data = json.loads(text)
            strs = []
            strings_in_json(data, strs)
            rows = rows_from_lines(strs)
        except ValueError:
            rows = rows_from_lines(text.splitlines())
    if label:
        rows = [r for r in rows if str(r.get("label", "")) == label or str(r.get("label", "")) == "test-" + label]
    if not rows:
        die("no [PERF] summary/window data in %s%s" % (path, " for label " + label if label else ""))
    summaries = [r for r in rows if r.get("kind") == "summary"]
    if summaries:
        return summaries[-1], "summary"
    return aggregate([r for r in rows if r.get("kind") == "window"]), "windows(%d)" % len(rows)


def aggregate(windows):
    out = {"kind": "aggregate", "label": windows[-1].get("label", "")}
    frames = sum(w.get("frames", 0) or 0 for w in windows) or 1
    out["frames"] = frames
    keys = set()
    for w in windows:
        keys.update(k for k, v in w.items() if isinstance(v, float))
    for k in keys:
        vals = [(w[k], w.get("frames", 1) or 1) for w in windows if isinstance(w.get(k), float)]
        if not vals:
            continue
        if k.endswith("_avg") or k in ("fps", "editor", "dev") or k.endswith("_nz_pct"):
            out[k] = sum(v * f for v, f in vals) / sum(f for _, f in vals)
        elif k.endswith("_max") or k.endswith("_p95"):
            out[k] = max(v for v, _ in vals)
        elif k == "t":
            out[k] = max(v for v, _ in vals)
    return out


# ----------------------------------------------------------------------------- evaluation

def noise_floor(key):
    if "_ms_" in key:
        return 0.25
    if key.startswith("gc_alloc_count"):
        return 2.0
    if key.startswith("gc_alloc"):
        return 64.0
    if "_mb_" in key:
        return 1.0
    return 2.0


def effective(data, key, notes):
    """Value of key in data after fallbacks; None if missing/meaningless."""
    rendered = any((data.get(k + "_max") or 0) > 0 for k in RENDER_KEYS)
    if key.split("_")[0] in RENDER_KEYS and not rendered:
        notes.add("render counters are 0 (no camera rendered: batchmode/-nographics) -> render budgets n/a")
        return None
    if key.startswith("cpu_main_ms") and not (data.get("cpu_main_ms_avg") or 0) > 0:
        alt = "frame_ms" + key[len("cpu_main_ms"):]
        if data.get(alt) is not None:
            notes.add("cpu_main_ms missing/0 (players: enable Frame Timing Stats) -> using frame_ms")
            return data.get(alt)
        return None
    v = data.get(key)
    return v if isinstance(v, float) else None


def parse_budget(s):
    m = BUDGET_RE.match(s)
    if not m:
        die("bad --budget %r (want KEY<=VALUE)" % s)
    return m.group(1), (m.group(2), float(m.group(3)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--after", required=True)
    ap.add_argument("--baseline")
    ap.add_argument("--label")
    ap.add_argument("--budget", action="append", default=[])
    ap.add_argument("--budgets")
    ap.add_argument("--no-default-budgets", action="store_true")
    ap.add_argument("--accept", action="append", default=[], help="KEY=reason (user-approved exception)")
    ap.add_argument("--watch", action="append", default=[])
    ap.add_argument("--tolerance", type=float, default=10.0)
    ap.add_argument("--floor", help="empty-scene run (CSV/log) or bytes subtracted from gc_alloc_avg")
    ap.add_argument("--md", help="also write the markdown table to this file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    budgets = {} if a.no_default_budgets else dict(DEFAULT_BUDGETS)
    if a.budgets:
        try:
            with open(a.budgets, encoding="utf-8") as fh:
                for k, v in json.load(fh).items():
                    budgets.update([parse_budget(k + str(v).replace(" ", ""))])
        except (OSError, ValueError) as e:
            die("cannot read --budgets: %s" % e)
    for b in a.budget:
        k, v = parse_budget(b)
        budgets[k] = v
    accepted = {}
    for x in a.accept:
        if "=" not in x:
            die("bad --accept %r (want KEY=reason)" % x)
        k, r = x.split("=", 1)
        accepted[k.strip()] = r.strip()

    after, after_src = load(a.after, a.label)
    base, base_src = load(a.baseline, a.label) if a.baseline else (None, None)

    floor = 0.0
    if a.floor:
        f = num(a.floor)
        if f is None:
            fl, _ = load(a.floor, None)
            f = fl.get("gc_alloc_avg") or 0.0
        floor = f

    notes = set()
    keys = list(budgets.keys()) + [w for w in a.watch if w not in budgets]
    rows, fail_budget, fail_regress = [], [], []
    for key in keys:
        av = effective(after, key, notes)
        bv = effective(base, key, notes) if base else None
        if key.startswith("gc_alloc_avg") and floor:
            def sub(v):  # floor runs vary by a few bytes: anything under FLOOR_NOISE after subtraction is 0
                v = v - floor
                return 0.0 if v < FLOOR_NOISE else v
            if av is not None and (after.get("editor") or 0) >= 1:
                av = sub(av)
            if bv is not None and (base.get("editor") or 0) >= 1:
                bv = sub(bv)
            notes.add("gc_alloc_avg: editor floor %.0f B subtracted (remainders < %d B count as 0)" % (floor, FLOOR_NOISE))
        status, budget_txt = "-", "-"
        if key in budgets:
            op, lim = budgets[key]
            budget_txt = "%s %g" % (op, lim)
            if av is None:
                status = "n/a"
            elif OPS[op](av, lim):
                status = "PASS"
            elif key in accepted:
                status = "ACCEPTED"
            elif key.startswith("gc_alloc") and (after.get("editor") or 0) >= 1 and not floor:
                status = "WARN"
                notes.add("gc_alloc over budget in an Editor run: confirm in a Development player or pass --floor")
            else:
                status = "FAIL"
                fail_budget.append(key)
        reg = "-"
        if base is not None and av is not None and bv is not None:
            higher_better = key.startswith("fps")
            worse = (bv - av) if higher_better else (av - bv)
            pct = (worse / abs(bv) * 100.0) if bv else (100.0 if worse > 0 else 0.0)
            if worse > noise_floor(key) and pct > a.tolerance:
                if key in accepted:
                    reg = "ACCEPTED (%+.0f%%)" % pct
                else:
                    reg = "REGRESSED (%+.0f%%)" % pct
                    fail_regress.append(key)
            elif pct > a.tolerance:
                reg = "ok (%+.0f%%, under noise floor %g)" % (pct, noise_floor(key))
            else:
                reg = "ok (%+.0f%%)" % (pct if worse >= 0 else -abs(pct))
        rows.append({"metric": key, "budget": budget_txt, "baseline": bv, "after": av, "status": status,
                     "regression": reg, "accepted": accepted.get(key)})

    def fmt(v):
        return "n/a" if v is None else ("%.3f" % v).rstrip("0").rstrip(".")

    lines = ["| Metric | Budget | Baseline | After | Budget status | vs baseline |", "|---|---|---|---|---|---|"]
    for r in rows:
        st = r["status"] + (" (%s)" % r["accepted"] if r["accepted"] and r["status"] == "ACCEPTED" else "")
        lines.append("| %s | %s | %s | %s | %s | %s |" % (r["metric"], r["budget"], fmt(r["baseline"]),
                                                         fmt(r["after"]), st, r["regression"]))
    ctx = "after: %s (%s, label=%s, frames=%s, fps=%s, editor=%s)" % (
        a.after, after_src, after.get("label", "?"), fmt(after.get("frames")), fmt(after.get("fps")),
        fmt(after.get("editor")))
    if base:
        ctx += "\nbaseline: %s (%s, label=%s, frames=%s)" % (a.baseline, base_src, base.get("label", "?"),
                                                               fmt(base.get("frames")))
    ok = not fail_budget and not fail_regress
    result = "RESULT: OK" if ok else "RESULT: FAIL" + (" budget=" + ",".join(fail_budget) if fail_budget else "") + \
        (" regress=" + ",".join(fail_regress) if fail_regress else "")
    if a.json:
        print(json.dumps({"rows": rows, "notes": sorted(notes), "ok": ok, "result": result, "after": after,
                          "baseline": base}, indent=2))
    else:
        print(ctx)
        print("\n".join(lines))
        for n in sorted(notes):
            print("note: " + n)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(ctx + "\n\n" + "\n".join(lines) + "\n" + "".join("\n- note: " + n for n in sorted(notes)) + "\n")
    print(result, file=sys.stderr if a.json else sys.stdout)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
