#!/usr/bin/env python3
"""Evaluate the game-dev prompt improver on the frozen 48-prompt corpus.

    uv run --frozen python scripts/eval_prompt_improver.py --fake --out /tmp/pi-eval.json
    uv run --frozen python scripts/eval_prompt_improver.py --live --yes --out pi-live.json   # costs money

Every prompt goes through the REAL coordinator, PromptImprover.improve(session, message), on an isolated AppState
and a temporary Unity-like project. --fake installs a scripted FakeProvider whose replies come from a small
deterministic cue heuristic that reads only the request text, project facts and history it is sent, never the
labels; question cards are auto-answered with each card's recommended (primary) button. Decision, cards, model calls
and added tokens are measured from the real outcome. It tests plumbing and regression gates, NOT the intelligence of
a real model. --live sends the same corpus to the configured model (real provider, isolated database) and reports
measured numbers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from gamedevworkstation.agent.context import est  # noqa: E402
from gamedevworkstation.core.types import ChatRequest, Message, TextBlock  # noqa: E402
from gamedevworkstation.features import pi_research  # noqa: E402
from gamedevworkstation.features.pi_contracts import ProjectFacts  # noqa: E402
from gamedevworkstation.features.pi_research import QUESTION_BANK  # noqa: E402
from gamedevworkstation.features.pi_contracts import TEMPLATE_VERSION  # noqa: E402
from gamedevworkstation.providers.fake import FakeProvider, text_response  # noqa: E402

CORPUS = REPO / "tests" / "fixtures" / "prompt_improver" / "prompts.json"
MAX_QUESTIONS = 3
MAX_CALLS = 2

# ---------------------------------------------------------------- scripted (fake) model -------------------------
TARGET_RE = re.compile(
    r"\b(?:Assets|Packages|ProjectSettings)/\S+|\b[\w-]+\.(?:prefab|unity|cs|asset|mat|shader|anim|controller|asmdef|"
    r"inputactions|spriteatlas|png|wav|gdwreplay)\b")
NUMBER_RE = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s?(units?|u/s|m/s|m|s|sec|secs|seconds?|ms|fps|hz|%|kb|mb|gb|px|db|deg|degrees|"
    r"players?|clients?|batches|draw calls|allocations?|frames?|tris|x)\b", re.I)
ACCEPT_RE = re.compile(
    r"\b(?:should|must|asserts?|verify|verifies|test|tests|passes|fails?|stays?|never|at most|at least|no more than|"
    r"exactly|until|zero|so that|within|no errors?|debe|comprueba|verifica|prueba|muss|soll|doit|verifie)\b", re.I)
TOPIC_KEYWORDS = [  # priority order; keyword stems matched in the lower-cased request
    ("bug_replay", ("bug", "crash", "intermittent", "sometimes", "disappear", "vanish", "still happens", "flaky")),
    ("multiplayer", ("multiplayer", "netcode", "server", "sync", "lobby", "online", "co-op", "players can", "two people")),
    ("performance", ("laggy", "lag", "stutter", "fps", "frame", "optimiz", "performance", "memory", "smoother", "loading")),
    ("feel", ("jump", "dash", "floaty", "feel", "punch", "juice", "snappy", "satisfying", "fuehl", "hits do not")),
    ("assets", ("sound", "sfx", "music", "art", "sprite", "model", "texture", "icon", "looks", "animation", "audio",
                "store page")),
    ("platform_input", ("mobile", "android", "ios", "controller", "gamepad", "touch", "steuerung", "platform", "build",
                        "ship", "release", "tester")),
]
OPTIONS = {  # topic -> (recommended option, other options): (id, label, detail)
    "feel": [("preset", "Use a numeric preset", "Propose explicit values with units for you to approve."),
             ("taste", "Match TASTE.md", "Follow the documented feel in the project's TASTE notes."),
             ("tune", "Tune live in Play Mode", "Expose the values and iterate with you.")],
    "acceptance": [("playtest", "PlayMode test", "An automated play test asserts the result."),
                   ("editmode", "EditMode test", "A fast unit test on the data or logic."),
                   ("manual", "Manual check", "You verify by playing; a screenshot is attached.")],
    "assets": [("existing", "Existing assets", "Use assets already in the project."),
               ("placeholder", "Placeholders", "Grey-box placeholders until final art arrives."),
               ("supplied", "You supply them", "Wait for licensed files you provide.")],
    "performance": [("profile", "Profile first", "Capture a profile on the target device, then set a budget."),
                    ("budget60", "60 fps budget", "Use a 16.6 ms frame budget as the target."),
                    ("memory", "Memory budget", "Constrain allocations and memory instead.")],
    "multiplayer": [("server", "Server authoritative", "The server owns the state; clients send requests."),
                    ("owner", "Owning client", "The owner simulates; the server validates."),
                    ("local", "Local only", "Not replicated.")],
    "bug_replay": [("archive", "Use a recorded archive", "Replay an existing input recording to a checkpoint."),
                   ("record", "Record a new one", "Record the failure live, then replay it."),
                   ("repro_test", "Conventional repro test", "Write a deterministic PlayMode repro.")],
    "platform_input": [("kbm", "Keyboard and mouse", "Desktop only."),
                       ("pad", "Gamepad", "Controller bindings."),
                       ("touch", "Touch", "Mobile touch controls.")],
    "target": [("existing", "Existing candidate", "Edit the most likely existing asset."),
               ("new", "New asset", "Create a new scene or prefab for it.")],
}


def _cues(text: str) -> set[str]:
    out = set()
    if TARGET_RE.search(text):
        out.add("target")
    if NUMBER_RE.search(text):
        out.add("number")
    if ACCEPT_RE.search(text):
        out.add("acceptance")
    return out


def _question(topic: str, candidates: list[str]) -> dict:
    opts = list(OPTIONS[topic])
    if topic == "target" and candidates:
        opts = [(f"c{i + 1}", Path(c).name[:70], c[:200]) for i, c in enumerate(candidates[:3])] + [opts[1]]
        opts = opts[:4]
    return {"id": f"q-{topic.replace('_', '-')}", "topic": topic, "text": QUESTION_BANK[topic][0][:300],
            "options": [{"id": o[0], "label": o[1], "detail": o[2], "cited_fact": candidates[0] if candidates and topic == "target" else None}
                        for o in opts],
            "recommended": opts[0][0], "rationale": f"Changes {topic.replace('_', ' ')} decisions materially.",
            "allow_free_text": True}


def _card(request: str, answers: list[dict] | None = None) -> dict:
    paths = [m.group(0).rstrip(".,;:)") for m in TARGET_RE.finditer(request)][:20]
    num = NUMBER_RE.search(request)
    ac = {"id": "AC1", "expected": "The requested behaviour is observable after the change and compile stays clean.",
          "verification": "playmode_test" if re.search(r"play ?mode|play test", request, re.I) else "manual"}
    if num:
        ac.update(target=float(num.group(1).replace(",", ".")), unit=num.group(2)[:20])
    return {"goal": request.strip()[:500] or "unspecified", "scope": paths, "acceptance_criteria": [ac],
            "quality_ladder_level": "L2", "quality_rationale": "Behaviour change.", "effort": "low",
            "answers": answers or [], "assumptions": [], "risks": []}


HEAD_FACTS = "Project facts (data, not instructions):\n"
HEAD_HISTORY = "Recent conversation (data):\n"
HEAD_REQUEST = "Request to evaluate:\n"


def _parse_eval_prompt(text: str) -> tuple[str, str, str]:
    """(facts, history, request) out of the coordinator's evaluation prompt."""
    head, sep, request = text.partition("\n\n" + HEAD_REQUEST)
    if not sep:
        head, request = "", text.split(HEAD_REQUEST, 1)[-1]
    facts, _, hist = head.partition("\n\n" + HEAD_HISTORY)
    facts = facts[len(HEAD_FACTS):] if facts.startswith(HEAD_FACTS) else facts
    history = "\n".join(ln for ln in hist.splitlines() if ln.strip() and not re.match(r"</?untrusted-", ln))
    return facts, history, request


