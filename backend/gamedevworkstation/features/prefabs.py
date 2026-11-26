"""Session routes for the Unity Prefabs tab."""
from __future__ import annotations

import asyncio
from collections import Counter, deque
from fnmatch import fnmatchcase
from functools import lru_cache
import json
from pathlib import Path
import time
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import prefab_edit
from .prefab_yaml import Project
from .unity_bridge import is_unity_project

if TYPE_CHECKING:
    from ..app import AppState

PREFIX = "/sessions/{sid}/prefabs"
CATEGORIES = "prefab-categories.json"
NO_PROJECT = "no Unity project in this session's folder"
GroupBy = Literal["category", "folder", "component"]


class Categories(BaseModel):
    categories: dict[str, list[str]]


class Edit(BaseModel):
    path: str
    file_id: str
    key: str
    part: str | None = None
    value: str


class Batch(BaseModel):
    edits: list[Edit] = Field(min_length=1)
    summary: str | None = None


class Move(BaseModel):
    force: bool = False


class Render(BaseModel):
    force: bool = False
    size: int = Field(128, ge=32, le=1024)


def _root(folder: str | None) -> Path | None:
    if not folder:
        return None
    queue = deque([(Path(folder).expanduser().resolve(), 0)])
    while queue:
        path, depth = queue.popleft()
        if is_unity_project(path):
            return path
        if depth < 3:
            try:
                children = sorted(path.iterdir())
            except OSError:
                continue
            queue.extend((child, depth + 1) for child in children
                         if Project.visible_folder(child.name) and not child.is_symlink() and child.is_dir())
    return None


def _categories(root: Path) -> dict[str, list[str]] | None:
    try:
        return json.loads(prefab_edit.metadata_path(root, CATEGORIES).read_text(encoding="utf-8"))["categories"]
    except FileNotFoundError:
        return None


