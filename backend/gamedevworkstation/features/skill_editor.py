"""API behind the Skills page's SKILL.md editor: a skill's other files (references/, scripts/,
templates/) to view or edit, and "Customize", which copies a built-in skill into the user skills
dir where it takes precedence (the same override `PUT /skills/{name}` uses)."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Body, FastAPI, HTTPException

from ..skills import customize_skill, get_skill, skill_file, skill_files, write_skill_file

if TYPE_CHECKING:
    from ..app import AppState


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    @api.get("/skills/{name}/files")
    async def files(name: str) -> dict:
        s = get_skill(name)
        if not s:
            raise HTTPException(404)
        root = Path(s["path"]).parent
        return {"source": s["source"], "editable": s["source"] == "user",
                "files": [{"path": f, "size": (root / f).stat().st_size} for f in skill_files(name)]}

    @api.get("/skills/{name}/file")
    async def read_file(name: str, path: str) -> dict:
        try:
            return skill_file(name, path)
        except (KeyError, FileNotFoundError) as e:
            raise HTTPException(404, str(e)) from e

    @api.put("/skills/{name}/file")
    async def write_file(name: str, path: str, body: dict = Body(...)) -> dict:
        try:
            return write_skill_file(name, path, str(body.get("content", "")))
        except (KeyError, FileNotFoundError) as e:
            raise HTTPException(404, str(e)) from e
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @api.post("/skills/{name}/customize")
    async def customize(name: str) -> dict:
        try:
            return customize_skill(name)
        except KeyError as e:
            raise HTTPException(404, f"No built-in skill named '{name}'") from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
