"""`gdw eval run`: run agents on Eval Forge tasks, k trials each, and score them.

Each trial gets a fresh throwaway worktree at the task's start commit, the task prompt and nothing else (the
hidden tests aren't in the tree). After the agent stops, the tree is graded like any candidate, the failure (if
any) is attributed, and the trial is written to <out>/<task>/<agent>/trial-<n>.json with the agent's raw log.

Agents
- claude_code  the user's `claude` CLI in print mode, logged in with their subscription (no API keys reach it);
               Bash and file tools allowed inside the trial worktree. Its cost is the CLI's API-equivalent figure.
- claude_code_glm  the same, told it may hand side work (reading, summarizing, drafting) to GLM Flash subagents
               through `arkcli +chat` from Bash; each trial counts those calls.
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
    helper_calls: int = 0  # subagent calls the agent made through a helper CLI (claude_code_glm: arkcli +chat)
    model: str = ""        # the model the agent reported using, when it says
    log: str = ""          # raw output (stream-json / JSONL / transcript), saved next to the trial
    session_id: str = ""   # builtin: the trial's session, the key to its usage-ledger rows
    fallbacks: int = 0     # builtin: stronger-model switches the router made during the trial
    attempts: list[dict] = field(default_factory=list)  # builtin: {tier, model, reason} per model segment
    policy_revision: str = ""  # builtin, auto arm: the [model_routing] revision that chose the model


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
    helper_calls: int = 0
    model: str = ""


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
        if ev.get("type") == "system" and ev.get("subtype") == "init" and ev.get("model"):
            r.model = str(ev["model"])
        elif ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    r.tool_calls += 1
                    if block.get("name") == "Bash" and "arkcli +chat" in str((block.get("input") or {}).get("command")):
                        r.helper_calls += 1
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


GLM_HELPER = ("You can hand side work to cheap GLM Flash subagents and run several at once: reading or summarizing "
              "large files, drafting boilerplate, first-pass reviews. Call one from Bash with\n"
              "  arkcli +chat --model {model} --no-progress --thinking disabled --instructions \"<role>\" \"<task>\"\n"
              "(add --input @<file> to attach a file; the answer is printed). Check what they return before you use "
              "it; you're responsible for the result. Do the judgement and the final edits yourself.\n\n")


def claude_code_agent(app: "AppState | None" = None, *, model: str | None = None,
                      helper_model: str | None = None) -> AgentFn:
    """The claude CLI on a trial; with `helper_model`, it's told it may use GLM Flash subagents via arkcli."""
    from .claude_cli import child_env, find_cli

    async def run(prompt: str, tree: Path, limits: Limits) -> AgentResult:
        cli = find_cli(app.config) if app is not None else shutil.which("claude")
        if not cli:
            return AgentResult(error="the claude CLI isn't installed")
        if helper_model and not shutil.which("arkcli"):
            return AgentResult(error="arkcli isn't installed, so the GLM helpers can't run")
        preamble = TASK_PREAMBLE + (GLM_HELPER.format(model=helper_model) if helper_model else "")
        argv = [cli, "-p", preamble + prompt, "--output-format", "stream-json", "--verbose",
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


def builtin_agent(app: "AppState", *, tier: str = "claude.standard", effort: str = "low",
                  job_type: str | None = None, provider: str | None = None,
                  allowance: Callable[[], float] | None = None) -> AgentFn:
    """The builtin subagent loop. `job_type` goes to the router (use with tier="auto"); `allowance` returns the
    dollars an approved batch may still spend, and bounds the unit's run cap together with Limits.max_cost_usd."""
    from ..agent.tools import ToolContext
    from .subagents import SubagentManager

    async def run(prompt: str, tree: Path, limits: Limits) -> AgentResult:
        mgr = app.extensions.get("subagents") or SubagentManager(app)
        session = app.store.create(folder=str(tree), mode="accept_edits")
        ctx = ToolContext(app=app, session=session, run_id="eval-" + secrets.token_hex(4))
        cap = limits.max_cost_usd
        if allowance is not None:
            cap = min(cap, allowance())
            if cap <= 0:
                return AgentResult(error="BudgetExceeded: the approved spend allowance is used up", session_id=session["id"])
        args = {"name": "eval", "tier": tier, "effort": effort, "tools": FILE_TOOLS,
                "instructions": TASK_PREAMBLE + prompt, "max_turns": 60, "run_cap_usd": cap}
        if job_type:
            args["job_type"] = job_type
        if provider:
            args["provider"] = provider
        try:
            sub = await mgr.spawn(ctx, args)
        except Exception as e:  # noqa: BLE001 — spend cap, effort gate, missing key: never started
            return AgentResult(error=f"{type(e).__name__}: {e}"[:500], session_id=session["id"])
        route = sub.route.revision if sub.route else ""
        try:
            await asyncio.wait_for(sub.done_event.wait(), limits.agent_timeout_s)
        except asyncio.TimeoutError:
            await mgr.stop(sub.id)
            return AgentResult(timed_out=True, cost_usd=sub.usage.cost_usd, session_id=session["id"],
                               fallbacks=sub.escalations, attempts=list(sub.attempts), model=sub.model,
                               policy_revision=route)
        history = [m.model_dump() for m in sub.history]
        if not history:
            from ..config import data_dir

            f = data_dir() / "subagents" / f"{sub.id}.json"
            history = json.loads(f.read_text(encoding="utf-8")).get("history", []) if f.exists() else []
        calls = sum(1 for m in history for b in (m.get("content") or []) if isinstance(b, dict) and b.get("type") == "tool_use")
        return AgentResult(error=sub.error or "", cost_usd=sub.usage.cost_usd, tool_calls=calls,
                           input_tokens=sub.usage.total_input, output_tokens=sub.usage.output_tokens,
                           log=json.dumps(history, default=str), session_id=session["id"], fallbacks=sub.escalations,
                           attempts=list(sub.attempts), model=sub.model, policy_revision=route)

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
    src = eval_grade.resolve_repo(task, repo)
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
                  helper_calls=res.helper_calls, model=res.model,
                  failed_steps=[s.name for s in grade.steps if not s.passed] if grade else [],
                  diff_lines=sum(1 for l in diff.splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---")),
                  started_at=started)
    (logdir / f"trial-{n}.json").write_text(json.dumps({**asdict(trial), "grade": grade.to_dict() if grade else None},
                                                       indent=1), encoding="utf-8")
    (logdir / f"trial-{n}.log").write_text(res.log, encoding="utf-8")
    (logdir / f"trial-{n}.diff").write_text(diff, encoding="utf-8")
    (logdir / f"trial-{n}.prompt.md").write_text(task.prompt, encoding="utf-8")  # what the agent saw (Review Desk)
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
                     "mean_helper_calls": round(sum(r.helper_calls for r in rs) / len(rs), 1),
                     "models": sorted({r.model for r in rs if r.model}),
                     "blame": {b: sum(1 for r in rs if r.blame == b) for b in ("agent", "environment", "grader")}})
    return rows