def _matches(path: str, pattern: str) -> bool:
    parts, patterns = path.split("/"), pattern.split("/")

    @lru_cache(maxsize=None)
    def match(i: int, j: int) -> bool:
        if j == len(patterns):
            return i == len(parts)
        if patterns[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatchcase(parts[i], patterns[j]) and match(i + 1, j + 1)

    return match(0, 0)


def _preview(root: Path, guid: str | None) -> Path | None:
    if not guid:
        return None
    try:
        path = prefab_edit.metadata_path(root, "prefab-previews", guid + ".png")
    except HTTPException:
        return None
    return path if path.is_file() else None


def _group(path: str, parent: Path, group_by: GroupBy, components: list[str], categories: dict | None) -> str:
    if group_by == "folder":
        return parent.relative_to("Assets").as_posix()
    if group_by == "component":
        return next((name for name in components if name not in {"Transform", "RectTransform"}), "Uncategorized")
    if categories is None:
        return parent.name
    return next((name for name, patterns in categories.items() if any(_matches(path, p) for p in patterns)),
                "Uncategorized")


def _scan(root: Path | None, group_by: GroupBy) -> dict:
    result = {"root": str(root) if root else None, "scanned_at": time.time(), "group_by": group_by,
              "groups": [], "prefabs": []}
    if not root:
        return {**result, "error": NO_PROJECT}
    project = Project(root)
    categories = _categories(root) if group_by == "category" else None
    edited = prefab_edit.edit_counts(prefab_edit.load_history(root))
    groups = Counter()
    for path, guid in sorted(project.prefabs.items()):
        try:
            components = project.root_components(path)
            variant = project.variant_of(project.read(path))
        except (OSError, UnicodeError):
            components, variant = [], None
        parent = Path(path).parent
        group = _group(path, parent, group_by, components, categories)
        groups[group] += 1
        result["prefabs"].append({
            "path": path, "name": Path(path).stem, "guid": guid,
            "group": group, "folder": parent.as_posix(), "components": components,
            "variant_of": variant, "edited": edited.get(path, 0), "preview": _preview(root, guid) is not None,
        })
    result["groups"] = [{"name": name, "count": count} for name, count in sorted(groups.items())]
    return result


def register(app_: FastAPI, api: APIRouter, S: AppState) -> None:
    # A session is not a write lock. Multiple sessions can point at the same project.
    from threading import Lock

    lock = Lock()

    renders: dict[str, dict] = {}  # project root -> {running, started_at, finished_at, result}

    def session_root(sid: str) -> Path | None:
        session = S.store.get(sid)
        if not session:
            raise HTTPException(404, "Unknown session")
        return _root(session["folder"])

    def need_root(sid: str) -> Path:
        root = session_root(sid)
        if root is None:
            raise HTTPException(404, NO_PROJECT)
        return root

    @api.get(PREFIX)
    def scan(sid: str, group_by: GroupBy = "category") -> dict:
        with lock:
            return _scan(session_root(sid), group_by)

    @api.get(PREFIX + "/categories")
    def get_categories(sid: str) -> dict:
        with lock:
            return {"categories": _categories(need_root(sid)) or {}}

    @api.put(PREFIX + "/categories")
    def categories(sid: str, body: Categories) -> dict:
        with lock:
            root = need_root(sid)
            data = body.model_dump()
            prefab_edit.write_json(prefab_edit.metadata_path(root, CATEGORIES), data)
            return data

    @api.get(PREFIX + "/detail")
    def detail(sid: str, path: str) -> dict:
        with lock:
            root = need_root(sid)
            return prefab_edit.detail(Project(root), path, prefab_edit.load_history(root))

    @api.post(PREFIX + "/edit")
    def edit(sid: str, body: Edit) -> dict:
        with lock:
            project = Project(need_root(sid))
            step, history = prefab_edit.edit_many(project, [body.model_dump()], None)
            return {"ok": True, "step": step, "detail": prefab_edit.detail(project, body.path, history)}

    @api.post(PREFIX + "/edit_many")
    def edit_many(sid: str, body: Batch) -> dict:
        with lock:
            project = Project(need_root(sid))
            step, _ = prefab_edit.edit_many(project, [edit.model_dump() for edit in body.edits], body.summary)
            return {"ok": True, "step": step}

    def move(sid: str, body: Move, *, redo: bool):
        with lock:
            result = prefab_edit.move(Project(need_root(sid)), redo=redo, force=body.force)
            if "conflict" in result:  # same error shape as every other route: {"detail": {"conflict": [...]}}
                raise HTTPException(409, {"conflict": result["conflict"]})
            return result

    @api.post(PREFIX + "/undo")
    def undo(sid: str, body: Move):
        return move(sid, body, redo=False)

    @api.post(PREFIX + "/redo")
    def redo(sid: str, body: Move):
        return move(sid, body, redo=True)

    @api.get(PREFIX + "/history")
    def history(sid: str) -> dict:
        with lock:
            return prefab_edit.public_history(prefab_edit.load_history(need_root(sid)))

    @api.post(PREFIX + "/previews")
    async def render_previews(sid: str, body: Render) -> dict:
        """Render prefab thumbnails with Unity in the background (an approval card asks first); poll /previews/status."""
        from .unity_bridge import get_bridge

        root = need_root(sid)
        session = S.store.get(sid)
        if Path(session["folder"]).expanduser().resolve() != root:
            raise HTTPException(400, f"Rendering previews needs a session opened in the Unity project folder ({root})")
        key = str(root)
        if (job := renders.get(key)) and job["running"]:
            return {k: v for k, v in job.items() if k != "task"}
        job = renders[key] = {"running": True, "started_at": time.time(), "finished_at": None, "result": None}

        async def run() -> None:
            try:
                r = await get_bridge(S).prefab_previews(session, prefab_edit.metadata_path(root, "prefab-previews"),
                                                        size=body.size, force=body.force)
                job["result"] = {"status": r.status, "summary": r.summary, "route": r.mode,
                                 "counts": r.evidence.get("counts") or {}, "actions": r.evidence.get("actions") or [],
                                 "menu": r.evidence.get("menu")}
            except Exception as e:  # noqa: BLE001 - reported to the tab, never raised into the event loop
                job["result"] = {"status": "error", "summary": str(e)[:500], "counts": {}, "actions": []}
            finally:
                job["running"], job["finished_at"] = False, time.time()

        job["task"] = asyncio.create_task(run())
        return {k: v for k, v in job.items() if k != "task"}

    @api.get(PREFIX + "/previews/status")
    def previews_status(sid: str) -> dict:
        job = renders.get(str(need_root(sid)))
        if not job:
            return {"running": False, "result": None}
        # The Unity approval card shows in the Chat tab; the Prefabs tab says so while it waits.
        waiting = job["running"] and any(a.get("kind") == "unity" and (a.get("payload") or {}).get("op") == "previews"
                                         for a in S.approvals.pending(sid))
        return {**{k: v for k, v in job.items() if k != "task"}, "waiting_approval": waiting}

    @api.get(PREFIX + "/preview")
    def preview(sid: str, path: str) -> FileResponse:
        with lock:
            root = need_root(sid)
            project = Project(root)
            prefab_edit.prefab_path(project, path)
            image = _preview(root, project.prefabs[path])
            if not image:
                raise HTTPException(404, "No cached prefab preview")
            return FileResponse(image, media_type="image/png")