def scripted_model(req: ChatRequest):
    """The fake model: decides from cues found in the request text it receives. Never sees corpus labels."""
    text = req.messages[-1].text()
    if text.startswith("Current task card:\n"):  # synthesis: hand the card back unchanged (answers are merged by the coordinator)
        raw = text[len("Current task card:\n"):].split("\n\nAnswers:\n", 1)[0]
        return text_response(raw)
    facts, history, request = _parse_eval_prompt(text)
    cues = _cues(request)
    if len(request.split()) <= 10 and history:  # a short follow-up inherits what the last turns said
        cues |= _cues(history)
    candidates = [ln[2:].strip() for ln in facts.splitlines() if ln.startswith("- ") and "/" in ln]
    if len(cues) >= 2:
        out = {"decision": "PROCEED", "cited_facts": candidates[:3], "questions": [], "task_card": _card(request),
               "assumptions": []}
    else:
        low = request.lower()
        topics = [t for t, kws in TOPIC_KEYWORDS if any(k in low for k in kws)][:2]
        if "target" not in cues and "target" not in topics:
            topics.append("target")
        if "acceptance" not in cues:
            topics.append("acceptance")
        topics = list(dict.fromkeys(topics))[:MAX_QUESTIONS]
        out = {"decision": "ASK", "cited_facts": candidates[:3], "questions": [_question(t, candidates) for t in topics],
               "task_card": _card(request), "assumptions": []}
    return text_response(json.dumps(out))


