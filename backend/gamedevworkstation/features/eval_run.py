"""`gdw eval run`: run agents on Eval Forge tasks, k trials each, and score them.

Each trial gets a fresh throwaway worktree at the task's start commit, the task prompt and nothing else (the
hidden tests aren't in the tree). After the agent stops, the tree is graded like any candidate, the failure (if
any) is attributed, and the trial is written to <out>/<task>/<agent>/trial-<n>.json with the agent's raw log.

Agents
- claude_code  the user's `claude` CLI in print mode, logged in with their subscription (no API keys reach it);
               Bash and file tools allowed inside the trial worktree. Its cost is the CLI's API-equivalent figure.
- codex        `codex exec` in its workspace-write sandbox (it can only write inside the trial worktree).
- builtin      GameDevWorkstation's own subagent loop with file tools (read, search, write, edit, delete) and no
               shell, so it can't run tests itself; spend caps and the effort gate apply as in the app.

Scores: pass@k with the unbiased estimator 1 - C(n-c, k) / C(n, k) over n trials with c passes, plus mean
cost, wall time and tool calls, and how many failures blame the agent, the environment or the grader.
Nothing here runs unless someone asks for it: a real run costs model usage.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import shutil
import time
from dataclasses import asdict, dataclass, field
from math import comb
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from . import eval_attribute, eval_grade, eval_validate
from .eval_task import LoadedTask, Limits

if TYPE_CHECKING:
    from ..app import AppState

FILE_TOOLS = ["read_file", "list_dir", "search", "write_file", "edit_file", "delete_file"]
TASK_PREAMBLE = ("You are working in a git checkout of a project. Make the change described below by editing the "
                 "files in this directory. Don't commit. When you're done, stop.\n\n")


@dataclass
class AgentResult:
    error: str = ""
    timed_out: bool = False
    cost_usd: float | None = None
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    log: str = ""          # raw output (stream-json / JSONL / transcript), saved next to the trial


AgentFn = Callable[[str, Path, Limits], Awaitable[AgentResult]]


@dataclass
class Trial:
    task: str
    agent: str
    trial: int
    passed: bool
    blame: str
    reason: str
    wall_s: float
    cost_usd: float | None
    tool_calls: int
    input_tokens: int
    output_tokens: int
    agent_error: str
    timed_out: bool
    tampered: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    diff_lines: int = 0
    started_at: str = ""


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k (Chen et al. 2021): the chance at least one of k samples drawn from n trials passes."""
    if n <= 0 or k <= 0:
        return 0.0
    k = min(k, n)
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


# ------------------------------------------------------------------ agents


async def _proc(argv: list[str], cwd: Path, env: dict[str, str], timeout: float) -> tuple[int | None, str, bool]:
    p = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                             start_new_session=True)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
        return p.returncode, out.decode("utf-8", "replace"), False
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, 9)
        out = b""
        with contextlib.suppress(Exception):
            out, _ = await asyncio.wait_for(p.communicate(), 10)
        return None, out.decode("utf-8", "replace"), True


def parse_claude_stream(text: str) -> AgentResult:
    """Tool calls, tokens, cost and errors from `claude -p --output-format stream-json --verbose` output."""
    r = AgentResult(log=text)
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    r.tool_calls += 1
        elif ev.get("type") == "result":
            r.cost_usd = ev.get("total_cost_usd", ev.get("cost_usd"))
            u = ev.get("usage") or {}
            r.input_tokens = int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + \
                int(u.get("cache_creation_input_tokens") or 0)
            r.output_tokens = int(u.get("output_tokens") or 0)
            if ev.get("is_error"):
                r.error = str(ev.get("result") or ev.get("subtype") or "error")[:500]
    return r


def parse_codex_jsonl(text: str) -> AgentResult:
    """Tool calls (commands, file changes, MCP calls) and tokens from `codex exec --json` output."""
    r = AgentResult(log=text)
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "item.completed" and (ev.get("item") or {}).get("type") in ("command_execution", "file_change",
                                                                           "mcp_tool_call", "web_search"):
            r.tool_calls += 1
        elif t == "turn.completed":
            u = ev.get("usage") or {}
            r.input_tokens += int(u.get("input_tokens") or 0)
            r.output_tokens += int(u.get("output_tokens") or 0)
        elif t in ("error", "turn.failed"):
            r.error = str(ev.get("message") or (ev.get("error") or {}).get("message") or t)[:500]
    return r


