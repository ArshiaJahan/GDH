"""`gdw eval ...` and /api/evals: Eval Forge from the command line and the app.

    gdw eval forge <commit> | --pr N --github OWNER/NAME  [--repo PATH] [--out evals/suite] [--rewrite]
    gdw eval list [--suite evals/suite]
    gdw eval grade <task> --patch FILE       grade one candidate change
    gdw eval validate <task>... | --suite DIR  the reference must pass, flawed solutions must fail
    gdw eval run --agents claude_code,codex,builtin --trials K [<task>... | --suite DIR]
    gdw eval export [<task>... | --suite DIR] --out DIR   as Harbor tasks (the Terminal-Bench 2.0 format)
    gdw eval compare-routing --suite DIR --baseline-tier T --job-type J --trials N --max-spend-usd X [--approve-paid]
                                             pinned tier vs tier="auto"; without --approve-paid only a preview
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI, HTTPException

from ..agent.tools import wrap_untrusted
from ..core.effort import EffortApprovalRequired, check_effort
from ..core.types import EFFORT_LEVELS, ChatRequest, Message, TextBlock
from ..providers.registry import attempt_failure
from . import eval_export, eval_forge, eval_grade, eval_run, eval_task, eval_validate

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
        with app.usage.scope():
            try:
                resp = await prov.complete(req)
            except (Exception, asyncio.CancelledError) as exc:
                usage, kind = attempt_failure(exc)
                app.usage.record(provider=mcfg.provider, model=m, usage=usage, role="assistant", profile=profile,
                                 run_id=run_id, effort=effort, feature="eval_forge", ok=False, error_kind=kind)
                raise
            failed = resp.stop_reason == "error"
            app.usage.record(provider=mcfg.provider, model=m, usage=resp.usage, role="assistant", profile=profile,
                             run_id=run_id, effort=effort, feature="eval_forge", latency_ms=resp.latency_ms,
                             ok=not failed, error_kind="other" if failed else None)
        # A failed reply is already recorded as a failed attempt; its (empty) text reaches Forge's own validation.
        return resp.message().text()

    return rewrite, m


RUBRIC_SYSTEM = (
    "You grade a code change against a rubric. Read the rubric, then the diff. Reply with one JSON object: "
    '{"pass": true|false, "score": 0-1, "reasons": "<one or two sentences>"}. Pass only when every rubric item '
    "is met by the diff itself; don't give credit for intent or comments.")


def make_rubric(app: "AppState", *, model: str | None = None, effort: str = "low") -> eval_grade.Rubric:
    """The LLM rubric grader (through the effort gate, recorded in usage)."""
    m = model or app.config.resolve("claude.standard")
    run_id = "eval-rubric-" + secrets.token_hex(4)
    check_effort(effort, None, run_id)

    async def judge(rubric: str, diff: str) -> dict:
        check_effort(effort, None, run_id)
        mcfg = app.config.model(m)
        profile = app.config.profiles(mcfg.provider)[0]
        prov = app.providers.for_model(m, profile)
        body = f"Rubric:\n{rubric}\n\n" + wrap_untrusted(diff[-60_000:], "candidate diff")
        req = ChatRequest(model=m, messages=[Message(role="user", content=[TextBlock(text=body)])], system=RUBRIC_SYSTEM,
                          effort=effort, max_tokens=600, show_thinking=False,  # type: ignore[arg-type]
                          metadata={"run_id": run_id, "cache_key": "eval_rubric"})
        with app.usage.scope():
            try:
                resp = await prov.complete(req)
            except (Exception, asyncio.CancelledError) as exc:
                usage, kind = attempt_failure(exc)
                app.usage.record(provider=mcfg.provider, model=m, usage=usage, role="assistant", profile=profile,
                                 run_id=run_id, effort=effort, feature="eval_rubric", ok=False, error_kind=kind)
                raise
            failed = resp.stop_reason == "error"
            app.usage.record(provider=mcfg.provider, model=m, usage=resp.usage, role="assistant", profile=profile,
                             run_id=run_id, effort=effort, feature="eval_rubric", latency_ms=resp.latency_ms,
                             ok=not failed, error_kind="other" if failed else None)
        # A failed reply is already recorded as a failed attempt; it grades as a failure like any unparsable reply.
        from .pi_contracts import loads_reply

        try:
            verdict = loads_reply(resp.message().text())
        except ValueError:
            return {"pass": False, "reasons": "the judge's reply wasn't JSON"}
        return verdict if isinstance(verdict, dict) else {"pass": False, "reasons": "the judge's reply wasn't an object"}

    return judge


_STARTED: list["AppState"] = []


def _cli_state() -> "AppState":
    """An AppState whose trace recorder runs for the CLI's lifetime (the app starts it in the FastAPI lifespan);
    `cli` drains it at exit."""
    from ..app import AppState

    state = AppState()
    _STARTED.append(state)
    try:
        asyncio.run(state.tracing.astart())
    except Exception:  # noqa: BLE001  tracing fails open
        pass
    return state


async def _drain(states: list["AppState"]) -> None:
    for state in states:
        try:
            await state.tracing.aclose()
        except Exception:  # noqa: BLE001
            pass


def _rubric_for(args: argparse.Namespace) -> eval_grade.Rubric | None:
    if not getattr(args, "rubric_model", None):
        return None
    return make_rubric(_cli_state(), model=args.rubric_model, effort=args.effort)


def _grade_cmd(args: argparse.Namespace) -> int:
    task = eval_task.load(args.task)
    patch = sys.stdin.read() if args.patch == "-" else Path(args.patch).read_text(encoding="utf-8")
    g = asyncio.run(eval_grade.grade_patch(task, patch, repo=Path(args.repo) if args.repo else None,
                                           rubric=_rubric_for(args)))
    if args.json:
        print(json.dumps(g.to_dict(), indent=1))
    else:
        for st in g.steps:
            print(f"{'PASS' if st.passed else 'FAIL'} {st.kind:12} {st.name}" + (" (environment)" if st.environment and not st.passed else ""))
        if g.tampered:
            print(f"tampered with hidden tests: {', '.join(g.tampered)} (graded against the originals)")
        print("passed" if g.passed else "failed")
    return 0 if g.passed else 1


def _validate_cmd(args: argparse.Namespace) -> int:
    dirs = [Path(t) for t in args.tasks] or eval_task.discover(args.suite)
    if not dirs:
        print("gdw eval validate: no tasks given and none in the suite", file=sys.stderr)
        return 2
    reports = []
    for d in dirs:
        task = eval_task.load(d)
        rep = asyncio.run(eval_validate.validate(task, repo=Path(args.repo) if args.repo else None,
                                                 rubric=_rubric_for(args), max_mutants=args.mutants,
                                                 max_partials=args.partials))
        reports.append(rep)
        if not args.markdown and not args.json:
            print(f"{task.task.id}: reference {'pass' if rep.reference_passed else 'FAIL'}, "
                  f"{rep.killed}/{rep.flawed} flawed caught ({rep.kill_rate:.0%})")
            for o in rep.survivors:
                print(f"  survived: {o.id} ({o.description})")
    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=1))
    elif args.markdown:
        print(eval_validate.render_markdown(reports))
    return 0 if all(r.ok for r in reports) else 1


AGENTS = ("builtin", "claude_code", "claude_code_glm", "codex")
GLM_MODEL = "glm-5-3-flash-260828"


def _run_cmd(args: argparse.Namespace) -> int:
    names = [a.strip() for a in args.agents.split(",") if a.strip()]
    bad = [a for a in names if a not in AGENTS]
    if not names or bad:
        print(f"gdw eval run: --agents takes {', '.join(AGENTS)}", file=sys.stderr)
        return 2
    dirs = [Path(t) for t in args.tasks] or eval_task.discover(args.suite)
    if not dirs:
        print("gdw eval run: no tasks given and none in the suite", file=sys.stderr)
        return 2
    tasks = [eval_task.load(d) for d in dirs]
    app = None
    if {"builtin", "claude_code", "claude_code_glm"} & set(names):
        app = _cli_state()
    agents: dict[str, eval_run.AgentFn] = {}
    for n in names:
        if n == "builtin":
            agents[n] = eval_run.builtin_agent(app, tier=args.tier, effort=args.effort)  # type: ignore[arg-type]
        elif n == "claude_code":
            agents[n] = eval_run.claude_code_agent(app, model=args.claude_model)
        elif n == "claude_code_glm":
            agents[n] = eval_run.claude_code_agent(app, model=args.claude_model, helper_model=args.glm_model)
        else:
            agents[n] = eval_run.codex_agent(model=args.codex_model)
    out = Path(args.out or f"evals/runs/{time.strftime('%Y%m%d-%H%M%S')}")
    out.mkdir(parents=True, exist_ok=True)
    results = asyncio.run(eval_run.run_suite(tasks, agents, args.trials, out, repo=Path(args.repo) if args.repo else None,
                                             parallel=args.parallel, rubric=_rubric_for(args)))
    print(eval_run.render_markdown(results, args.trials))
    print(f"\nraw trials, logs and diffs: {out}")
    return 0


def _compare_cmd(args: argparse.Namespace) -> int:
    from ..config import get_config

    dirs = eval_task.discover(args.suite)
    if not dirs:
        print("gdw eval compare-routing: no tasks in the suite", file=sys.stderr)
        return 2
    tasks = [eval_task.load(d) for d in dirs]
    try:
        # The preview needs only the config: no AppState, no provider, no trial, no grader command.
        plan = eval_run.plan_compare(get_config(), tasks, baseline_tier=args.baseline_tier, job_type=args.job_type,
                                     effort=args.effort, trials=args.trials, max_spend_usd=args.max_spend_usd)
    except ValueError as e:
        print(f"gdw eval compare-routing: {e}", file=sys.stderr)
        return 2
    if not args.approve_paid:
        print(eval_run.render_plan(plan))
        return 0
    if not plan["eligible"]:
        print("gdw eval compare-routing: no eligible tasks in the suite", file=sys.stderr)
        return 2
    app = _cli_state()
    out = Path(args.out or f"evals/runs/compare-{time.strftime('%Y%m%d-%H%M%S')}")
    rep = asyncio.run(eval_run.compare_routing(app, tasks, baseline_tier=args.baseline_tier, job_type=args.job_type,
                                               effort=args.effort, trials=args.trials,
                                               max_spend_usd=args.max_spend_usd, out_dir=out,
                                               repo=Path(args.repo) if args.repo else None))
    print(eval_run.render_compare_markdown(rep))
    print(f"report, raw trials, logs and diffs: {out}")
    return 0


def _export_cmd(args: argparse.Namespace) -> int:
    dirs = [Path(t) for t in args.tasks] or eval_task.discover(args.suite)
    if not dirs:
        print("gdw eval export: no tasks given and none in the suite", file=sys.stderr)
        return 2
    code = 0
    for d in dirs:
        task = eval_task.load(d)
        try:
            out = eval_export.export(task, Path(args.out), repo=Path(args.repo) if args.repo else None,
                                     base_image=args.base_image, clone_url=args.clone_url, org=args.org,
                                     docker_setup=args.docker_setup or "")
            print(f"{task.task.id}: {out}")
        except eval_export.ExportError as e:
            print(f"{task.task.id}: skipped: {e}", file=sys.stderr)
            code = 1
    return code


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
        rewrite, by = make_rewrite(_cli_state(), model=args.model, effort=args.effort)
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
    g = sub.add_parser("grade", help="grade one candidate change against a task")
    g.add_argument("task", help="the task directory")
    g.add_argument("--patch", required=True, help="the candidate's diff against the start commit ('-' = stdin)")
    g.add_argument("--repo", help="the git repository holding the start commit (default: the task's source.repo)")
    g.add_argument("--json", action="store_true")
    g.add_argument("--rubric-model", help="grade rubric.md with this model (effort gate applies)")
    g.add_argument("--effort", default="low", choices=list(EFFORT_LEVELS))
    g.set_defaults(fn=_grade_cmd)
    v = sub.add_parser("validate", help="check graders: the reference passes, flawed solutions fail")
    v.add_argument("tasks", nargs="*", help="task directories (default: every task in --suite)")
    v.add_argument("--suite", default=DEFAULT_SUITE)
    v.add_argument("--repo", help="the git repository holding the start commits (default: each task's source.repo)")
    v.add_argument("--mutants", type=int, default=12)
    v.add_argument("--partials", type=int, default=6)
    v.add_argument("--markdown", action="store_true")
    v.add_argument("--json", action="store_true")
    v.add_argument("--rubric-model")
    v.add_argument("--effort", default="low", choices=list(EFFORT_LEVELS))
    v.set_defaults(fn=_validate_cmd)
    r = sub.add_parser("run", help="run agents on tasks, k trials each; reports pass@k, cost, time, tool calls")
    r.add_argument("tasks", nargs="*", help="task directories (default: every task in --suite)")
    r.add_argument("--suite", default=DEFAULT_SUITE)
    r.add_argument("--agents", required=True, help=f"comma-separated: {', '.join(AGENTS)}")
    r.add_argument("--trials", type=int, default=1, help="k: trials per task and agent")
    r.add_argument("--parallel", type=int, default=1)
    r.add_argument("--out", help="results directory (default evals/runs/<time>)")
    r.add_argument("--repo", help="the git repository holding the start commits (default: each task's source.repo)")
    r.add_argument("--tier", default="claude.standard", help="builtin: the model tier")
    r.add_argument("--claude-model", help="claude_code: --model for the CLI")
    r.add_argument("--codex-model", help="codex: -m for the CLI")
    r.add_argument("--glm-model", default=GLM_MODEL, help="claude_code_glm: the arkcli model id for the helpers")
    r.add_argument("--rubric-model")
    r.add_argument("--effort", default="low", choices=list(EFFORT_LEVELS))
    r.set_defaults(fn=_run_cmd)
    c = sub.add_parser("compare-routing", help="pinned tier vs tier=auto on the same tasks (preview unless --approve-paid)")
    c.add_argument("--suite", default=DEFAULT_SUITE)
    c.add_argument("--baseline-tier", required=True, help="the pinned arm's tier, e.g. codex.standard")
    c.add_argument("--job-type", required=True, help="the router rule to exercise (extract, mechanical_edit, implement_feature)")
    c.add_argument("--trials", type=int, required=True, help="trials per task and arm")
    c.add_argument("--max-spend-usd", type=float, required=True, help="recorded-spend threshold for the whole run")
    c.add_argument("--approve-paid", action="store_true", help="really run it: paid model calls on your accounts")
    c.add_argument("--out", help="results directory (default evals/runs/compare-<time>)")
    c.add_argument("--repo", help="the git repository holding the start commits (default: each task's source.repo)")
    c.add_argument("--effort", default="low", choices=list(EFFORT_LEVELS))
    c.set_defaults(fn=_compare_cmd)
    x = sub.add_parser("export", help="write tasks as Harbor tasks (the Terminal-Bench 2.0 format)")
    x.add_argument("tasks", nargs="*", help="task directories (default: every task in --suite)")
    x.add_argument("--suite", default=DEFAULT_SUITE)
    x.add_argument("--out", required=True)
    x.add_argument("--repo", help="the git repository holding the start commits (default: each task's source.repo)")
    x.add_argument("--base-image", default="python:3.12-slim")
    x.add_argument("--clone-url", help="have the image clone this URL instead of copying a snapshot of the repo")
    x.add_argument("--org", default="gdh", help="the [task] name prefix (org/name)")
    x.add_argument("--docker-setup", help="an extra RUN line for the image only, e.g. installing dependencies")
    x.set_defaults(fn=_export_cmd)
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
    except (eval_forge.ForgeError, eval_task.EvalTaskError, eval_grade.GradeError, eval_export.ExportError,
            OSError) as e:
        print(f"gdw eval {args.cmd}: {e}", file=sys.stderr)
        return 2
    except EffortApprovalRequired as e:
        print(f"gdw eval {args.cmd}: {e}", file=sys.stderr)
        return 2
    finally:
        states, _STARTED[:] = list(_STARTED), []
        if states:
            asyncio.run(_drain(states))


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
