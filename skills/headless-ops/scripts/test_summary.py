#!/usr/bin/env python3
"""Summarise a Unity Test Framework NUnit3 results XML (the file written by -testResults).

usage: test_summary.py results.xml [--allow-empty] [--max-failures N] [--json]

Prints
  tests: total=T passed=P failed=F skipped=S inconclusive=I duration=Ds result=R
  FAILED <full test name> :: <first line of the message>      (one per failed test-case)
          at <first stack line inside Assets/>                   (when present)
Exit codes: 0 all passed (and at least one test ran, unless --allow-empty)
            2 one or more tests failed (same meaning as Unity's own exit code 2)
            1 the XML is missing/unreadable, or no tests ran
Python 3 stdlib only.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET


def first_line(text):
    for line in (text or "").strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def first_project_frame(stack):
    for line in (stack or "").splitlines():
        m = re.search(r"(Assets/[^\s:]+\.cs:\d+|Assets/[^\s]+\.cs\(\d+[,\d]*\)|in (\S+\.cs):(\d+))", line)
        if m:
            return re.sub(r"^at\s+", "", line.strip())
    return ""


def main(argv):
    if "-h" in argv[1:] or "--help" in argv[1:]:
        print(__doc__.strip())
        return 0
    args = [a for a in argv[1:] if not a.startswith("--")]
    allow_empty = "--allow-empty" in argv
    as_json = "--json" in argv
    max_fail = 30
    if "--max-failures" in argv:
        i = argv.index("--max-failures")
        max_fail = int(argv[i + 1])
        args = [a for a in args if a != argv[i + 1]]
    if len(args) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 1
    try:
        root = ET.parse(args[0]).getroot()
    except (OSError, ET.ParseError) as e:
        print("tests: unreadable results file %s (%s)" % (args[0], e))
        return 1

    # Root is <test-run> in NUnit3 output; fall back to counting test-case elements.
    cases = list(root.iter("test-case"))
    a = root.attrib

    def count(attr, pred):
        v = a.get(attr)
        if v is not None and v.isdigit():
            return int(v)
        return sum(1 for c in cases if pred(c.get("result", "")))

    total = count("total", lambda r: True)
    passed = count("passed", lambda r: r == "Passed")
    failed = count("failed", lambda r: r == "Failed")
    skipped = count("skipped", lambda r: r == "Skipped")
    inconclusive = count("inconclusive", lambda r: r == "Inconclusive")
    duration = a.get("duration", "?")
    result = a.get("result", "?")

    failures = []
    for c in cases:
        if c.get("result") == "Failed":
            msg = first_line(c.findtext("./failure/message"))
            where = first_project_frame(c.findtext("./failure/stack-trace"))
            failures.append({"name": c.get("fullname") or c.get("name"), "message": msg, "at": where})

    if as_json:
        print(json.dumps({"total": total, "passed": passed, "failed": failed, "skipped": skipped,
                          "inconclusive": inconclusive, "duration": duration, "result": result,
                          "failures": failures}, indent=1))
    else:
        try:
            dur = "%.1fs" % float(duration)
        except ValueError:
            dur = duration
        print("tests: total=%d passed=%d failed=%d skipped=%d inconclusive=%d duration=%s result=%s"
              % (total, passed, failed, skipped, inconclusive, dur, result))
        for f in failures[:max_fail]:
            print("FAILED %s :: %s" % (f["name"], f["message"]))
            if f["at"]:
                print("        at %s" % f["at"])
        if len(failures) > max_fail:
            print("... %d more failures" % (len(failures) - max_fail))

    if failed > 0 or failures:
        return 2
    if total == 0 and not allow_empty:
        print("no tests ran (wrong filter, no test assemblies, or tests excluded); pass --allow-empty to accept")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