def claude_code_agent(app: "AppState | None" = None, *, model: str | None = None) -> AgentFn:
    from .claude_cli import child_env, find_cli

    async def run(prompt: str, tree: Path, limits: Limits) -> AgentResult:
        cli = find_cli(app.config) if app is not None else shutil.which("claude")
        if not cli:
            return AgentResult(error="the claude CLI isn't installed")
        argv = [cli, "-p", TASK_PREAMBLE + prompt, "--output-format", "stream-json", "--verbose",
                "--permission-mode", "acceptEdits", "--allowedTools", "Bash,Read,Edit,Write,MultiEdit,Glob,Grep,LS",
                "--max-budget-usd", f"{limits.max_cost_usd:g}"]
        if model:
            argv += ["--model", model]
        code, out, timed_out = await _proc(argv, tree, child_env(), limits.agent_timeout_s)
        r = parse_claude_stream(out)
        r.timed_out = timed_out
        if code not in (0, None) and not r.error:
            r.error = f"claude exited {code}: {out.strip().splitlines()[-1][:300] if out.strip() else ''}"
        return r

    return run


def codex_agent(*, model: str | None = None) -> AgentFn:
    async def run(prompt: str, tree: Path, limits: Limits) -> AgentResult:
        cli = shutil.which("codex")
        if not cli:
            return AgentResult(error="the codex CLI isn't installed")
        argv = [cli, "exec", "--json", "-s", "workspace-write", "--skip-git-repo-check", "-C", str(tree)]
        if model:
            argv += ["-m", model]
        code, out, timed_out = await _proc(argv + [TASK_PREAMBLE + prompt], tree, dict(os.environ),
                                           limits.agent_timeout_s)
        r = parse_codex_jsonl(out)
        r.timed_out = timed_out
        if code not in (0, None) and not r.error:
            r.error = f"codex exited {code}: {out.strip().splitlines()[-1][:300] if out.strip() else ''}"
        return r

    return run


def builtin_agent(app: "AppState", *, tier: str = "claude.standard", effort: str = "low") -> AgentFn:
    from ..agent.tools import ToolContext
    from .subagents import SubagentManager

    async def run(prompt: str, tree: Path, limits: Limits) -> AgentResult:
        mgr = app.extensions.get("subagents") or SubagentManager(app)
        session = app.store.create(folder=str(tree), mode="accept_edits")
        ctx = ToolContext(app=app, session=session, run_id="eval-" + secrets.token_hex(4))
        try:
            sub = await mgr.spawn(ctx, {"name": "eval", "tier": tier, "effort": effort, "tools": FILE_TOOLS,
                                        "instructions": TASK_PREAMBLE + prompt, "max_turns": 60})
        except Exception as e:  # noqa: BLE001 — spend cap, effort gate, missing key: never started
            return AgentResult(error=f"{type(e).__name__}: {e}"[:500])
        try:
            await asyncio.wait_for(sub.done_event.wait(), limits.agent_timeout_s)
        except asyncio.TimeoutError:
            await mgr.stop(sub.id)
            return AgentResult(timed_out=True, cost_usd=sub.usage.cost_usd)
        history = [m.model_dump() for m in sub.history]
        if not history:
            from ..config import data_dir

            f = data_dir() / "subagents" / f"{sub.id}.json"
            history = json.loads(f.read_text(encoding="utf-8")).get("history", []) if f.exists() else []
        calls = sum(1 for m in history for b in (m.get("content") or []) if isinstance(b, dict) and b.get("type") == "tool_use")
        return AgentResult(error=sub.error or "", cost_usd=sub.usage.cost_usd, tool_calls=calls,
                           input_tokens=sub.usage.total_input, output_tokens=sub.usage.output_tokens,
                           log=json.dumps(history, default=str))

    return run


# ------------------------------------------------------------------ trials


def _validation(task: LoadedTask) -> dict | None:
    p = task.dir / eval_validate.REPORT_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