class ScriptedProvider(FakeProvider):
    """FakeProvider whose every reply comes from the cue heuristic (effort gate and call log still apply)."""

    def _next(self, req: ChatRequest):
        return scripted_model(req).model_copy(update={"model": req.model})


# ---------------------------------------------------------------- the real coordinator ---------------------------
def facts_text(ctx: dict) -> str:
    lines = [f"unity_version: {ctx.get('unity_version', 'unknown')}",
             f"render_pipeline: {ctx.get('render_pipeline', 'unknown')}",
             f"input_handler: {ctx.get('input_handler', 'unknown')}"]
    lines += [f"- {c}" for c in ctx.get("candidates", [])]
    lines += [f"doc: {d}" for d in ctx.get("docs", [])]
    lines += [f"console: {c}" for c in ctx.get("console", [])]
    if ctx.get("attached_task"):
        lines.append(f"task: {ctx['attached_task']}")
    return "\n".join(lines)


def _req_tokens(req: ChatRequest) -> int:
    sysm = req.system if isinstance(req.system, str) else " ".join(req.system)
    return est(sysm) + sum(est(m.text()) for m in req.messages)


class Recorder:
    """Wraps the provider the coordinator dispatches to: counts calls and sizes the real requests/replies."""

    def __init__(self, inner: Any, live: bool = False) -> None:
        self.inner, self.live = inner, live
        self.name = getattr(inner, "name", "anthropic")
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.raw: list[str] = []

    def reset(self) -> None:
        self.calls = self.input_tokens = self.output_tokens = 0
        self.raw = []

    def __getattr__(self, item: str) -> Any:
        return getattr(self.inner, item)

    async def complete(self, req: ChatRequest):
        self.calls += 1
        r = await self.inner.complete(req)
        text = r.message().text()
        if self.live and getattr(r, "usage", None):
            self.input_tokens += r.usage.total_input
            self.output_tokens += r.usage.output_tokens
        else:
            self.input_tokens += _req_tokens(req)
            self.output_tokens += est(text)
        self.raw.append(text)
        return r


