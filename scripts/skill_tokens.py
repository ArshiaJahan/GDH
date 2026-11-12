#!/usr/bin/env python3
"""Estimate skill system tokens with the same character heuristic as the Context card.

Compare real Opus main-agent calls before/after with:
    SELECT session_id, AVG(cache_read_tokens) AS avg_cache_read, COUNT(*) AS calls
    FROM usage_records
    WHERE role = 'main' AND model = 'claude-opus-5-5'
    GROUP BY session_id;
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from gamedevworkstation.agent.context import est
from gamedevworkstation.skills import system_skill_segments

UNITY_PIPELINE = ["unity-router", "compile-fix-loop", "play-verify", "headless-ops", "scene-prefab-safety",
                  "gdd-to-backlog", "project-memory", "architecture-patterns", "asset-pipeline", "perf-pass",
                  "game-feel-pass", "build-ship", "vcs-hygiene", "unity-mcp-orchestrator"]


def scenarios() -> list[tuple[str, dict]]:
    pipeline = ["delegation", *UNITY_PIPELINE]
    return [
        ("delegation only", {"skills": ["delegation"]}),
        ("Unity pipeline (legacy)", {"skills": pipeline}),
        ("Unity pipeline (progressive)", {"skills": pipeline, "skill_mode": "progressive",
                                         "pinned_skills": ["delegation"], "loaded_skills": UNITY_PIPELINE[-3:]}),
        ("graphify session (legacy)", {"skills": ["delegation", "graphify"]}),
    ]


def system_tokens(settings: dict) -> int:
    return est("\n".join(system_skill_segments(settings)))


def main() -> None:
    for label, settings in scenarios():
        print(f"{label:32} {system_tokens(settings):>8,} estimated system tokens (skills)")
    graphify = {"skills": ["delegation", "graphify"], "skill_mode": "progressive",
                "pinned_skills": ["delegation"], "loaded_skills": ["graphify"]}
    print(f"{'graphify session (progressive)':32} {system_tokens(graphify):>8,} estimated system tokens (skills)")


if __name__ == "__main__":
    main()
