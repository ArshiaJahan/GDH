"""Feature routes beyond the core API. Each feature module registers itself here."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI

if TYPE_CHECKING:
    from .app import AppState


def register_routes(app: FastAPI, api: APIRouter, S: "AppState") -> None:
    for mod in _feature_modules():
        mod.register(app, api, S)


def _feature_modules() -> list:
    import importlib

    names = [f"gamedevworkstation.features.{n}" for n in (
        "usage_routes", "session_routes", "subagents", "delegation", "terminal", "elevenlabs_feature",
        "items_routes", "changes_routes", "worktrees", "web_tools", "mcp_feature", "skill_editor", "skill_assistant", "tasks_feature", "task_board", "harnesses", "settings_routes", "updates",
        "storage",
        # Hooks & gates, quality ladder, campaigns, fleet: added by later work packages; a module
        # that doesn't exist yet is skipped below.
        "hooks", "ladder", "campaigns", "fleet",
        "unity_tool",  # the agent's `unity` tool and /api/unity (Unity backend: MCP or the Unity CLI)
        # Media files a command announced (TRAILER_OUTPUT: / ARTIFACT: lines) indexed as items.
        "media_out",
    )]
    mods = []
    for n in names:
        try:
            mods.append(importlib.import_module(n))
        except ModuleNotFoundError as e:
            if e.name != n:
                raise
    return mods