def render_markdown(results: list[Trial], k: int) -> str:
    rows = summarize(results, k)
    pk = f" pass@{k} |" if k > 1 else ""
    out = [f"| Agent | Tasks | pass@1 |{pk} Mean cost | Mean wall | Mean tool calls | Mean helper calls | "
           "Failures: agent / env / grader |",
           "|---|---|---|" + ("---|" if k > 1 else "") + "---|---|---|---|---|"]
    for r in rows:
        cost = f"${r['mean_cost_usd']:.3f}" if r["mean_cost_usd"] is not None else "n/a"
        b = r["blame"]
        kcol = f" {r[f'pass@{k}']:.0%} |" if k > 1 else ""
        out.append(f"| {r['agent']} | {r['tasks']} | {r['pass@1']:.0%} |{kcol} {cost} | "
                   f"{r['mean_wall_s']:.0f}s | {r['mean_tool_calls']:.0f} | {r['mean_helper_calls']:.1f} | "
                   f"{b['agent']} / {b['environment']} / {b['grader']} |")
    return "\n".join(out)


# ------------------------------------------------------------------ compare-routing (D7)
# Pinned baseline tier vs `tier = "auto"` through the real router, paired and interleaved by task and trial. The
# preview (plan_compare) needs only the config; nothing here builds a model client unless compare_routing runs.

