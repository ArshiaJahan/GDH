"""`gdw eval ...` and /api/evals: Eval Forge from the command line and the app.

    gdw eval forge <commit> | --pr N --github OWNER/NAME  [--repo PATH] [--out evals/suite] [--rewrite]
    gdw eval list [--suite evals/suite]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI, HTTPException

from ..agent.tools import wrap_untrusted
from ..core.effort import EffortApprovalRequired, check_effort
from ..core.types import EFFORT_LEVELS, ChatRequest, Message, TextBlock, Usage
from . import eval_forge, eval_task

if TYPE_CHECKING:
    from ..app import AppState

DEFAULT_SUITE = "evals/suite"


def make_rewrite(app: "AppState", *, model: str | None = None, effort: str = "low") -> tuple[eval_forge.Rewrite, str]:
    """A model call that rewrites PR text as a task statement (through the effort gate, recorded in usage)."""
    m = model or app.config.resolve("claude.standard")
    run_id = "eval-forge-" + secrets.token_hex(4)
    check_effort(effort, None, run_id)  # above "high" needs the user's approval: raises

    async def rewrite(text: str) -> str:
        check_effort(effort, None, run_id)
        mcfg = app.config.model(m)
        profile = app.config.profiles(mcfg.provider)[0]
        prov = app.providers.for_model(m, profile)
        req = ChatRequest(model=m, messages=[Message(role="user", content=[TextBlock(text=wrap_untrusted(text, "pull request"))])],
                          system=eval_forge.REWRITE_SYSTEM, effort=effort, max_tokens=1500,  # type: ignore[arg-type]
                          show_thinking=False, metadata={"run_id": run_id, "cache_key": "eval_forge"})
        try:
            resp = await prov.complete(req)
        except Exception as e:  # noqa: BLE001
            app.usage.record(provider=mcfg.provider, model=m, usage=Usage(), role="assistant", profile=profile,
                             run_id=run_id, effort=effort, feature="eval_forge", ok=False,
                             error_kind="rate_limit" if getattr(e, "rate_limited", False) else "other")
            raise
        app.usage.record(provider=mcfg.provider, model=m, usage=resp.usage, role="assistant", profile=profile,
                         run_id=run_id, effort=effort, feature="eval_forge", latency_ms=resp.latency_ms)
        return resp.message().text()

    return rewrite, m


def _forge_cmd(args: argparse.Namespace) -> int:
    repo = Path(args.repo).expanduser()
    text, rev, pr, slug = None, args.target, None, args.source
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    if (args.pr is None) == (args.target is None):
        print("gdw eval forge: give a commit, or --pr N with --github OWNER/NAME", file=sys.stderr)
        return 2
    if args.pr is not None:
        if not args.github:
            print("gdw eval forge: --pr needs --github OWNER/NAME", file=sys.stderr)
            return 2
        pr = args.pr
        body, rev, slug = eval_forge.pr_text(args.github, pr)
        text = text if text is not None else body
    rewrite, by = None, ""
    if args.rewrite:
        from ..app import AppState

        rewrite, by = make_rewrite(AppState(), model=args.model, effort=args.effort)
    out = asyncio.run(eval_forge.forge(repo, rev, Path(args.out), task_id=args.id, command=args.command, text=text,
                                       pr=pr, source_repo=slug, rewrite=rewrite, rewritten_by=by,
                                       kind=args.kind, unity_replay=args.unity_replay or "", tags=args.tag or [],
                                       setup=args.setup or ""))
    t = eval_task.load(out)
    print(json.dumps({"task": t.task.id, "dir": str(out), "tests": t.task.grader.tests,
                      "command": t.task.grader.command, "removed": t.task.forge.removed}, indent=1))
    return 0


def _list_cmd(args: argparse.Namespace) -> int:
    rows = []
    for d in eval_task.discover(args.suite):
        try:
            t = eval_task.load(d)
            rows.append({"id": t.task.id, "kind": t.task.kind, "title": t.task.title, "ok": True})
        except eval_task.EvalTaskError as e:
            rows.append({"id": d.name, "ok": False, "error": str(e)})
    print(json.dumps(rows, indent=1) if args.json else
          "\n".join(f"{'ok ' if r['ok'] else 'BAD'} {r['id']}  {r.get('title') or r.get('error')}" for r in rows))
    return 0 if all(r["ok"] for r in rows) else 1


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="gdw eval", description="Eval Forge: agent tasks from real commits.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forge", help="turn a commit or merged PR into a task")
    f.add_argument("target", nargs="?", help="the commit (any git revision)")
    f.add_argument("--pr", type=int, help="a merged PR number instead of a commit (needs --github)")
    f.add_argument("--repo", default=".", help="the git repository (default: here)")
    f.add_argument("--out", default=DEFAULT_SUITE, help=f"suite directory (default {DEFAULT_SUITE})")
    f.add_argument("--id", help="task id (default: from the title and commit)")
    f.add_argument("--command", help="test command (default: pytest/vitest on the commit's test files)")
    f.add_argument("--setup", help="command that prepares a fresh tree (install, build)")
    f.add_argument("--text-file", help="use this text as the task description instead of the commit message")
    f.add_argument("--github", metavar="OWNER/NAME", help="read the PR from GitHub (for a PR number)")
    f.add_argument("--source", help="the source repo recorded in task.toml (default: --repo's path)")
    f.add_argument("--kind", default="code", choices=["code", "unity"])
    f.add_argument("--unity-replay", help="unity tasks: project-relative .gdwreplay the grader replays")
    f.add_argument("--tag", action="append")
    f.add_argument("--rewrite", action="store_true", help="have a model rewrite the text first (effort gate applies)")
    f.add_argument("--model")
    f.add_argument("--effort", default="low", choices=list(EFFORT_LEVELS))
    f.set_defaults(fn=_forge_cmd)
    ls = sub.add_parser("list", help="list the suite's tasks and check each one loads")
    ls.add_argument("--suite", default=DEFAULT_SUITE)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(fn=_list_cmd)
    return ap


def cli(argv: list[str]) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0) if isinstance(e.code, int) else 2
    try:
        return int(args.fn(args))
    except (eval_forge.ForgeError, eval_task.EvalTaskError, OSError) as e:
        print(f"gdw eval {args.cmd}: {e}", file=sys.stderr)
        return 2
    except EffortApprovalRequired as e:
        print(f"gdw eval {args.cmd}: {e}", file=sys.stderr)
        return 2


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    @api.get("/evals/tasks")
    async def list_tasks(suite: str) -> dict:
        root = Path(suite).expanduser()
        if not root.is_dir():
            raise HTTPException(400, f"no such suite directory: {suite}")
        out = []
        for d in eval_task.discover(root):
            try:
                t = eval_task.load(d)
                out.append({"id": t.task.id, "title": t.task.title, "kind": t.task.kind, "tags": t.task.tags,
                            "source": t.task.source.model_dump(), "tests": t.task.grader.tests})
            except eval_task.EvalTaskError as e:
                out.append({"id": d.name, "error": str(e)})
        return {"suite": str(root), "tasks": out}
