#!/usr/bin/env python3
"""Check prompt improver eval freshness or run and publish a paid live eval."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
os.environ.setdefault("GDW_NO_KEYCHAIN", "1")
os.environ.setdefault("GDW_HOME", tempfile.mkdtemp(prefix="pi-regression-home-"))

from gamedevworkstation.features.eval_fingerprint import check, compute, digest, render_md  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("eval_prompt_improver", REPO / "scripts/eval_prompt_improver.py")
_EVAL = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_EVAL)


def _run_live(model: str) -> tuple[dict, int, float | None]:
    """Run the real coordinator and summarize its results using the isolated app database."""
    from gamedevworkstation.features import prompt_improver as PI
    base = Path(tempfile.mkdtemp(prefix="pi-regression-live-"))
    corpus = _EVAL.load_corpus()
    app, imp, rec = _EVAL.build_app(base, None, live=True)
    resolved = app.config.resolve(model)
    original = PI._cfg
    PI._cfg = lambda a: {**original(a), "model": resolved}
    try:
        recs = _EVAL.asyncio.run(_EVAL.run_corpus(corpus, app, imp, rec, _EVAL.make_project(base)))
    finally:
        PI._cfg = original
    bypass = _EVAL.run_bypass(corpus["bypass"])
    rows = app.db.all("SELECT cost_usd FROM usage_records")
    return (_EVAL.summarize(recs, bypass, corpus), len(rows),
            (sum(float(r["cost_usd"] or 0) for r in rows) if rows else None))


def _set_isolated_home() -> None:
    os.environ["GDW_NO_KEYCHAIN"] = "1"
    os.environ["GDW_HOME"] = tempfile.mkdtemp(prefix="pi-regression-home-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prompt improver regression eval publication tools.")
    subs = parser.add_subparsers(dest="command", required=True)
    ck = subs.add_parser("check")
    ck.add_argument("--github", action="store_true")
    ck.add_argument("--published-dir", type=Path, default=REPO / "docs/evals")
    run = subs.add_parser("run")
    run.add_argument("--approve-paid", action="store_true")
    run.add_argument("--model", default="claude.fast")
    run.add_argument("--out-dir", type=Path, default=REPO / "docs/evals")
    args = parser.parse_args(argv)
    _set_isolated_home()
    if args.command == "check":
        result = check(args.published_dir / "prompt-improver.json", args.published_dir / "prompt-improver.md", compute())
        print(result["message"])
        if args.github:
            status = result["status"]
            if status in ("never_run", "stale"):
                print(f"::warning::{result['message']}")
            elif status == "invalid":
                print(f"::error::{result['message']}")
            if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
                note = f"**Prompt improver eval:** {status}"
                if result["changed"]:
                    note += f" (changed: {', '.join(result['changed'])})."
                elif status in ("never_run", "stale"):
                    note += ". Re-run it with `uv run python scripts/eval_regression.py run --approve-paid`."
                with Path(summary_path).open("a", encoding="utf-8") as stream:
                    stream.write(note + "\n")
        return 1 if result["status"] == "invalid" else 0
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        print("Refusing to run a paid eval in CI.")
        return 2
    corpus = _EVAL.load_corpus()
    from gamedevworkstation.config import get_config
    config = get_config()
    resolved = config.resolve(args.model)
    if not args.approve_paid:
        n = len(corpus["prompts"])
        print(f"{n} prompts x up to {_EVAL.MAX_CALLS} calls = up to {n * _EVAL.MAX_CALLS} real model calls with {resolved}; bills your provider account")
        return 2
    before_path = args.out_dir / "prompt-improver.json"
    previous = None
    if before_path.exists():
        try:
            previous = json.loads(before_path.read_text(encoding="utf-8")).get("summary")
        except (OSError, ValueError):
            previous = None
    summary, calls, cost = _run_live(args.model)
    fp = compute(config.model_copy(update={"prompt_improver": {**config.prompt_improver, "model": resolved}}))
    try:
        git_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_sha = ""
    doc = {"schema": 1, "fingerprint": fp, "digest": digest(fp), "mode": "live",
           "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "git_sha": git_sha,
           "model": resolved, "calls": calls, "cost_usd": cost, "summary": summary}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "prompt-improver.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "prompt-improver.md").write_text(render_md(doc), encoding="utf-8")
    if isinstance(previous, dict):
        for key, value in summary.items():
            old = previous.get(key)
            if isinstance(value, (int, float)) and isinstance(old, (int, float)):
                print(f"{key}: {old} -> {value}")
    print(f"Published live prompt improver eval to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