COMPARE_SCHEMA = "gdw.eval.compare-routing/1"
SMALL_SAMPLE_PAIRS = 10
PINNED, ROUTED = "pinned", "routed"


def split_tasks(tasks: list[LoadedTask]) -> tuple[list[LoadedTask], list[dict]]:
    """The deterministic code subset of a suite, and why each other task is left out."""
    keep, out = [], []
    for t in tasks:
        g = t.task.grader
        why = []
        if t.task.kind == "unity" or g.unity is not None:
            why.append("needs Unity replay")
        if g.rubric:
            why.append("needs a paid rubric grader")
        if not why and not (g.command or g.checks or g.differential):
            why.append("no deterministic grader")
        if why:
            out.append({"task": t.task.id, "reason": "; ".join(why)})
        else:
            keep.append(t)
    return keep, out


def _active_cap(cfg) -> float | None:
    return float(cfg.delegation.get("subagent_spend_cap_usd") or 0) or None


def plan_compare(cfg, tasks: list[LoadedTask], *, baseline_tier: str, job_type: str, effort: str, trials: int,
                 max_spend_usd: float) -> dict:
    """What a paid run would do, from the config and the loaded suite only. Raises ValueError on a bad request."""
    from . import routing_policy

    if trials < 1:
        raise ValueError("--trials must be at least 1")
    if max_spend_usd <= 0:
        raise ValueError("--max-spend-usd must be above 0")
    if job_type not in routing_policy.JOB_TYPES:
        raise ValueError(f"--job-type takes {', '.join(routing_policy.JOB_TYPES)}")
    base_model = cfg.resolve(baseline_tier)
    if base_model not in cfg.models:
        raise ValueError(f"unknown --baseline-tier {baseline_tier!r}: no model {base_model!r} is configured")
    provider = cfg.models[base_model].provider
    if baseline_tier in routing_policy.PINNED_TIERS:
        raise ValueError(f"{baseline_tier} runs outside the API loop; pick an API tier")
    keep, excluded = split_tasks(tasks)
    rows = []
    for t in keep:  # the router sees the prompt the agent sees, never the graders
        r = routing_policy.select(cfg, job_type=job_type, effort=effort, instructions=TASK_PREAMBLE + t.prompt,
                                  provider=provider)
        rows.append({"task": t.task.id, "baseline_model": base_model, "routed_tier": r.tier, "routed_model": r.model,
                     "reason": r.reason, "check": r.check, "fallbacks": list(r.chain), "revision": r.revision,
                     "changed": r.model != base_model, "max_cost_usd": t.task.limits.max_cost_usd})
    cap = _active_cap(cfg)
    per_trial = [min([x for x in (row["max_cost_usd"], max_spend_usd, cap) if x]) for row in rows]
    return {"schema": COMPARE_SCHEMA, "job_type": job_type, "baseline_tier": baseline_tier, "baseline_model": base_model,
            "effort": effort, "trials": trials, "eligible": rows, "excluded": excluded,
            "arm_runs": 2 * len(rows) * trials, "max_spend_usd": max_spend_usd, "active_cap_usd": cap,
            "per_trial_cap_usd": max(per_trial) if per_trial else None,
            "no_selection_change": bool(rows) and not any(r["changed"] for r in rows)}


