#!/usr/bin/env python3
"""Estimate skill tokens with the same character heuristic as the Context card, and price them.

Prints system tokens per call for a few sessions (legacy "full" vs progressive disclosure), the
tokens saved, and what they cost at API list prices for the model (`--model`, default the
orchestrator's): uncached input and cache-read price. Then a per-skill breakdown for a skill with
reference files (`--skill`, default unity-practices): what is always in context (its index line),
what loading it costs, and loading one or two references vs. one big file. Prices are list prices
from the config, not a receipt.

The app calibrates these estimates against real usage. Compare real Opus main-agent calls with:
    SELECT session_id, AVG(cache_read_tokens) AS avg_cache_read, COUNT(*) AS calls
    FROM usage_records
    WHERE role = 'main' AND model = 'claude-opus-5-5'
    GROUP BY session_id;
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from gamedevworkstation.agent.context import est  # noqa: E402
from gamedevworkstation.config import get_config  # noqa: E402
from gamedevworkstation.skills import get_skill, skill_load_text, skills_index, system_skill_segments  # noqa: E402

UNITY_PIPELINE = ["unity-router", "compile-fix-loop", "play-verify", "headless-ops", "scene-prefab-safety",
                  "gdd-to-backlog", "project-memory", "architecture-patterns", "asset-pipeline", "perf-pass",
                  "game-feel-pass", "build-ship", "vcs-hygiene", "unity-mcp-orchestrator", "unity-practices"]
PROGRESSIVE = {"skill_mode": "progressive", "pinned_skills": ["delegation"]}


def scenarios() -> list[tuple[str, dict]]:
    pipeline = ["delegation", *UNITY_PIPELINE]
    return [
        ("delegation only", {"skills": ["delegation"]}),
        ("Unity pipeline (legacy)", {"skills": pipeline}),
        ("Unity pipeline (progressive)", {"skills": pipeline, **PROGRESSIVE, "loaded_skills": UNITY_PIPELINE[-3:]}),
        ("graphify session (legacy)", {"skills": ["delegation", "graphify"]}),
        ("graphify session (progressive)", {"skills": ["delegation", "graphify"], **PROGRESSIVE,
                                            "loaded_skills": ["graphify"]}),
    ]


def system_tokens(settings: dict) -> int:
    return est("\n".join(system_skill_segments(settings)))


def prices(model_id: str) -> tuple[float, float, float]:
    """(input, cache read, output) USD per million tokens for a model in the config."""
    m = get_config().model(model_id)
    return m.input, (m.cache_read if m.cache_read is not None else m.input * 0.1), m.output


def usd(tokens: int, per_million: float) -> str:
    v = tokens * per_million / 1e6
    return f"${v:.4f}" if v < 0.01 else f"${v:.3f}"


def skill_breakdown(name: str) -> list[tuple[str, int]]:
    """(label, tokens) for one skill: index line, load, references, and the one-file alternative."""
    s = get_skill(name)
    if not s:
        return []
    root = Path(s["path"]).parent
    line = next((x for x in skills_index(PROGRESSIVE).splitlines() if x.startswith(f"- {name}:")), "")
    load = est(skill_load_text(name))
    refs = sorted(est(f.read_text(encoding="utf-8")) for f in root.glob("references/*.md"))
    rows = [("always in context (index line, every call)", est(line)), ("load SKILL.md (once, when needed)", load)]
    if refs:
        avg = sum(refs) // len(refs)
        rows += [("load + 1 reference (typical task)", load + avg), ("load + 2 references (max the skill allows)",
                                                                     load + 2 * avg),
                 (f"one big file with all {len(refs)} references", load + sum(refs))]
    templates = sum(est(f.read_text(encoding="utf-8", errors="replace")) for f in root.glob("templates/**/*")
                    if f.is_file() and not any(part.startswith(".") for part in f.relative_to(root).parts))
    if templates:
        rows.append(("templates written by scaffold.py (output not generated)", templates))
    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Skill token and API-price estimates")
    ap.add_argument("--model", default=get_config().orchestrator.get("model", "claude-opus-5-5"))
    ap.add_argument("--skill", default="unity-practices")
    ap.add_argument("--calls", type=int, default=100, help="calls per session for the session totals")
    a = ap.parse_args(argv)
    p_in, p_cache, p_out = prices(a.model)
    print(f"Prices for {a.model}: ${p_in}/M input, ${p_cache}/M cache read, ${p_out}/M output (API list prices)\n")
    print(f"{'session':32} {'tokens/call':>11} {'uncached':>10} {'cached':>10}")
    results = {}
    for label, settings in scenarios():
        t = system_tokens(settings)
        results[label] = t
        print(f"{label:32} {t:>11,} {usd(t, p_in):>10} {usd(t, p_cache):>10}")
    for kind in ("Unity pipeline", "graphify session"):
        saved = results[f"{kind} (legacy)"] - results[f"{kind} (progressive)"]
        print(f"saved, {kind:24} {saved:>11,} tokens/call; over {a.calls} calls {saved * a.calls:,} tokens = "
              f"{usd(saved * a.calls, p_cache)}-{usd(saved * a.calls, p_in)}")
    print("\nskill index (every call of a progressive session):")
    for label, extra in (("in a Unity project", {"unity_project": True}), ("outside a Unity project", {"unity_project": False})):
        t = est(skills_index({**PROGRESSIVE, **extra}))
        print(f"  {label:28} {t:>6,} tokens  {usd(t, p_in)} uncached, {usd(t, p_cache)} cached")
    rows = skill_breakdown(a.skill)
    if rows:
        print(f"\n{a.skill}:")
        for label, t in rows:
            price = usd(t, p_out) + " output" if label.startswith("templates") else usd(t, p_in)
            print(f"  {label:54} {t:>7,} tokens  {price}")


if __name__ == "__main__":
    main()
