#!/usr/bin/env python3
"""Check acceptance criteria against a captured Unity console log; print a PASS/FAIL markdown table.

Usage:
  check_criteria.py CRITERIA LOG [--only M1-S02,...] [--type play-verify] [--results results.xml]
                    [--evidence ID=PASS:text]... [--forbid TEXT]... [--since TEXT] [--exit-code N] [--root DIR]
  CRITERIA: BACKLOG.md (gdd-to-backlog table format), a markdown list, or JSON.
  LOG: read_console JSON dump, Editor.log / batchmode log, or plain text ("-" = stdin).

BACKLOG.md rows (gdd-to-backlog contract):
  | M1-S02-AC2 | Given/When/Then | play-verify | log:"[Combat] hit"; screenshot:M1-S02-hit shows the flash |
Signal kinds (';'-separated in the Signal column, or in backticks in a markdown list item):
  metric:player.hp == 100      [VERIFY] key assertion on the LAST value; unit suffix ignored (16.6 ms);
                               perf-pass "[PERF] kind=summary" keys count too (frame_ms_p95, gc_alloc_avg, ...)
                               failed/passed/total/skipped fall back to the --results NUnit counts
  verify:max(rooms) >= 5       extended form: last|min|max|count|any|all(key); ops == != > >= < <= ~= exists
  log:"text"                   required log text (substring; /regex/ for a regex)
  forbid:"text"                forbidden log text (also --forbid, applies to the whole run)
  test:Fixture.Method          NUnit test passed (needs --results; substring of the full name)
  file:path                    file exists (relative to --root, default cwd)
  exit:N                       compared with --exit-code N (else MANUAL)
  screenshot:<name> shows ...  observe:... manual:...   -> MANUAL until --evidence ID=PASS:<path/why>
JSON: [{"id":..,"text":..,"checks":["metric:x == 1", ..]}] or {"criteria":[..]}.

A gate row CONSOLE (0 errors/exceptions) is added unless --no-error-gate: JSON dumps use entry types;
text logs use exception lines, "error CS", and VerifyProbe's last log.errors/log.exceptions values.

Exit: 0 all PASS, 1 any FAIL, 4 no FAIL but MANUAL items without evidence, 2 usage/input error.
Python 3.9+ stdlib only.
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

KINDS = "verify|metric|log|forbid|test|file|exit|screenshot|observe|manual"
BACKTICK_SIG_RE = re.compile(r"`\s*(%s)\s*:\s*([^`]+?)\s*`" % KINDS, re.I)
CELL_SIG_SPLIT_RE = re.compile(r";\s*(?=(?:%s)\s*:)" % KINDS, re.I)
CELL_SIG_RE = re.compile(r"^\s*(%s)\s*:\s*(.*?)\s*$" % KINDS, re.I | re.S)
ID_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(?:\*\*)?\[?([A-Za-z]{1,6}[-_]?\d+(?:[.-][A-Za-z]*\d+)*)\]?(?:\*\*)?\s*[:.)\-\u2014]")
ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# [VERIFY] key=value lines (VerifyProbe) and perf-pass PerfProbe summaries ([PERF] kind=summary key=value ...).
VERIFY_RE = re.compile(r"\[VERIFY\]\s*(.*)|\[PERF\]\s*(kind=summary\b.*)")
KV_RE = re.compile(r'([^\s=]+)=("([^"]*)"|\S*)')
EXPR_RE = re.compile(r"^\s*(?:(last|min|max|count|any|all)\s*\(\s*([^)\s]+)\s*\)|([^\s=!<>~]+))\s*"
                     r"(==|!=|>=|<=|>|<|~=|exists)\s*(.*?)\s*$")
UNIT_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*[A-Za-z%/]+$")
EXC_RE = re.compile(r"^\s*(?:[\w.]+\.)?\w*Exception(?::|$)|Assertion failed|error CS\d{4}")
ERROR_TYPES = {"error", "exception", "assert"}


# ----------------------------------------------------------------------------- criteria

def norm_signal(kind, val):
    kind = kind.lower()
    val = val.strip()
    if kind in ("log", "forbid") and len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    return kind, val


def parse_cell_signals(cell):
    out = []
    for part in CELL_SIG_SPLIT_RE.split(cell):
        m = CELL_SIG_RE.match(part)
        if m:
            out.append(norm_signal(m.group(1), m.group(2).rstrip(";").strip()))
    return out


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def parse_criteria(text):
    s = text.lstrip()
    if s[:1] in "[{":
        try:
            data = json.loads(s)
        except ValueError:
            data = None
        if data is not None:
            items = data.get("criteria", []) if isinstance(data, dict) else data
            out = []
            for n, c in enumerate(items, 1):
                checks = []
                for ch in c.get("checks", []):
                    if isinstance(ch, str):
                        checks.extend(parse_cell_signals(ch))
                    elif isinstance(ch, dict):
                        checks.append(norm_signal(str(ch.get("type", "")),
                                                  str(ch.get("expr", ch.get("pattern", ch.get("name", ""))))))
                out.append({"id": str(c.get("id", "C%d" % n)), "text": c.get("text", ""),
                            "type": c.get("test", ""), "checks": checks})
            return out
    out, n, header = [], 0, None
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            cells = split_row(line)
            low = [c.lower() for c in cells]
            if any(c == "signal" or c == "signals" for c in low):
                header = low
                continue
            if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                continue
            if header is None or len(cells) < 2:
                continue
            col = lambda name, d: header.index(name) if name in header else d
            i_id, i_sig = col("ac", col("id", 0)), max(i for i, c in enumerate(header) if c.startswith("signal"))
            i_test = col("test", -1)
            if i_sig >= len(cells):
                continue
            text_col = 1 if len(cells) > 1 and i_id != 1 else 0
            out.append({"id": cells[i_id], "text": short(cells[text_col], 80),
                        "type": cells[i_test] if 0 <= i_test < len(cells) else "",
                        "checks": parse_cell_signals(cells[i_sig])})
            continue
        header = None if line.strip() == "" else header
        if not ITEM_RE.match(line):
            continue
        sigs = [norm_signal(k, v) for k, v in BACKTICK_SIG_RE.findall(line)]
        idm = ID_RE.match(line)
        if not sigs and not idm:
            continue  # ordinary bullet, not a criterion
        n += 1
        cid = idm.group(1) if idm else "C%d" % n
        desc = BACKTICK_SIG_RE.sub("", ITEM_RE.sub("", line, count=1)).strip(" -:;,.")
        if idm:
            desc = re.sub(r"^(?:\[[ xX]\]\s+)?(?:\*\*)?\[?%s\]?(?:\*\*)?\s*[:.)\-\u2014]?\s*" % re.escape(cid), "", desc)
        out.append({"id": cid, "text": short(desc, 80), "type": "", "checks": sigs})
    return out


# ----------------------------------------------------------------------------- log

class Log:
    def __init__(self):
        self.lines = []          # (text, type or None)
        self.samples = []        # dicts from [VERIFY] lines, in order

    def add(self, text, typ=None):
        self.lines.append((text, typ))
        m = VERIFY_RE.search(text)
        if m:
            d = {}
            for k, raw, quoted in KV_RE.findall(m.group(1) or m.group(2)):
                d[k] = quoted if raw.startswith('"') else raw
            if d:
                self.samples.append(d)


def load_log(text, since=None):
    log = Log()
    s = text.lstrip()
    entries = None
    if s[:1] in "[{":
        try:
            obj = json.loads(s)
            if isinstance(obj, dict) and isinstance(obj.get("result"), (dict, list)):
                obj = obj["result"]
            entries = obj
            if isinstance(obj, dict):
                entries = obj.get("data", obj.get("items", []))
                if isinstance(entries, dict):
                    entries = entries.get("items", entries.get("lines", []))
        except ValueError:
            entries = None
    if entries is not None:
        # read_console (MCP for Unity 10.3) lists entries oldest first, so "last" = most recent.
        rows = []
        for e in entries:
            if isinstance(e, str):
                rows.append((e, None))
            elif isinstance(e, dict):
                rows.append((str(e.get("message", "")), str(e.get("type", "")).lower() or None))
        if since:
            idx = max((i for i, (t, _) in enumerate(rows) if since in t), default=None)
            if idx is not None:
                rows = rows[idx:]
        for t, typ in rows:
            log.add(t, typ)
        return log, "json"
    lines = text.splitlines()
    if since:
        idx = max((i for i, t in enumerate(lines) if since in t), default=None)
        if idx is not None:
            lines = lines[idx:]
    for t in lines:
        log.add(t)
    return log, "text"


# ----------------------------------------------------------------------------- checks

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        if v == "true":
            return 1.0
        if v == "false":
            return 0.0
        return None


def compare(a, op, b):
    if op == "exists":
        return a is not None
    if a is None:
        return False
    if op == "~=":
        return re.search(b, str(a)) is not None
    fa, fb = num(a), num(b)
    if fa is not None and fb is not None:
        return {"==": abs(fa - fb) < 1e-6, "!=": abs(fa - fb) >= 1e-6, ">": fa > fb, ">=": fa >= fb,
                "<": fa < fb, "<=": fa <= fb}[op]
    b = b.strip('"')
    if op == "==":
        return str(a) == b
    if op == "!=":
        return str(a) != b
    return False


def check_verify(expr, log, counts=None):
    m = EXPR_RE.match(expr)
    if not m:
        return "FAIL", "bad expression '%s' (want key OP value)" % expr
    agg, key = (m.group(1) or "last").lower(), m.group(2) or m.group(3)
    op, want = m.group(4), m.group(5)
    u = UNIT_RE.match(want)
    if u:
        want = u.group(1)  # "16.6 ms" -> "16.6"
    vals = [s[key] for s in log.samples if key in s]
    if not vals and counts and key in counts:
        got = counts[key]
        ok = compare(got, op, want)
        return ("PASS" if ok else "FAIL"), "NUnit %s=%s (want %s %s)" % (key, got, op, want)
    if not vals:
        if op == "exists":
            return "FAIL", "no [VERIFY] %s= line" % key
        return "FAIL", "no [VERIFY] %s= line (%d [VERIFY] lines total)" % (key, len(log.samples))
    if agg == "count":
        got = str(len(vals))
    elif agg in ("min", "max"):
        nums = [num(v) for v in vals if num(v) is not None]
        if not nums:
            return "FAIL", "%s values not numeric: %s" % (key, vals[-1])
        got = "%g" % (min(nums) if agg == "min" else max(nums))
    elif agg == "any":
        ok = [v for v in vals if compare(v, op, want)]
        return ("PASS", "%s=%s matched in %d/%d samples" % (key, ok[0], len(ok), len(vals))) if ok else \
            ("FAIL", "no sample of %s %s %s (last %s=%s)" % (key, op, want, key, vals[-1]))
    elif agg == "all":
        bad = [v for v in vals if not compare(v, op, want)]
        return ("PASS", "all %d samples of %s %s %s" % (len(vals), key, op, want)) if not bad else \
            ("FAIL", "%d/%d samples violate, e.g. %s=%s" % (len(bad), len(vals), key, bad[0]))
    else:
        got = vals[-1]
    ok = compare(got, op, want)
    label = "%s(%s)" % (agg, key) if agg != "last" else key
    return ("PASS" if ok else "FAIL"), "%s=%s (want %s %s; %d samples)" % (label, got, op, want, len(vals))


def pattern_find(pat, log):
    if len(pat) > 2 and pat.startswith("/") and pat.endswith("/"):
        rx = re.compile(pat[1:-1])
        return [t for t, _ in log.lines if rx.search(t)]
    return [t for t, _ in log.lines if pat in t]


def short(t, n=100):
    t = t.strip().splitlines()[0] if t.strip() else ""
    return t if len(t) <= n else t[: n - 3] + "..."


def load_results(path):
    """NUnit XML -> ({fullname: result}, {total, passed, failed, skipped})."""
    if not path:
        return None, None
    root = ET.parse(path).getroot()
    cases = {tc.get("fullname", ""): tc.get("result", "") for tc in root.iter("test-case")}
    counts = {k: root.get(k) for k in ("total", "passed", "failed", "skipped") if root.get(k) is not None}
    return cases, counts


def check_test(name, results):
    if results is None:
        return "MANUAL", "no --results XML given"
    hits = {k: v for k, v in results.items() if name in k}
    if not hits:
        return "FAIL", "test '%s' not in results (%d tests)" % (name, len(results))
    bad = {k: v for k, v in hits.items() if v != "Passed"}
    if bad:
        k, v = next(iter(bad.items()))
        return "FAIL", "%s: %s" % (k, v)
    return "PASS", "%d test(s) Passed: %s" % (len(hits), next(iter(hits)))


def error_gate(log, mode):
    if mode == "json":
        errs = [t for t, typ in log.lines if typ in ERROR_TYPES]
    else:
        errs = [t for t, _ in log.lines if EXC_RE.search(t)]
    probe = 0
    for key in ("log.errors", "log.exceptions"):
        vals = [num(s[key]) for s in log.samples if key in s]
        if vals and vals[-1]:
            probe += int(vals[-1])
    if errs:
        return "FAIL", "%d error/exception line(s), first: %s" % (len(errs), short(errs[0]))
    if probe:
        return "FAIL", "VerifyProbe counted %d error(s)/exception(s) (log.errors/log.exceptions)" % probe
    src = "console entry types" if mode == "json" else "exception/CS lines"
    if log.samples and any("log.errors" in s for s in log.samples):
        src += " + VerifyProbe log.errors=0"
    return "PASS", "0 errors (%s)" % src


def evaluate(crit, log, results, counts, evidence, root, exit_code):
    rows = []
    for c in crit:
        statuses, notes = [], []
        for kind, arg in c["checks"]:
            if kind in ("verify", "metric"):
                st, ev = check_verify(arg, log, counts)
            elif kind == "log":
                hits = pattern_find(arg, log)
                st, ev = ("PASS", "found x%d: %s" % (len(hits), short(hits[0]))) if hits else ("FAIL", "not found: %s" % arg)
            elif kind == "forbid":
                hits = pattern_find(arg, log)
                st, ev = ("FAIL", "forbidden x%d: %s" % (len(hits), short(hits[0]))) if hits else ("PASS", "absent: %s" % arg)
            elif kind == "test":
                st, ev = check_test(arg, results)
            elif kind == "file":
                path = arg.strip("`\"' ")
                full = path if os.path.isabs(path) else os.path.join(root, path)
                st, ev = ("PASS", "exists: %s" % path) if os.path.exists(full) else ("FAIL", "missing: %s" % full)
            elif kind == "exit":
                if exit_code is None:
                    st, ev = "MANUAL", "exit:%s (pass --exit-code)" % arg
                else:
                    st = "PASS" if str(exit_code) == arg.strip() else "FAIL"
                    ev = "exit code %s (want %s)" % (exit_code, arg.strip())
            else:  # screenshot / observe / manual
                st, ev = "MANUAL", "%s: %s" % (kind, arg)
            statuses.append(st)
            notes.append(ev)
        if not c["checks"]:
            statuses, notes = ["MANUAL"], ["no machine-checkable signal"]
        if c["id"] in evidence:
            est, etxt = evidence[c["id"]]
            if "FAIL" in statuses and est == "PASS":
                notes.append("evidence %s ignored: an automatic check FAILED" % etxt)
            else:
                statuses = [s if s != "MANUAL" else est for s in statuses]
                notes.append("agent: %s %s" % (est, etxt))
        status = "FAIL" if "FAIL" in statuses else ("MANUAL" if "MANUAL" in statuses else "PASS")
        rows.append((c["id"], status, c["text"], "; ".join(notes)))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("criteria")
    ap.add_argument("log")
    ap.add_argument("--results", help="NUnit results XML for `test:` signals")
    ap.add_argument("--evidence", action="append", default=[], metavar="ID=PASS|FAIL:text",
                    help="agent verdict for MANUAL items (e.g. screenshots); repeatable")
    ap.add_argument("--since", help="only use the log after the last line containing this text")
    ap.add_argument("--only", help="comma-separated criterion ID prefixes, e.g. M1-S02,M1-S03-AC1")
    ap.add_argument("--type", help="comma-separated Test column values to keep, e.g. play-verify,PlayMode")
    ap.add_argument("--forbid", action="append", default=[], help="text that must not appear in the run; repeatable")
    ap.add_argument("--root", default=".", help="base folder for file: signals (default: cwd)")
    ap.add_argument("--exit-code", type=int, help="exit code of the run, for exit: signals")
    ap.add_argument("--no-error-gate", action="store_true", help="do not add the CONSOLE 0-errors criterion")
    ap.add_argument("--json", action="store_true", help="JSON output instead of a markdown table")
    a = ap.parse_args(argv)

    try:
        crit = parse_criteria(open(a.criteria, encoding="utf-8", errors="replace").read())
        raw = sys.stdin.read() if a.log == "-" else open(a.log, encoding="utf-8", errors="replace").read()
        results, counts = load_results(a.results)
    except (OSError, ET.ParseError) as e:
        print("RESULT: FAIL input error: %s" % e)
        return 2
    if a.only:
        want = tuple(x.strip() for x in a.only.split(",") if x.strip())
        crit = [c for c in crit if c["id"].startswith(want)]
    if a.type:
        types = {x.strip().lower() for x in a.type.split(",")}
        crit = [c for c in crit if c.get("type", "").lower() in types]
    if not crit:
        print("RESULT: FAIL no criteria found in %s" % a.criteria)
        return 2
    evidence = {}
    for e in a.evidence:
        m = re.match(r"([^=]+)=(PASS|FAIL)(?::(.*))?$", e, re.I)
        if not m:
            print("RESULT: FAIL bad --evidence '%s' (want ID=PASS:text)" % e)
            return 2
        evidence[m.group(1).strip()] = (m.group(2).upper(), (m.group(3) or "").strip())

    log, mode = load_log(raw, a.since)
    rows = evaluate(crit, log, results, counts, evidence, a.root, a.exit_code)
    for n, pat in enumerate(a.forbid, 1):
        hits = pattern_find(pat, log)
        rows.append(("FORBID%d" % n, "FAIL" if hits else "PASS", "never logs: %s" % pat,
                     ("x%d: %s" % (len(hits), short(hits[0]))) if hits else "absent"))
    if not a.no_error_gate:
        st, ev = error_gate(log, mode)
        rows.append(("CONSOLE", st, "no errors/exceptions during the run", ev))

    n_fail = sum(1 for r in rows if r[1] == "FAIL")
    n_manual = sum(1 for r in rows if r[1] == "MANUAL")
    n_pass = len(rows) - n_fail - n_manual
    code = 1 if n_fail else (4 if n_manual else 0)
    if a.json:
        print(json.dumps({"pass": n_pass, "fail": n_fail, "manual": n_manual, "exit_code": code,
                          "rows": [dict(zip(("id", "status", "criterion", "evidence"), r)) for r in rows]}, indent=1))
        return code
    print("| ID | Status | Criterion | Evidence |")
    print("|---|---|---|---|")
    for r in rows:
        print("| %s | %s | %s | %s |" % tuple(x.replace("|", "\\|") for x in r))
    print()
    print("log: %s (%d lines, %d [VERIFY] samples)" % (mode, len(log.lines), len(log.samples)))
    if code == 0:
        print("RESULT: OK %d/%d PASS" % (n_pass, len(rows)))
    elif code == 1:
        print("RESULT: FAIL %d FAIL, %d MANUAL, %d PASS" % (n_fail, n_manual, n_pass))
    else:
        print("RESULT: INCOMPLETE %d MANUAL item(s) need --evidence, %d PASS" % (n_manual, n_pass))
    return code


if __name__ == "__main__":
    sys.exit(main())