def render_plan(plan: dict) -> str:
    L = [f"gdw eval compare-routing: PREVIEW (no model client, trial or grader was started)", "",
         f"job type:        {plan['job_type']}",
         f"pinned arm:      {plan['baseline_tier']} -> {plan['baseline_model']}",
         f"routed arm:      tier=auto (job type {plan['job_type']}), same effort ({plan['effort']}), prompt, tools and graders",
         f"eligible tasks:  {len(plan['eligible'])}   trials per arm: {plan['trials']}   "
         f"arm runs: {plan['arm_runs']} (paired, interleaved)"]
    for r in plan["eligible"]:
        fb = f", fallbacks {', '.join(r['fallbacks'])}" if r["fallbacks"] else ""
        L.append(f"  {r['task']}: pinned {r['baseline_model']}; routed {r['routed_tier']} -> {r['routed_model']} "
                 f"({r['reason']}{fb}){'' if r['changed'] else ' [same model]'}")
    if plan["no_selection_change"]:
        L.append("  The router picks the baseline model for every eligible task: no selection change to measure.")
    L.append(f"excluded tasks:  {len(plan['excluded'])}")
    for x in plan["excluded"]:
        L.append(f"  {x['task']}: {x['reason']}")
    cap = f"${plan['active_cap_usd']:.2f}" if plan["active_cap_usd"] else "none"
    L += ["", f"spend ceiling:   ${plan['max_spend_usd']:.2f} recorded spend across both arms (admission stops at it; "
          "the last request may overrun it)",
          f"per-run cap:     the smaller of the task's max_cost_usd, the remaining allowance and the active "
          f"subagent cap ({cap}); at most ${plan['per_trial_cap_usd'] or 0:.2f} for any one run",
          "", "Nothing was run. Add --approve-paid to run it; that makes paid model calls on your accounts."]
    return "\n".join(L)


def ledger_spend(app: "AppState", session_ids: list[str]) -> dict:
    """Full-precision ledger totals for the trial sessions: failed attempts and fallbacks included."""
    ids = [i for i in dict.fromkeys(session_ids) if i]
    if not ids:
        return {"cost_usd": 0.0, "requests": 0, "failed": 0, "models": []}
    q = ",".join("?" * len(ids))
    r = app.db.one(f"SELECT COALESCE(SUM(cost_usd),0) c, COUNT(*) n, COALESCE(SUM(1-ok),0) f FROM usage_records "
                   f"WHERE session_id IN ({q})", ids)
    models = [m["model"] for m in app.db.all(f"SELECT DISTINCT model FROM usage_records WHERE session_id IN ({q}) "
                                             "ORDER BY model", ids)]
    return {"cost_usd": float(r["c"]), "requests": int(r["n"]), "failed": int(r["f"]), "models": models}


def _usable(rec: dict | None) -> bool:
    """A trial that says something about the model: not an environment or grader failure."""
    return rec is not None and rec["blame"] not in ("environment", "grader")


