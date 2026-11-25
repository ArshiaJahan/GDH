#!/usr/bin/env python3
"""Run and summarize the deterministic guardrail catalogue."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO))

from tests.guardrails.report import CASES_DIR, evaluate, load_cases, load_known_gaps, load_wrap_gaps, summary_line, to_json, to_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--approve-paid", action="store_true")
    parser.add_argument("--model", default="claude.fast")
    args = parser.parse_args(argv)
    if args.live and ("CI" in os.environ or "GITHUB_ACTIONS" in os.environ):
        print("refusing --live in CI", file=sys.stderr)
        return 2
    if args.live and not args.approve_paid:
        print("refusing --live without --approve-paid", file=sys.stderr)
        return 2
    cases = load_cases()
    if args.list:
        for vector in ("web", "console", "asset", "commit", "mcp", "subagent", "direct_delete", "direct_secret"):
            print(f"{vector}: " + ", ".join(c["id"] for c in cases if c["vector"] == vector))
        return 0
    from tests.guardrails.runner import run_all
    if args.live:
        print(f"WARNING: --live makes up to {len(cases)*3} real model calls with {args.model} and bills your provider account")
    results = run_all(live=args.live, model=args.model if args.live else None)
    try: sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError): sha = ""
    report = evaluate(results, load_known_gaps(), load_wrap_gaps(), git_sha=sha)
    print(summary_line(report))
    for violation in report.violations(): print(violation)
    if args.out: args.out.write_text(json.dumps(to_json(report), indent=2) + "\n", encoding="utf-8")
    summary_path = args.summary or (Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None)
    if summary_path: summary_path.open("a", encoding="utf-8").write(to_markdown(report))
    return 1 if report.violations() else 0


if __name__ == "__main__":
    raise SystemExit(main())
