#!/usr/bin/env python3
"""Aggregate the three trailer reviewer JSONs into one decision (same rules as design-critique).

Usage:
  trailer_review.py review/*.json [--pass-score 7] [--round 1] [--max-rounds 2] [--out review/decision.json]

Reviewers (references/reviewers.md): "Muted Scroller", "Trailer Editor", "Platform & Accessibility Auditor".
Each file: {"reviewer", "score": 1-10, "blockers": [...], "issues": [{"severity": "blocker|major|minor",
"evidence", "fix"}], "three_words": {"<word>": {"answer": "yes|no", "evidence"}}, "timestamps": [...]}.
Files without a "reviewer" key (qc.json, decision.json) are skipped.

Decision, in order:
  invalid or missing reviewer          -> TRAILER_REVIEW: ESCALATE min=0, RESULT: FAIL (re-run that reviewer)
  max(score) - min(score) > 3          -> ESCALATE (needs a human; blockers are kept in the report)
  any blocker (list or severity)       -> REFINE (ESCALATE once --round reaches --max-rounds)
  min(score) < pass score              -> REFINE (ESCALATE once --round reaches --max-rounds)
  a reviewer with < 2 "yes" taste words -> REFINE (same round rule)
  otherwise                            -> PASS
Prints `TRAILER_REVIEW: PASS|REFINE|ESCALATE min=<n>`, then `RESULT: OK` only on PASS (exit 0; else 1).
Python 3.9+ standard library only.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _trailer_common import EXIT_FAIL, EXIT_OK, EXIT_USAGE, write_json  # noqa: E402

REVIEWERS = ("Muted Scroller", "Trailer Editor", "Platform & Accessibility Auditor")
SEVERITIES = ("blocker", "major", "minor")


def validate(d, name):
    """List of problems with one reviewer JSON."""
    p = []
    if d.get("reviewer") not in REVIEWERS:
        p.append("%s: reviewer must be one of %s" % (name, ", ".join(REVIEWERS)))
    s = d.get("score")
    if isinstance(s, bool) or not isinstance(s, int) or not 1 <= s <= 10:
        p.append("%s: score must be an integer 1-10" % name)
    b = d.get("blockers")
    if not isinstance(b, list) or not all(isinstance(x, str) and x.strip() for x in b):
        p.append("%s: blockers must be a list of evidenced reasons (empty when none)" % name)
    iss = d.get("issues")
    if not isinstance(iss, list):
        p.append("%s: issues must be a list" % name)
    else:
        for k, i in enumerate(iss):
            if not isinstance(i, dict) or i.get("severity") not in SEVERITIES or \
                    not str(i.get("evidence") or "").strip() or not str(i.get("fix") or "").strip():
                p.append("%s: issues[%d] needs severity (blocker|major|minor), evidence and fix" % (name, k))
    tw = d.get("three_words", {})
    if not isinstance(tw, dict):
        p.append("%s: three_words must map each TASTE.md word to {answer, evidence}" % name)
    else:
        for w, v in tw.items():
            if not isinstance(v, dict) or v.get("answer") not in ("yes", "no") or not str(v.get("evidence") or
                                                                                      "").strip():
                p.append("%s: three_words[%s] needs answer yes|no and evidence" % (name, w))
    ts = d.get("timestamps", [])
    if not isinstance(ts, list):
        p.append("%s: timestamps must be a list" % name)
    return p


def decide(reviews, pass_score=7, rnd=1, max_rounds=2):
    """(status, min score, reasons). reviews: validated reviewer dicts."""
    scores = [r["score"] for r in reviews]
    lo, hi = min(scores), max(scores)
    reasons = []
    blockers = [(r["reviewer"], b) for r in reviews for b in r["blockers"]] + \
               [(r["reviewer"], i["evidence"]) for r in reviews for i in r["issues"] if i["severity"] == "blocker"]
    if hi - lo > 3:
        reasons.append("reviewers disagree by %d points (needs a human)" % (hi - lo))
        reasons += ["blocker (%s): %s" % b for b in blockers]
        return "ESCALATE", lo, reasons
    refine = []
    refine += ["blocker (%s): %s" % b for b in blockers]
    if lo < pass_score:
        refine.append("minimum score %d is below the pass score %d" % (lo, pass_score))
    for r in reviews:
        tw = r.get("three_words") or {}
        if tw and sum(1 for v in tw.values() if v.get("answer") == "yes") < 2:
            refine.append("%s: fewer than two of the three taste words hold" % r["reviewer"])
    if not refine:
        return "PASS", lo, ["min %d >= %d, no blockers" % (lo, pass_score)]
    if rnd >= max_rounds:
        return "ESCALATE", lo, ["round %d of %d failed; the user decides (Accept as is / Revise with notes / Park)" % (
            rnd, max_rounds)] + refine
    return "REFINE", lo, refine


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="reviewer JSON files (globs are expanded)")
    ap.add_argument("--pass-score", type=int, default=7)
    ap.add_argument("--round", type=int, default=1, help="1 = first review, 2 = after one refinement")
    ap.add_argument("--max-rounds", type=int, default=2)
    ap.add_argument("--out", help="write the decision JSON here")
    a = ap.parse_args(argv)
    if not 1 <= a.pass_score <= 10 or a.round < 1 or a.max_rounds < 1:
        print("--pass-score 1-10, --round >= 1, --max-rounds >= 1")
        print("RESULT: FAIL bad arguments")
        return EXIT_USAGE
    paths = []
    for f in a.files:
        paths += sorted(glob.glob(f)) if any(c in f for c in "*?[") else [f]
    problems, reviews, skipped = [], [], []
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except OSError as ex:
            problems.append("%s: %s" % (p, ex.strerror or ex))
            continue
        except ValueError as ex:
            problems.append("%s: not valid JSON (%s)" % (p, ex))
            continue
        if not isinstance(d, dict) or "reviewer" not in d:
            skipped.append(os.path.basename(p))
            continue
        pr = validate(d, os.path.basename(p))
        problems += pr
        if not pr:
            reviews.append(d)
    names = [r["reviewer"] for r in reviews]
    for n in REVIEWERS:
        c = names.count(n)
        if c == 0 and not any(n in x for x in problems):
            problems.append("missing review from %s" % n)
        elif c > 1:
            problems.append("%d reviews from %s (one each)" % (c, n))
    if skipped:
        print("skipped (no reviewer key): " + ", ".join(skipped))
    for r in reviews:
        print("%-34s score %2d  blockers %d  issues %d" % (r["reviewer"], r["score"], len(r["blockers"]),
                                                           len(r["issues"])))
    if problems:
        for p in problems:
            print("INVALID " + p)
        print("TRAILER_REVIEW: ESCALATE min=0")
        print("RESULT: FAIL invalid or missing reviews (%d problem(s)); re-run those reviewers" % len(problems))
        return EXIT_FAIL
    status, lo, reasons = decide(reviews, a.pass_score, a.round, a.max_rounds)
    for x in reasons:
        print("- " + x)
    if a.out:
        write_json(a.out, {"status": status, "min": lo, "pass_score": a.pass_score, "round": a.round,
                           "max_rounds": a.max_rounds, "reasons": reasons,
                           "scores": {r["reviewer"]: r["score"] for r in reviews}})
    print("TRAILER_REVIEW: %s min=%d" % (status, lo))
    if status == "PASS":
        print("RESULT: OK trailer review passed (min %d, pass %d)" % (lo, a.pass_score))
        return EXIT_OK
    print("RESULT: FAIL trailer review %s (min %d, pass %d, round %d/%d)" % (status, lo, a.pass_score, a.round,
                                                                           a.max_rounds))
    return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