async def compare_routing(app: "AppState", tasks: list[LoadedTask], *, baseline_tier: str, job_type: str,
                          effort: str, trials: int, max_spend_usd: float, out_dir: Path,
                          repo: Path | None = None) -> dict:
    """Paid mode: run both arms, task by task and trial by trial, and write compare-routing.json / .md."""
    plan = plan_compare(app.config, tasks, baseline_tier=baseline_tier, job_type=job_type, effort=effort,
                        trials=trials, max_spend_usd=max_spend_usd)
    keep, _ = split_tasks(tasks)
    provider = app.config.model(plan["baseline_model"]).provider
    sessions: list[str] = []

    def allowance() -> float:
        return max_spend_usd - ledger_spend(app, sessions)["cost_usd"]

    arms: dict[str, AgentFn] = {
        PINNED: builtin_agent(app, tier=baseline_tier, effort=effort, job_type=job_type, provider=provider,
                              allowance=allowance),
        ROUTED: builtin_agent(app, tier="auto", effort=effort, job_type=job_type, provider=provider,
                              allowance=allowance)}
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs: list[dict] = []
    stopped = False
    for t in keep:
        for n in range(1, trials + 1):
            pair: dict = {"task": t.task.id, "trial": n, PINNED: None, ROUTED: None,
                          "order": [PINNED, ROUTED] if n % 2 else [ROUTED, PINNED]}  # alternate who goes first
            pairs.append(pair)
            for arm in pair["order"]:
                if allowance() <= 0:
                    stopped = True
                    break
                box: list[AgentResult] = []

                async def captured(prompt, tree, limits, _fn=arms[arm], _box=box):
                    r = await _fn(prompt, tree, limits)
                    _box.append(r)
                    if r.session_id:
                        sessions.append(r.session_id)
                    return r

                trial = await run_trial(t, arm, captured, n, out_dir, repo=repo)
                res = box[0] if box else AgentResult()
                led = ledger_spend(app, [res.session_id])
                pair[arm] = {**asdict(trial), "session_id": res.session_id, "spend_usd": led["cost_usd"],
                             "requests": led["requests"], "failed_requests": led["failed"],
                             "ledger_models": led["models"], "fallbacks": res.fallbacks, "attempts": res.attempts,
                             "policy_revision": res.policy_revision,
                             "stopped_at_cap": "BudgetExceeded" in res.error}
            if stopped:
                break
        if stopped:
            break
    report = build_compare_report(plan, pairs, stopped=stopped, spent=ledger_spend(app, sessions))
    (out_dir / "compare-routing.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out_dir / "compare-routing.md").write_text(render_compare_markdown(report), encoding="utf-8")
    return report


def _trial_from(rec: dict) -> Trial:
    keys = Trial.__dataclass_fields__
    return Trial(**{k: rec[k] for k in keys if k in rec})


def build_compare_report(plan: dict, pairs: list[dict], *, stopped: bool, spent: dict) -> dict:
    k, planned = plan["trials"], len(plan["eligible"]) * plan["trials"]
    arm_recs = {a: [p[a] for p in pairs if p[a] is not None] for a in (PINNED, ROUTED)}
    complete = [p for p in pairs if p[PINNED] and p[ROUTED]]
    valid = [p for p in complete if _usable(p[PINNED]) and _usable(p[ROUTED])]
    arms = {}
    for a, recs in arm_recs.items():
        summ = summarize([_trial_from(r) for r in recs], k)
        arms[a] = {"trials": len(recs), "passed": sum(r["passed"] for r in recs),
                   "pass@1": summ[0]["pass@1"] if summ else None, f"pass@{k}": summ[0][f"pass@{k}"] if summ else None,
                   "spend_usd": sum(r["spend_usd"] for r in recs), "requests": sum(r["requests"] for r in recs),
                   "failed_requests": sum(r["failed_requests"] for r in recs),
                   "fallbacks": sum(r["fallbacks"] for r in recs),
                   "wall_s": round(sum(r["wall_s"] for r in recs), 1),
                   "environment_failures": sum(r["blame"] == "environment" for r in recs),
                   "grader_failures": sum(r["blame"] == "grader" for r in recs),
                   "models": sorted({m for r in recs for m in r["ledger_models"]})}
    n = len(valid)
    pp, rp = sum(p[PINNED]["passed"] for p in valid), sum(p[ROUTED]["passed"] for p in valid)
    pinned_spend, routed_spend = (sum(p[a]["spend_usd"] for p in valid) for a in (PINNED, ROUTED))
    paired = {"pairs": n, "pinned_pass_rate": pp / n if n else None, "routed_pass_rate": rp / n if n else None,
              "both_pass": sum(p[PINNED]["passed"] and p[ROUTED]["passed"] for p in valid),
              "both_fail": sum(not p[PINNED]["passed"] and not p[ROUTED]["passed"] for p in valid),
              "only_pinned_passes": sum(p[PINNED]["passed"] and not p[ROUTED]["passed"] for p in valid),
              "only_routed_passes": sum(p[ROUTED]["passed"] and not p[PINNED]["passed"] for p in valid),
              "pinned_spend_usd": pinned_spend, "routed_spend_usd": routed_spend,
              "spend_difference_usd": routed_spend - pinned_spend}
    changed = sum(1 for r in arm_recs[ROUTED] if any(a["model"] != plan["baseline_model"] for a in r["attempts"]))
    notes = []
    if len(complete) < planned:
        notes.append(f"incomplete: {len(complete)} of {planned} planned pairs finished"
                     + (" (stopped at the spend threshold)" if stopped else ""))
    if len(valid) < len(complete):
        notes.append(f"{len(complete) - len(valid)} pair(s) left out of the comparison for an environment or grader failure")
    if 0 < n < SMALL_SAMPLE_PAIRS:
        notes.append(f"small sample: {n} valid pair(s); differences are not evidence")
    if not n:
        savings = "No valid pairs finished, so there is nothing to compare."
    elif pp != rp:
        savings = (f"Pass rates differ (pinned {pp}/{n}, routed {rp}/{n}), so no savings at the same pass rate is "
                   "claimed.")
    elif plan["no_selection_change"] and changed == 0:
        savings = "No selection change: the router used the baseline model throughout, so there are no savings to claim."
    else:
        d = pinned_spend - routed_spend
        pct = f" ({d / pinned_spend:.0%} of the pinned spend)" if pinned_spend else ""
        savings = (f"Savings at the same pass rate ({pp}/{n} both arms): ${d:.4f}{pct} on {n} pair(s)."
                   if d >= 0 else
                   f"Same pass rate ({pp}/{n} both arms), but the routed arm cost ${-d:.4f} more: no savings.")
    return {"schema": COMPARE_SCHEMA, "plan": plan, "arms": arms, "paired": paired, "pairs": pairs,
            "complete_pairs": len(complete), "planned_pairs": planned, "stopped_at_spend_threshold": stopped,
            "spend_threshold_usd": plan["max_spend_usd"], "recorded_spend_usd": spent["cost_usd"],
            "selection_changed_trials": changed, "savings": savings, "notes": notes,
            "policy_revisions": sorted({r["policy_revision"] for r in arm_recs[ROUTED] if r["policy_revision"]})}


def render_compare_markdown(rep: dict) -> str:
    plan, k = rep["plan"], rep["plan"]["trials"]
    L = [f"# Routing comparison: {plan['baseline_tier']} vs auto ({plan['job_type']})", "",
         f"Pinned: `{plan['baseline_model']}`. Routed: `tier=auto`, policy revision "
         f"{', '.join(rep['policy_revisions']) or 'n/a'}. Effort {plan['effort']}, {k} trial(s) per task and arm, "
         f"{len(plan['eligible'])} task(s). Spend is read from the usage ledger and includes failed attempts and fallbacks.",
         "", f"**{rep['savings']}**", ""]
    L += [f"- {n}" for n in rep["notes"]]
    L += ["", f"| Arm | Trials | Passed | pass@1 | pass@{k} | Spend | Requests (failed) | Fallbacks | Env / grader failures |",
          "|---|---|---|---|---|---|---|---|---|"]
    for a, r in rep["arms"].items():
        p1 = f"{r['pass@1']:.0%}" if r["pass@1"] is not None else "n/a"
        pk = f"{r[f'pass@{k}']:.0%}" if r[f"pass@{k}"] is not None else "n/a"
        L.append(f"| {a} | {r['trials']} | {r['passed']} | {p1} | {pk} | ${r['spend_usd']:.4f} | "
                 f"{r['requests']} ({r['failed_requests']}) | {r['fallbacks']} | "
                 f"{r['environment_failures']} / {r['grader_failures']} |")
    p = rep["paired"]
    if p["pairs"]:
        L += ["", f"Paired ({p['pairs']} valid pairs): pinned passes {p['pinned_pass_rate']:.0%}, routed "
              f"{p['routed_pass_rate']:.0%}; both pass {p['both_pass']}, both fail {p['both_fail']}, only pinned "
              f"{p['only_pinned_passes']}, only routed {p['only_routed_passes']}. Spend on these pairs: pinned "
              f"${p['pinned_spend_usd']:.4f}, routed ${p['routed_spend_usd']:.4f} "
              f"(difference ${p['spend_difference_usd']:+.4f})."]
    L += ["", f"Recorded spend ${rep['recorded_spend_usd']:.4f} against the ${rep['spend_threshold_usd']:.2f} threshold "
          "(admission stops once it is reached; the last request may overrun it)."]
    return "\n".join(L) + "\n"