async def run_trial(task: LoadedTask, agent_name: str, agent: AgentFn, n: int, out_dir: Path, *,
                    repo: Path | None = None, unity_replay=None, rubric=None) -> Trial:
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    src = Path(repo or task.task.source.repo)
    logdir = out_dir / task.task.id / agent_name
    logdir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    grade: eval_grade.Grade | None = None
    diff = ""
    with eval_grade.checkout(src, task.task.source.parent) as tree:
        setup_failed = False
        if task.task.grader.setup:
            code, out, _, _ = eval_grade.run_shell(task.task.grader.setup, tree, task.task.grader.timeout_s)
            setup_failed = code != 0
        if setup_failed:
            res = AgentResult(error="the task's setup command failed before the agent started (environment)")
            grade = eval_grade.Grade(False, [eval_grade.Step("setup", "setup", False, environment=True)])
        else:
            res = await agent(task.prompt, tree, task.task.limits)
            wall = time.monotonic() - t0
            diff = eval_grade.tree_diff(tree)
            if not (res.error and not diff.strip()) and not (res.timed_out and not diff.strip()):
                if task.task.grader.differential is not None:
                    with eval_grade.checkout(src, task.task.source.parent) as ref:
                        eval_grade.apply_patch(ref, task.solution)
                        grade = await eval_grade.grade(task, tree, reference=ref, unity_replay=unity_replay, rubric=rubric)
                else:
                    grade = await eval_grade.grade(task, tree, unity_replay=unity_replay, rubric=rubric)
    wall = time.monotonic() - t0
    att = eval_attribute.attribute(grade, agent_error=res.error, agent_timed_out=res.timed_out,
                                   validation=_validation(task))
    trial = Trial(task=task.task.id, agent=agent_name, trial=n, passed=bool(grade and grade.passed and not res.error),
                  blame=att.blame, reason=att.reason, wall_s=round(wall, 1),
                  cost_usd=round(res.cost_usd, 4) if res.cost_usd is not None else None, tool_calls=res.tool_calls,
                  input_tokens=res.input_tokens, output_tokens=res.output_tokens, agent_error=res.error,
                  timed_out=res.timed_out, tampered=grade.tampered if grade else [],
                  failed_steps=[s.name for s in grade.steps if not s.passed] if grade else [],
                  diff_lines=sum(1 for l in diff.splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---")),
                  started_at=started)
    (logdir / f"trial-{n}.json").write_text(json.dumps({**asdict(trial), "grade": grade.to_dict() if grade else None},
                                                       indent=1), encoding="utf-8")
    (logdir / f"trial-{n}.log").write_text(res.log, encoding="utf-8")
    (logdir / f"trial-{n}.diff").write_text(diff, encoding="utf-8")
    return trial


async def run_suite(tasks: list[LoadedTask], agents: dict[str, AgentFn], trials: int, out_dir: Path, *,
                    repo: Path | None = None, parallel: int = 1, unity_replay=None, rubric=None) -> list[Trial]:
    sem = asyncio.Semaphore(max(1, parallel))

    async def one(t: LoadedTask, name: str, fn: AgentFn, n: int) -> Trial:
        async with sem:
            return await run_trial(t, name, fn, n, out_dir, repo=repo, unity_replay=unity_replay, rubric=rubric)

    jobs = [one(t, name, fn, n) for t in tasks for name, fn in agents.items() for n in range(1, trials + 1)]
    results = list(await asyncio.gather(*jobs))
    (out_dir / "results.json").write_text(json.dumps({"trials": [asdict(r) for r in results],
                                                      "summary": summarize(results, trials)}, indent=1),
                                          encoding="utf-8")
    return results


def summarize(results: list[Trial], k: int) -> list[dict]:
    rows = []
    for agent in sorted({r.agent for r in results}):
        rs = [r for r in results if r.agent == agent]
        by_task: dict[str, list[Trial]] = {}
        for r in rs:
            by_task.setdefault(r.task, []).append(r)
        p1 = sum(pass_at_k(len(v), sum(x.passed for x in v), 1) for v in by_task.values()) / len(by_task)
        pk = sum(pass_at_k(len(v), sum(x.passed for x in v), k) for v in by_task.values()) / len(by_task)
        costs = [r.cost_usd for r in rs if r.cost_usd is not None]
        rows.append({"agent": agent, "tasks": len(by_task), "trials": len(rs), "passed": sum(r.passed for r in rs),
                     "pass@1": round(p1, 3), f"pass@{k}": round(pk, 3),
                     "mean_cost_usd": round(sum(costs) / len(costs), 4) if costs else None,
                     "mean_wall_s": round(sum(r.wall_s for r in rs) / len(rs), 1),
                     "mean_tool_calls": round(sum(r.tool_calls for r in rs) / len(rs), 1),
                     "blame": {b: sum(1 for r in rs if r.blame == b) for b in ("agent", "environment", "grader")}})
    return rows


def render_markdown(results: list[Trial], k: int) -> str:
    rows = summarize(results, k)
    out = [f"| Agent | Tasks | pass@1 | pass@{k} | Mean cost | Mean wall | Mean tool calls | Failures: agent / env / grader |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        cost = f"${r['mean_cost_usd']:.3f}" if r["mean_cost_usd"] is not None else "n/a"
        b = r["blame"]
        out.append(f"| {r['agent']} | {r['tasks']} | {r['pass@1']:.0%} | {r[f'pass@{k}']:.0%} | {cost} | "
                   f"{r['mean_wall_s']:.0f}s | {r['mean_tool_calls']:.0f} | {b['agent']} / {b['environment']} / {b['grader']} |")
    return "\n".join(out)
