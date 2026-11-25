"""Requests a user might send, with the skill(s) each should trigger, and a word-overlap ranker.

An offline stand-in for "does the model still pick the right skill from the index": the expected
skill must rank in the top 3 by word overlap with its index line. Used by test_skill_index.py to
check that the short index hints keep the trigger words of the full descriptions.
"""
from __future__ import annotations

import re

CASES: list[tuple[str, set[str]]] = [
    ("the console is red with error CS0246 after I added a package", {"compile-fix-loop"}),
    ("fix compile errors in my scripts", {"compile-fix-loop"}),
    ("the game stutters and the profiler shows GC spikes", {"perf-pass"}),
    ("optimize the draw calls, there are too many batches", {"perf-pass"}),
    ("add screen shake and hit stop, the combat feels flat", {"game-feel-pass"}),
    ("verify the dash feature works in Play Mode against the acceptance criteria", {"play-verify"}),
    ("run the EditMode tests from the command line in batchmode", {"headless-ops"}),
    ("make a release build, bump the version and write the changelog", {"build-ship"}),
    ("set up git LFS and a .gitattributes for this project", {"vcs-hygiene"}),
    ("there is a merge conflict in a prefab file", {"vcs-hygiene", "scene-prefab-safety"}),
    ("I renamed an asset and now the prefab shows Missing (Mono Script)", {"scene-prefab-safety"}),
    ("sprites look blurry after import, fix the pixel art import settings", {"asset-pipeline"}),
    ("set up a sprite atlas and some placeholder art", {"asset-pipeline"}),
    ("set up the save system and scene loading for the game code", {"architecture-patterns"}),
    ("add an object pool for the bullets", {"unity-practices", "architecture-patterns"}),
    ("review this enemy spawner code for best practices and readability", {"unity-practices"}),
    ("move the magic numbers into ScriptableObjects so designers can tune them", {"unity-practices"}),
    ("make a debug scene and cheats for a bug that keeps coming back", {"unity-practices"}),
    ("texture memory is too high, check the texture compression", {"unity-practices", "asset-pipeline"}),
    ("record this run and export a GIF", {"replay"}),
    ("make a Steam trailer for the game", {"trailer-maker"}),
    ("turn the GDD into a backlog with milestones and stories", {"gdd-to-backlog"}),
    ("design the core loop and progression for a roguelike", {"game-designer"}),
    ("PROJECT.md is stale, record this decision and the conventions", {"project-memory"}),
    ("what next? I want to make a game", {"unity-router"}),
    ("the MCP tool call to create a GameObject fails", {"unity-mcp-orchestrator"}),
    ("do a design review of the screenshots against TASTE.md", {"design-critique"}),
    ("that broke, write a postmortem with a prevention rule", {"postmortem"}),
    ("grill me on this plan", {"grilling"}),
    ("how are the files in this codebase related? use the knowledge graph", {"graphify"}),
    ("which subagent tier and effort should I use when I spawn a subagent", {"delegation-tiers"}),
    ("do this at the lowest cost: script it or delegate to a subagent", {"cost-effective-claude-delegation"}),
    ("finish fast with parallel Opus subagents in worktrees and a reviewer", {"high-performance-claude-delegation"}),
    ("inside this campaign, finish the phase with a HANDOFF block", {"campaign"}),
    ("reproduce the inputs deterministically and verify the replay checkpoints", {"replay"}),
    ("smoke test the player build before we ship", {"build-ship"}),
    ("build enemy waves and a health system", {"unity-practices", "architecture-patterns"}),
    ("balance the difficulty and the economy", {"game-designer"}),
]

STOP = {"the", "and", "for", "with", "this", "that", "into", "from", "after", "before", "some", "there", "now", "use",
        "when", "what", "which", "should", "want", "make", "game", "unity", "our", "my", "its", "are", "how", "can",
        "add", "set", "fix", "does", "too", "is", "a", "an", "in", "on", "of", "to", "it", "or", "i", "do", "we"}


def stem(w: str) -> str:
    for suf in ("ings", "ing", "ions", "ion", "ers", "er", "ies", "es", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def words(text: str) -> set[str]:
    return {stem(w) for w in re.findall(r"[a-z0-9][a-z0-9.+-]*[a-z0-9]|[a-z0-9]", text.lower()) if w not in STOP}


def rank(request: str, lines: dict[str, str]) -> list[str]:
    """Skill names by word overlap with `request` (name words count too), best first."""
    q = words(request)
    scored = [(len(q & (words(text) | words(name.replace("-", " ")))), name) for name, text in lines.items()]
    return [n for s, n in sorted(scored, key=lambda x: (-x[0], x[1])) if s > 0]


def hits(lines: dict[str, str], top: int = 3) -> list[tuple[str, set[str], list[str]]]:
    """(request, expected, top-ranked) for every case whose expected skill is not in the top `top`."""
    misses = []
    for request, expected in CASES:
        got = rank(request, lines)[:top]
        if not expected & set(got):
            misses.append((request, expected, got))
    return misses
