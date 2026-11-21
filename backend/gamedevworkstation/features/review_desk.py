"""Agent Review Desk: review an agent's Eval Forge trial like a teammate's PR.

A run directory from `gdw eval run` holds each trial's JSON (grade, blame, cost), its diff and its CLI log. The desk
adds two append-only files next to that evidence:

- reviews.jsonl      a rubric review per trial: verdict, 1-5 scores (correctness, maintainability, test quality),
                     a failure mode from a fixed taxonomy, extra tags and notes. source is "human" or "llm:<model>".
- preferences.jsonl  "A is better than B" between two trials of the same task, with a reason.

`export` writes a labelled dataset (JSONL: human reviews and preference pairs, each with the task prompt and diffs).
An optional LLM pre-review proposes a review through the effort gate; `agreement` measures how often it matches the
human. Nothing here edits a trial: the evidence stays what the run produced.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..agent.tools import wrap_untrusted
from ..core.effort import EffortApprovalRequired, check_effort
from ..core.types import ChatRequest, Message, TextBlock, Usage
from . import review_agreement, review_trajectory

if TYPE_CHECKING:
    from ..app import AppState

REVIEWS = "reviews.jsonl"
PREFERENCES = "preferences.jsonl"
DATASET = "dataset.jsonl"
DEFAULT_ROOT = "evals/runs"

RUBRIC: list[dict] = [
    {"id": "correctness", "label": "Correctness", "question": "Does the change do what the task asks, edge cases included?",
     "anchors": {"1": "Wrong or doesn't run", "3": "Main path works; some requirements or edge cases missed",
                 "5": "Every requirement met, including edge cases"}},
    {"id": "maintainability", "label": "Maintainability",
     "question": "Would you merge this code as it is, from a teammate?",
     "anchors": {"1": "Hard to follow, duplicated or hacky", "3": "Fine, with a few things you'd ask to change",
                 "5": "Clear, minimal and in the codebase's style"}},
    {"id": "test_quality", "label": "Test quality",
     "question": "Do the agent's own tests check the new behaviour (not only that it runs)?",
     "anchors": {"1": "No tests, or tests that can't fail", "3": "Tests cover the main path",
                 "5": "Tests pin the behaviour and its edge cases"}},
]
DIMENSIONS = tuple(r["id"] for r in RUBRIC)

TAXONOMY: list[dict] = [
    {"id": "none", "label": "No failure", "description": "The work is correct."},
    {"id": "missed_requirement", "label": "Missed requirement", "description": "A stated requirement isn't done."},
    {"id": "wrong_behaviour", "label": "Wrong behaviour", "description": "It's done, but it behaves differently than asked."},
    {"id": "incomplete", "label": "Incomplete", "description": "Stopped partway; parts are stubs or missing."},
    {"id": "broke_existing", "label": "Broke existing code", "description": "Something that worked before now fails."},
    {"id": "tests_weakened", "label": "Tests weakened", "description": "Edited, skipped or deleted tests to get green."},
    {"id": "ignored_instructions", "label": "Ignored instructions",
     "description": "Went against an explicit constraint (scope, files, style, no commits)."},
    {"id": "overreach", "label": "Overreach", "description": "Unasked changes, rewrites or over-engineering."},
    {"id": "environment", "label": "Environment", "description": "The machine, network or tooling failed, not the agent."},
    {"id": "grader_overreach", "label": "Grader overreach",
     "description": "The hidden tests check details the task never asked for."},
    {"id": "other", "label": "Other", "description": "Say what in the notes."},
]
TAG_IDS = tuple(t["id"] for t in TAXONOMY)

_KEY = re.compile(r"^[A-Za-z0-9._-]{1,200}/[A-Za-z0-9._-]{1,100}/[0-9]{1,4}$")
_LOCK = threading.Lock()


class ReviewError(ValueError):
    pass


# ------------------------------------------------------------------ inputs


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    verdict: Literal["accept", "reject"]
    scores: dict[str, int]
    failure_mode: str = "none"
    tags: list[str] = Field(default_factory=list, max_length=len(TAG_IDS))
    notes: str = Field(default="", max_length=8000)

    @field_validator("scores")
    @classmethod
    def _scores(cls, v: dict[str, int]) -> dict[str, int]:
        if set(v) != set(DIMENSIONS):
            raise ValueError(f"scores need exactly {', '.join(DIMENSIONS)}")
        if any(not 1 <= s <= 5 for s in v.values()):
            raise ValueError("scores are 1 to 5")
        return {d: v[d] for d in DIMENSIONS}

    @field_validator("failure_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in TAG_IDS:
            raise ValueError(f"unknown failure mode {v!r}")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in TAG_IDS]
        if bad:
            raise ValueError(f"unknown tags: {', '.join(bad)}")
        return list(dict.fromkeys(v))


class PreferenceIn(BaseModel):
    task: str = Field(min_length=1, max_length=200)
    a: str
    b: str
    winner: Literal["a", "b", "tie"]
    reason: str = Field(default="", max_length=4000)
    reviewer: str = Field(min_length=1, max_length=80)


# ------------------------------------------------------------------ run directories


def find_runs(root: Path) -> list[dict]:
    """Run directories under root (any folder holding */*/trial-N.json), newest name first."""
    root = Path(root)
    if not root.is_dir():
        raise ReviewError(f"no such directory: {root}")
    out = []
    for d in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        trials = run_trials(d)
        if not trials:
            continue
        out.append({"dir": str(d), "name": d.name, "trials": len(trials), "passed": sum(t["passed"] for t in trials),
                    "agents": sorted({t["agent"] for t in trials}), "reviews": len(read_jsonl(d / REVIEWS))})
    return out


def run_trials(run_dir: Path) -> list[dict]:
    out = []
    for p in sorted(Path(run_dir).glob("*/*/trial-*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        t.pop("grade", None)
        t["key"] = f"{t['task']}/{t['agent']}/{t['trial']}"
        out.append(t)
    return sorted(out, key=lambda t: (t["task"], t["agent"], t["trial"]))


def trial_files(run_dir: Path, key: str) -> Path:
    """The trial's JSON path; the key is task/agent/n and can't leave the run directory."""
    if not _KEY.match(key or "") or ".." in key.split("/"):
        raise ReviewError(f"bad trial key {key!r} (want task/agent/n)")
    task, agent, n = key.split("/")
    p = Path(run_dir) / task / agent / f"trial-{n}.json"
    if not p.is_file():
        raise ReviewError(f"no trial {key} in {run_dir}")
    return p


def _prompt(run_dir: Path, task: str, p: Path) -> str:
    saved = p.with_suffix(".prompt.md")  # written by gdw eval run from this version on
    if saved.is_file():
        return saved.read_text(encoding="utf-8")
    for suite in (Path(run_dir).parent.parent / "suite", Path(run_dir).parent / "suite"):  # evals/runs/X -> evals/suite
        f = suite / task / "prompt.md"
        if f.is_file():
            return f.read_text(encoding="utf-8")
    return ""


def load_trial(run_dir: Path, key: str) -> dict:
    """Everything a reviewer needs for one trial: the prompt, diff, test results and trajectory."""
    p = trial_files(run_dir, key)
    t = json.loads(p.read_text(encoding="utf-8"))
    grade = t.pop("grade", None) or {"passed": False, "steps": []}
    log = p.with_suffix(".log")
    diff = p.with_suffix(".diff")
    rs = [r for r in read_jsonl(Path(run_dir) / REVIEWS) if r["key"] == key]
    prefs = [x for x in read_jsonl(Path(run_dir) / PREFERENCES) if key in (x["a"], x["b"])]
    return {**t, "key": key, "prompt": _prompt(run_dir, t["task"], p),
            "diff": diff.read_text(encoding="utf-8") if diff.is_file() else "",
            "grade": {"passed": bool(grade.get("passed")),
                      "steps": [{k: s.get(k) for k in ("name", "kind", "passed", "exit", "output")}
                                for s in grade.get("steps", [])]},
            "steps": review_trajectory.steps(log.read_text(encoding="utf-8", errors="replace")) if log.is_file() else [],
            "has_log": log.is_file(), "reviews": rs, "preferences": prefs}


# ------------------------------------------------------------------ the review store


def read_jsonl(path: Path) -> list[dict]:
    if not Path(path).is_file():
        return []
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a torn last line from a crash: skip it, keep the rest
    return out


def _append(path: Path, rec: dict) -> dict:
    with _LOCK, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def add_review(run_dir: Path, key: str, data: ReviewIn | dict, *, source: str = "human") -> dict:
    trial_files(run_dir, key)
    r = data if isinstance(data, ReviewIn) else ReviewIn.model_validate(data)
    return _append(Path(run_dir) / REVIEWS, {"id": "rv_" + secrets.token_hex(6), "key": key, "source": source,
                                             **r.model_dump(), "created_at": time.time()})


def add_preference(run_dir: Path, data: PreferenceIn | dict) -> dict:
    p = data if isinstance(data, PreferenceIn) else PreferenceIn.model_validate(data)
    if p.a == p.b:
        raise ReviewError("a preference compares two different trials")
    for k in (p.a, p.b):
        trial_files(run_dir, k)
        if k.split("/")[0] != p.task:
            raise ReviewError(f"{k} isn't a trial of {p.task}")
    return _append(Path(run_dir) / PREFERENCES, {"id": "pf_" + secrets.token_hex(6), **p.model_dump(),
                                                 "created_at": time.time()})


def latest(reviews: list[dict], key: str, *, human: bool) -> dict | None:
    rs = [r for r in reviews if r["key"] == key and (r["source"] == "human") == human]
    return max(rs, key=lambda r: r["created_at"]) if rs else None


def run_summary(run_dir: Path) -> dict:
    rs = read_jsonl(Path(run_dir) / REVIEWS)
    trials = []
    for t in run_trials(run_dir):
        trials.append({k: t.get(k) for k in ("key", "task", "agent", "trial", "passed", "blame", "reason", "cost_usd",
                                             "wall_s", "tool_calls")}
                      | {"human": latest(rs, t["key"], human=True), "llm": latest(rs, t["key"], human=False)})
    return {"dir": str(run_dir), "rubric": RUBRIC, "taxonomy": TAXONOMY, "trials": trials}


def agreement(run_dir: Path) -> dict:
    pairs = review_agreement.pair_up(read_jsonl(Path(run_dir) / REVIEWS))
    return review_agreement.agreement(pairs) | {"pairs": [{"key": h["key"], "human": h["verdict"], "llm": l["verdict"],
                                                           "source": l["source"]} for h, l in pairs]}


# ------------------------------------------------------------------ the dataset


def export(run_dirs: list[Path], out: Path) -> dict:
    """Labelled JSONL: one line per human review (latest per trial and reviewer) and per preference pair. Each carries
    the task prompt, the diff(s) and the test outcome, so a line stands on its own. LLM reviews aren't labels."""
    for d in run_dirs:
        if not run_trials(Path(d)):
            raise ReviewError(f"not an Eval Forge run directory: {d}")
    n_rev = n_pref = 0
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for run_dir in run_dirs:
            run_dir = Path(run_dir)
            cache: dict[str, dict] = {}

            def trial(key: str) -> dict:
                if key not in cache:
                    cache[key] = load_trial(run_dir, key)
                return cache[key]

            newest: dict[tuple[str, str], dict] = {}
            for r in read_jsonl(run_dir / REVIEWS):
                if r["source"] == "human":
                    k = (r["key"], r["reviewer"])
                    if k not in newest or r["created_at"] >= newest[k]["created_at"]:
                        newest[k] = r
            for r in sorted(newest.values(), key=lambda r: (r["key"], r["reviewer"])):
                t = trial(r["key"])
                f.write(json.dumps({"type": "review", "run": run_dir.name, "key": r["key"], "task": t["task"],
                                    "agent": t["agent"], "model": t.get("model", ""), "prompt": t["prompt"],
                                    "diff": t["diff"], "tests_passed": t["grade"]["passed"], "blame": t["blame"],
                                    "reviewer": r["reviewer"], "verdict": r["verdict"], "scores": r["scores"],
                                    "failure_mode": r["failure_mode"], "tags": r["tags"], "notes": r["notes"]},
                                   ensure_ascii=False) + "\n")
                n_rev += 1
            for p in read_jsonl(run_dir / PREFERENCES):
                a, b = trial(p["a"]), trial(p["b"])
                rec: dict[str, Any] = {"type": "preference", "run": run_dir.name, "task": p["task"],
                                       "prompt": a["prompt"], "reviewer": p["reviewer"], "reason": p["reason"],
                                       "winner": p["winner"], "a": {"key": p["a"], "diff": a["diff"],
                                                                    "tests_passed": a["grade"]["passed"]},
                                       "b": {"key": p["b"], "diff": b["diff"], "tests_passed": b["grade"]["passed"]}}
                if p["winner"] != "tie":  # the usual chosen/rejected shape for preference training
                    win, lose = (a, b) if p["winner"] == "a" else (b, a)
                    rec |= {"chosen": win["diff"], "rejected": lose["diff"]}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_pref += 1
    tmp.replace(out)
    return {"path": str(out), "reviews": n_rev, "preferences": n_pref}


# ------------------------------------------------------------------ LLM pre-review

PREREVIEW_SYSTEM = (
    "You review a coding agent's work like a teammate's pull request. You get the task, the hidden tests' results, a "
    "summary of the agent's steps and its diff. Score it against the rubric and pick one failure mode from the taxonomy "
    "(\"none\" when the work is correct). Judge the diff itself, not the agent's claims. Reply with one JSON object only: "
    '{"verdict": "accept"|"reject", "scores": {"correctness": 1-5, "maintainability": 1-5, "test_quality": 1-5}, '
    '"failure_mode": "<taxonomy id>", "tags": ["<taxonomy id>", ...], "notes": "<two or three sentences>"}.')

PreReview = Callable[[dict], Awaitable[dict]]


def prereview_body(t: dict) -> str:
    steps = "\n".join(f"{s['i']}. [{s['kind']}{'/' + s['tool'] if s['tool'] else ''}] {s['title']}"
                      + (" (error)" if s["is_error"] else "") for s in t["steps"][:120])
    tests = "\n".join(f"- {s['name']} ({s['kind']}): {'pass' if s['passed'] else 'FAIL'}\n{(s['output'] or '')[-1500:]}"
                      for s in t["grade"]["steps"])
    return (f"Rubric:\n{json.dumps(RUBRIC, indent=1)}\n\nFailure taxonomy:\n{json.dumps(TAXONOMY, indent=1)}\n\n"
            + wrap_untrusted(t["prompt"][:8000], "task prompt") + "\n\nHidden tests: "
            + ("passed" if t["grade"]["passed"] else "failed") + "\n" + wrap_untrusted(tests[-8000:], "test output")
            + "\n\nAgent steps:\n" + wrap_untrusted(steps[-6000:], "agent trajectory")
            + "\n\n" + wrap_untrusted(t["diff"][-40_000:], "agent diff"))


def normalize(reply: Any) -> dict:
    """A model reply as a valid review body: clamp scores, map unknown ids to "other", default to reject."""
    r = reply if isinstance(reply, dict) else {}
    scores = r.get("scores") if isinstance(r.get("scores"), dict) else {}
    out_scores = {}
    for d in DIMENSIONS:
        try:
            out_scores[d] = min(5, max(1, int(round(float(scores.get(d, 1))))))
        except (TypeError, ValueError):
            out_scores[d] = 1
    mode = r.get("failure_mode") if r.get("failure_mode") in TAG_IDS else "other"
    tags = [x for x in (r.get("tags") or []) if x in TAG_IDS] if isinstance(r.get("tags"), list) else []
    return {"verdict": "accept" if r.get("verdict") == "accept" else "reject", "scores": out_scores,
            "failure_mode": mode, "tags": tags, "notes": str(r.get("notes") or "")[:8000]}


def make_prereview(app: "AppState", *, model: str | None = None, effort: str = "low") -> tuple[PreReview, str]:
    """The LLM pre-reviewer (through the effort gate, recorded in usage). Returns (fn, model)."""
    m = model or app.config.resolve("claude.standard")
    run_id = "review-desk-" + secrets.token_hex(4)
    check_effort(effort, None, run_id)

    async def review(t: dict) -> dict:
        check_effort(effort, None, run_id)
        mcfg = app.config.model(m)
        profile = app.config.profiles(mcfg.provider)[0]
        prov = app.providers.for_model(m, profile)
        req = ChatRequest(model=m, messages=[Message(role="user", content=[TextBlock(text=prereview_body(t))])],
                          system=PREREVIEW_SYSTEM, effort=effort, max_tokens=800, show_thinking=False,  # type: ignore[arg-type]
                          metadata={"run_id": run_id, "cache_key": "review_desk"})
        try:
            resp = await prov.complete(req)
        except Exception as e:  # noqa: BLE001
            app.usage.record(provider=mcfg.provider, model=m, usage=Usage(), role="assistant", profile=profile,
                             run_id=run_id, effort=effort, feature="review_desk", ok=False,
                             error_kind="rate_limit" if getattr(e, "rate_limited", False) else "other")
            raise
        app.usage.record(provider=mcfg.provider, model=m, usage=resp.usage, role="assistant", profile=profile,
                         run_id=run_id, effort=effort, feature="review_desk", latency_ms=resp.latency_ms)
        from .pi_contracts import loads_reply

        try:
            reply = loads_reply(resp.message().text())
        except ValueError:
            reply = {"notes": "the model's reply wasn't JSON"}
        return normalize(reply)

    return review, m


async def prereview_trial(app: "AppState", run_dir: Path, key: str, *, model: str | None = None,
                          effort: str = "low") -> dict:
    fn, m = make_prereview(app, model=model, effort=effort)
    body = await fn(load_trial(run_dir, key))
    return add_review(run_dir, key, ReviewIn(reviewer=m, **body), source=f"llm:{m}")


# ------------------------------------------------------------------ REST


class _ReviewPost(ReviewIn):
    dir: str
    key: str


class _PrefPost(PreferenceIn):
    dir: str


class _DirPost(BaseModel):
    dir: str
    key: str = ""


def _run_dir(d: str) -> Path:
    p = Path(d).expanduser()
    if not p.is_dir() or not any(p.glob("*/*/trial-*.json")):
        raise HTTPException(400, f"not an Eval Forge run directory: {d}")
    return p


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    def guard(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except ReviewError as e:
            raise HTTPException(400, str(e)) from None

    @api.get("/review/runs")
    async def runs(root: str = DEFAULT_ROOT) -> dict:
        return {"root": root, "runs": guard(lambda: find_runs(Path(root).expanduser()))}

    @api.get("/review/run")
    async def run(dir: str) -> dict:  # noqa: A002
        return run_summary(_run_dir(dir))

    @api.get("/review/trial")
    async def trial(dir: str, key: str) -> dict:  # noqa: A002
        d = _run_dir(dir)
        return guard(lambda: load_trial(d, key))

    @api.post("/review/reviews")
    async def post_review(body: _ReviewPost) -> dict:
        d = _run_dir(body.dir)
        return guard(lambda: add_review(d, body.key, ReviewIn.model_validate(body.model_dump(exclude={"dir", "key"}))))

    @api.post("/review/preferences")
    async def post_pref(body: _PrefPost) -> dict:
        d = _run_dir(body.dir)
        return guard(lambda: add_preference(d, PreferenceIn.model_validate(body.model_dump(exclude={"dir"}))))

    @api.post("/review/prereview")
    async def post_prereview(body: _DirPost) -> dict:
        d = _run_dir(body.dir)
        try:
            return await prereview_trial(S, d, body.key)
        except ReviewError as e:
            raise HTTPException(400, str(e)) from None
        except EffortApprovalRequired as e:
            raise HTTPException(409, str(e)) from None

    @api.get("/review/agreement")
    async def get_agreement(dir: str) -> dict:  # noqa: A002
        return agreement(_run_dir(dir))

    @api.post("/review/export")
    async def post_export(body: _DirPost) -> dict:
        d = _run_dir(body.dir)
        return guard(lambda: export([d], d / DATASET))


# ------------------------------------------------------------------ CLI: gdw review ...


def cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gdw review", description="Agent Review Desk: label Eval Forge trials.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="write the labelled dataset (JSONL) for one or more runs")
    e.add_argument("runs", nargs="+")
    e.add_argument("--out", default="")
    a = sub.add_parser("agreement", help="how often the LLM pre-review matches the human review")
    a.add_argument("run")
    p = sub.add_parser("prereview", help="have a model propose a review for every trial without one")
    p.add_argument("run")
    p.add_argument("--model", default=None)
    p.add_argument("--effort", default="low")
    p.add_argument("--all", action="store_true", help="also trials that already have an LLM review")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "export":
            dirs = [Path(r) for r in args.runs]
            res = export(dirs, Path(args.out) if args.out else dirs[0] / DATASET)
            print(f"{res['reviews']} reviews and {res['preferences']} preference pairs -> {res['path']}")
        elif args.cmd == "agreement":
            res = agreement(Path(args.run))
            if not res["n"]:
                print("no trial has both a human and an LLM review yet")
                return 1
            print(json.dumps({k: v for k, v in res.items() if k != "pairs"}, indent=1))
        else:
            import asyncio

            from ..app import AppState

            app = AppState()
            run_dir = Path(args.run)
            rs = read_jsonl(run_dir / REVIEWS)
            keys = [t["key"] for t in run_trials(run_dir) if args.all or latest(rs, t["key"], human=False) is None]
            for k in keys:
                r = asyncio.run(prereview_trial(app, run_dir, k, model=args.model, effort=args.effort))
                print(f"{k}: {r['verdict']} {r['failure_mode']} {r['scores']}")
        return 0
    except (ReviewError, OSError, EffortApprovalRequired) as err:
        print(f"gdw review {args.cmd}: {err}", file=sys.stderr)
        return 2