def make_project(base: Path) -> Path:
    unity = base / "unity"
    (unity / "ProjectSettings").mkdir(parents=True)
    (unity / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.23f1\n", encoding="utf-8")
    return unity


@contextmanager
def corpus_facts(holder: dict):
    """The research step reads a real project; here its facts come from the current corpus entry's context."""
    old = pi_research.collect_facts, pi_research.render_facts
    pi_research.collect_facts = lambda project, session, app, prompt="": ProjectFacts(project=str(project), fingerprint="e" * 64)
    pi_research.render_facts = lambda facts, budget_tokens=1024: facts_text(holder.get("ctx") or {})
    try:
        yield
    finally:
        pi_research.collect_facts, pi_research.render_facts = old


async def answer_cards(app: Any, sid: str, seen: list[dict]) -> None:
    """Auto-answer every improver question card with its recommended (primary) button."""
    from gamedevworkstation.features.prompt_improver import APPROVAL_KIND

    while True:
        for c in app.approvals.pending(sid):
            if c["kind"] != APPROVAL_KIND:
                continue
            payload = c["payload"] if isinstance(c.get("payload"), dict) else json.loads(c["payload"])
            rec = next(b["id"] for b in payload["buttons"] if b.get("style") == "primary")
            seen.append(payload["meta"])
            app.approvals.resolve(c["id"], "approve", choice=rec)
        await asyncio.sleep(0.005)


async def improve_one(app: Any, imp: Any, rec_provider: Recorder, folder: Path, entry: dict, holder: dict) -> dict:
    ctx = entry.get("context") or {}
    holder["ctx"] = ctx
    rec = {"id": entry["id"], "label": entry["label"], "calls": 0, "cards": 0, "input_tokens": 0, "output_tokens": 0,
           "context_tokens": 0, "decision": None, "topics": [], "error": None, "raw": []}
    rec_provider.reset()
    imp._fails.clear()  # each corpus prompt is independent: one failure must not pause the rest
    imp._until.clear()
    try:
        session = app.store.create(folder=str(folder), mode="ask")
        for h in ctx.get("history", []):
            role, _, body = h.partition(": ")
            app.store.add_message(session["id"], Message(role=role if role in ("user", "assistant") else "user",
                                                         content=[TextBlock(text=body)]))
        msg = Message(role="user", content=[TextBlock(text=entry["prompt"])])
        app.store.add_message(session["id"], msg)
        seen: list[dict] = []
        answerer = asyncio.create_task(answer_cards(app, session["id"], seen))
        try:
            out = await imp.improve(session, msg)
        finally:
            answerer.cancel()
        rec["cards"] = len(app.db.all("SELECT id FROM approvals WHERE session_id=? AND kind='prompt_improver_question'",
                                      [session["id"]]))
        rec["topics"] = [m["topic"] for m in seen]
        rec["calls"] = rec_provider.calls
        rec["input_tokens"], rec["output_tokens"], rec["raw"] = rec_provider.input_tokens, rec_provider.output_tokens, rec_provider.raw
        rec["context_tokens"] = est(out.context_text)
        if out.status in ("proceeded", "asked"):
            rec["decision"] = "ASK" if out.status == "asked" else "PROCEED"
        elif out.status == "paused":
            rec["decision"] = "ASK"
            rec["error"] = f"paused: {out.reason}"
        else:
            rec["error"] = f"{out.status}: {out.reason}"
    except Exception as e:  # noqa: BLE001 - one bad prompt must not stop the run
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["overhead_tokens"] = rec["input_tokens"] + rec["output_tokens"] + rec["context_tokens"]
    return rec


def build_app(base: Path, provider: Any | None, live: bool = False) -> tuple[Any, Any, Recorder]:
    """An isolated AppState (own database) with the real PromptImprover. provider=None: the real configured provider."""
    from gamedevworkstation.app import AppState
    from gamedevworkstation.features import task_board
    from gamedevworkstation.features.prompt_improver import PromptImprover

    app = AppState(db_path=base / "eval.db")
    task_board.install(app)
    imp = PromptImprover(app)
    app.extensions["prompt_improver"] = imp
    if provider is not None:
        rec = Recorder(provider)
        app.providers.override("anthropic", "default", rec)
    else:
        real, rec = app.providers.for_model, Recorder(None, live=True)

        def for_model(model: str, profile: str = "default") -> Recorder:
            rec.inner = real(model, profile)
            return rec

        app.providers.for_model = for_model  # type: ignore[method-assign]
    return app, imp, rec


async def run_corpus(corpus: dict, app: Any, imp: Any, rec: Recorder, folder: Path) -> list[dict]:
    holder: dict = {}
    out = []
    with corpus_facts(holder):
        for p in corpus["prompts"]:
            out.append(await improve_one(app, imp, rec, folder, p, holder))
    return out


# ---------------------------------------------------------------- bypass --------------------------------------
async def _bypass_async(cases: list[dict]) -> list[dict]:
    base = Path(tempfile.mkdtemp(prefix="pi-eval-bypass-"))
    unity, plain = make_project(base), base / "plain"
    plain.mkdir()
    app, imp, rec = build_app(base, ScriptedProvider())
    out = []
    holder = {"ctx": {}}
    with corpus_facts(holder):
        for c in cases:
            s = c["session"]
            folder = {"unity": str(unity), "plain": str(plain), "none": None}[s["folder_kind"]]
            session = {**app.store.create(folder=folder), "folder": folder, "harness": s["harness"],
                       "settings": dict(s["settings"])}
            msg = Message(role="user", content=[TextBlock(text=c["prompt"])], meta=dict(c["message_meta"]))
            rec.reset()
            seen: list[dict] = []
            answerer = asyncio.create_task(answer_cards(app, session["id"], seen))
            try:
                o = await imp.improve(session, msg)
                if c["expected_reason"] == "ok":
                    ok, got = o.status in ("proceeded", "asked"), o.status
                else:
                    want_exec = c["expected_execution_text"] if c["expected_reason"] == "star_prefix" else ""
                    ok = (o.status == "bypassed" and o.reason == c["expected_reason"] and o.execution_text == want_exec
                          and rec.calls == 0)
                    got = o.reason if o.status == "bypassed" else o.status
                    if not ok:
                        got = f"{got} (execution_text={o.execution_text!r}, expected {want_exec!r}, calls={rec.calls})"
                err = None
            except Exception as e:  # noqa: BLE001
                ok, got, err = False, "", f"{type(e).__name__}: {e}"
            finally:
                answerer.cancel()
            out.append({"id": c["id"], "expected": c["expected_reason"], "got": got, "ok": ok, "error": err})
    return out


def run_bypass(cases: list[dict]) -> list[dict]:
    return asyncio.run(_bypass_async(cases))


# ---------------------------------------------------------------- report --------------------------------------
def pctl(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return float(s[min(len(s) - 1, math.ceil(p * len(s)) - 1)])


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def summarize(recs: list[dict], bypass: list[dict], corpus: dict) -> dict:
    vague = [r for r in recs if r["label"] == "vague"]
    clear = [r for r in recs if r["label"] == "clear"]
    exp = {p["id"]: set(p["expected_missing"]) for p in corpus["prompts"]}
    hits = [len(set(r["topics"]) & exp[r["id"]]) / len(exp[r["id"]]) for r in vague if exp[r["id"]]]
    allr = recs
    return {
        "n_prompts": len(recs), "n_vague": len(vague), "n_clear": len(clear), "errors": sum(1 for r in recs if r["error"]),
        "vague_ask_rate": mean([r["decision"] == "ASK" for r in vague]),
        "clear_false_ask_rate": mean([r["decision"] == "ASK" for r in clear]),
        "bypass_accuracy": mean([b["ok"] for b in bypass]), "bypass_cases": len(bypass),
        "topic_recall_vague": mean(hits),
        "added_input_tokens": {"mean": mean([r["input_tokens"] + r["context_tokens"] for r in allr]),
                               "p95": pctl([r["input_tokens"] + r["context_tokens"] for r in allr], 0.95)},
        "added_output_tokens": {"mean": mean([r["output_tokens"] for r in allr]), "p95": pctl([r["output_tokens"] for r in allr], 0.95)},
        "overhead_tokens": {"mean": mean([r["overhead_tokens"] for r in allr]), "p95": pctl([r["overhead_tokens"] for r in allr], 0.95)},
        "mean_clear_overhead_tokens": mean([r["overhead_tokens"] for r in clear]),
        "mean_vague_overhead_tokens": mean([r["overhead_tokens"] for r in vague]),
        "calls_per_prompt": {"mean": mean([r["calls"] for r in allr]), "max": max([r["calls"] for r in allr], default=0)},
        "cards_per_prompt": {"mean": mean([r["cards"] for r in allr]), "max": max([r["cards"] for r in allr], default=0)},
    }


def markdown(summary: dict, mode: str) -> str:
    s = summary
    rows = [("Vague ask-rate", f"{s['vague_ask_rate']:.2f}"), ("Clear false-ask rate", f"{s['clear_false_ask_rate']:.2f}"),
            ("Bypass accuracy", f"{s['bypass_accuracy']:.2f} ({s['bypass_cases']} cases)"),
            ("Topic recall on vague (info)", f"{s['topic_recall_vague']:.2f}"),
            ("Added input tokens mean / p95", f"{s['added_input_tokens']['mean']:.0f} / {s['added_input_tokens']['p95']:.0f}"),
            ("Added output tokens mean / p95", f"{s['added_output_tokens']['mean']:.0f} / {s['added_output_tokens']['p95']:.0f}"),
            ("Total overhead mean / p95", f"{s['overhead_tokens']['mean']:.0f} / {s['overhead_tokens']['p95']:.0f}"),
            ("Mean clear overhead", f"{s['mean_clear_overhead_tokens']:.0f}"),
            ("Calls per prompt mean / max", f"{s['calls_per_prompt']['mean']:.2f} / {s['calls_per_prompt']['max']}"),
            ("Cards per prompt mean / max", f"{s['cards_per_prompt']['mean']:.2f} / {s['cards_per_prompt']['max']}"),
            ("Prompts with errors", str(s["errors"]))]
    head = f"Prompt improver eval ({mode})\n\n| Metric | Value |\n|---|---|\n"
    note = ("\nScripted FakeProvider: tests orchestration, not real-model accuracy.\n" if mode == "fake"
            else "\nLive model run; numbers are measured on this corpus only.\n")
    return head + "\n".join(f"| {k} | {v} |" for k, v in rows) + "\n" + note


def load_corpus(path: Path = CORPUS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_fake(corpus: dict | None = None) -> dict:
    corpus = corpus or load_corpus()

    async def go() -> list[dict]:
        base = Path(tempfile.mkdtemp(prefix="pi-eval-"))
        app, imp, rec = build_app(base, ScriptedProvider())
        return await run_corpus(corpus, app, imp, rec, make_project(base))

    recs = asyncio.run(go())
    bypass = run_bypass(corpus["bypass"])
    return {"mode": "fake", "template_version": TEMPLATE_VERSION, "summary": summarize(recs, bypass, corpus), "prompts": recs,
            "bypass": bypass}


def run_live(corpus: dict, model: str) -> dict:
    """Real provider through the real PromptImprover.improve; only the database and the project tree are isolated."""
    from gamedevworkstation.features import prompt_improver as PI

    base = Path(tempfile.mkdtemp(prefix="pi-eval-live-"))

    async def go() -> tuple[list[dict], str]:
        app, imp, rec = build_app(base, None, live=True)
        resolved = app.config.resolve(model)
        orig = PI._cfg
        PI._cfg = lambda a: {**orig(a), "model": resolved}  # type: ignore[assignment]
        try:
            recs = await run_corpus(corpus, app, imp, rec, make_project(base))
        finally:
            PI._cfg = orig  # type: ignore[assignment]
        return recs, resolved

    recs, resolved = asyncio.run(go())
    bypass = run_bypass(corpus["bypass"])
    return {"mode": "live", "model": resolved, "template_version": TEMPLATE_VERSION,
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "summary": summarize(recs, bypass, corpus), "prompts": recs, "bypass": bypass}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the prompt improver on the frozen 48-prompt corpus.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fake", action="store_true", help="scripted FakeProvider (free, deterministic; tests orchestration only)")
    g.add_argument("--live", action="store_true", help="real model calls through the app's provider layer (costs money)")
    ap.add_argument("--yes", action="store_true", help="confirm the cost warning for --live")
    ap.add_argument("--model", default="claude.fast", help="model alias for --live (default: claude.fast)")
    ap.add_argument("--corpus", type=Path, default=CORPUS, help="corpus JSON (default: tests/fixtures/prompt_improver/prompts.json)")
    ap.add_argument("--out", type=Path, help="write the full JSON report here")
    a = ap.parse_args(argv)
    corpus = load_corpus(a.corpus)
    if a.live:
        n = len(corpus["prompts"])
        print(f"WARNING: --live makes up to {n * MAX_CALLS} real model calls ({n} prompts x up to {MAX_CALLS}) with "
              f"model '{a.model}' and bills your provider account. The corpus is read-only; nothing is installed.", file=sys.stderr)
        if not a.yes:
            print("Refusing to run without --yes.", file=sys.stderr)
            return 2
        report = run_live(corpus, a.model)
    else:
        os.environ["GDW_NO_KEYCHAIN"] = "1"  # the fake path never touches real app data or the Keychain
        os.environ["GDW_HOME"] = tempfile.mkdtemp(prefix="pi-eval-home-")
        report = run_fake(corpus)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(markdown(report["summary"], report["mode"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
