"""`unload_skill`: the agent's way to say it is done with a loaded skill (progressive sessions).

Loading is `read_skill(name)` (or invoking the skill); it puts the skill's text in history and on
the session's `loaded_skills` list, which compaction re-adds. Unloading takes the skill off that
list (and off the session's enabled skills), so the next compaction drops its text and it no
longer holds one of the `max_loaded` slots. History is not rewritten before then: editing earlier
messages would invalidate the prompt cache and cost more than the text it removes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI

from ..agent.tools import ToolContext, ToolOutput, obj
from ..skills import pinned_skill_names, skill_load_text

if TYPE_CHECKING:
    from ..app import AppState


def unload(settings: dict, name: str) -> tuple[dict, str]:
    """(settings update, message) for unloading `name`; an empty update when nothing changes."""
    loaded = list(settings.get("loaded_skills", []))
    if name in pinned_skill_names(settings):
        return {}, f"{name} is pinned for this session; the user can unpin it in the session's Skills card."
    if name not in loaded:
        return {}, f"{name} is not loaded. Loaded skills: {', '.join(loaded) or 'none'}."
    from ..agent.context import est

    update = {"loaded_skills": [n for n in loaded if n != name],
              "skills": [n for n in settings.get("skills", []) if n != name]}
    tokens = est(skill_load_text(name))
    return update, (f"Unloaded {name}. Its text (about {tokens:,} tokens) leaves the context at the next "
                    "compaction and is not re-added; read_skill loads it again if it is needed.")


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    @S.tools.add("unload_skill", "Unload a skill you loaded with read_skill once its task is done, so it stops "
                 "taking context and a loaded-skill slot. Pinned skills can't be unloaded.",
                 obj({"name": {"type": "string"}}, ["name"]), read_only=True, main_only=True,
                 when=lambda s: (s or {}).get("settings", {}).get("skill_mode") == "progressive")
    async def unload_skill(ctx: ToolContext, a: dict) -> ToolOutput:
        session = S.store.get(ctx.session_id)
        if not session:
            return ToolOutput("No session.", is_error=True)
        update, message = unload(session["settings"], str(a.get("name", "")).strip())
        if not update:
            return ToolOutput(message, is_error=True)
        updated = S.store.update(ctx.session_id, settings=update)
        if updated:
            ctx.session = updated
        return ToolOutput(message)
