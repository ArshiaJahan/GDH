"""The session's Gallery and Prefabs tabs, as agent tools, so the agent sees what the user sees there.

- `gallery`: lists the session's Gallery (generated media, screenshot requests, files in its screenshot and
  imported folders), newest first; `view_image` shows one.
- `prefabs` (Unity projects): list prefabs, read one prefab's values, edit values, and read the edit history.
  Edits go through the same journal as the Prefabs tab (`features/prefab_edit.py`), so the user can undo them
  there; each history step records who made it (`by`: "tab" or "agent"), which tells the agent what the user
  changed by hand. An edit asks for approval like `edit_file` (ctx.approve "edit").
The context pack's Unity section names both tabs and tools (hooks.build_context_pack).
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI, HTTPException

from ..agent.tools import ToolContext, ToolOutput, obj
from . import prefab_edit
from .prefab_yaml import Project
from .prefabs import LOCK, _root, _scan

if TYPE_CHECKING:
    from ..app import AppState

MAX_LIST = 200


def _in_unity(session: dict | None) -> bool:
    return bool(session) and (session.get("settings") or {}).get("unity_project") is not False


def _when(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def list_prefabs(root: Path, group_by: str = "folder", query: str = "", limit: int = 100) -> str:
    scan = _scan(root, group_by)  # type: ignore[arg-type]
    q = query.strip().lower()
    rows = [p for p in scan["prefabs"] if not q or q in p["path"].lower()
            or any(q in c.lower() for c in p["components"])]
    lines = [f"{len(rows)} of {len(scan['prefabs'])} prefabs (grouped by {group_by}):"]
    for p in rows[:limit]:
        extra = [", ".join(c for c in p["components"] if c not in ("Transform", "RectTransform"))[:80]]
        if p["variant_of"]:
            extra.append(f"variant of {p['variant_of'].get('name') or p['variant_of']['guid']}")
        if p["edited"]:
            extra.append(f"{p['edited']} edit(s) in the journal")
        lines.append(f"- [{p['group']}] {p['path']}" + (f" · {' · '.join(x for x in extra if x)}" if any(extra) else ""))
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more (narrow with `query`)")
    return "\n".join(lines)


def describe(detail: dict) -> str:
    out = [f"{detail['path']}" + (f" (variant of {detail['variant_of'].get('path') or detail['variant_of']['guid']})"
                                  if detail.get("variant_of") else "")]
    for o in detail["objects"]:
        out.append(f"object {o['name']} (file_id {o['file_id']})")
        for c in o["components"]:
            src = "built-in" if c["builtin"] else (f"package {c['package']}" if c.get("package") else c.get("script_path") or "")
            out.append(f"  {c['type']} (file_id {c['file_id']}{', ' + src if src else ''}{', disabled' if not c['enabled'] else ''})")
            for f in c["fields"]:
                flags = [f["kind"]]
                if not f["editable"]:
                    flags.append("read-only")
                if f.get("inherited"):
                    flags.append("inherited")
                if f.get("override"):
                    flags.append("override")
                if f.get("edited"):
                    flags.append(f"edited, was {f['edited']['was']}")
                parts = f" parts {','.join(f['parts'])}" if f.get("parts") else ""
                out.append(f"    {f['key']} = {str(f['value'])[:120]} [{'; '.join(flags)}]{parts}")
    return "\n".join(out)


def history_text(history: dict, limit: int = 15) -> str:
    pub = prefab_edit.public_history(history)
    if not pub["steps"]:
        return "No prefab edits yet."
    lines = [f"{len(pub['steps'])} steps, newest first (by tab = the user in the Prefabs tab, by agent = you):"]
    for st in pub["steps"][:limit]:
        lines.append(f"- #{st['id']} {_when(st['at'])} by {st.get('by', 'tab')}{' (undone)' if st['undone'] else ''}: "
                     f"{st['summary']}")
    return "\n".join(lines)


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    @S.tools.add("prefabs", "The Prefabs tab's data for this Unity project, read from the .prefab files by scripts. "
                 "op=list (group_by folder|category|component, query) lists prefabs; op=detail (path) shows one "
                 "prefab's components and values with file_ids; op=history shows recent edits and who made them "
                 "(by=tab means the user changed it by hand); op=edit (edits: [{path, file_id, key, part?, value}], "
                 "summary) writes values into the .prefab files as one step the user can undo in the tab. Prefer "
                 "this to editing prefab YAML with edit_file.",
                 obj({"op": {"type": "string", "enum": ["list", "detail", "history", "edit"]},
                      "group_by": {"type": "string", "enum": ["folder", "category", "component"]},
                      "query": {"type": "string"}, "path": {"type": "string"}, "summary": {"type": "string"},
                      "edits": {"type": "array", "items": obj({
                          "path": {"type": "string"}, "file_id": {"type": "string"}, "key": {"type": "string"},
                          "part": {"type": "string"}, "value": {"type": "string"}},
                          ["path", "file_id", "key", "value"])}}, ["op"]),
                 when=_in_unity)
    async def prefabs_tool(ctx: ToolContext, a: dict) -> ToolOutput:
        session = S.store.get(ctx.session_id) or ctx.session
        root = _root((session or {}).get("folder"))
        if root is None:
            return ToolOutput("No Unity project in this session's folder.", is_error=True)
        op = a.get("op")
        try:
            if op == "list":
                return ToolOutput(await asyncio.to_thread(list_prefabs, root, a.get("group_by") or "folder",
                                                          a.get("query") or ""))
            if op == "history":
                return ToolOutput(history_text(prefab_edit.load_history(root)))
            if op == "detail":
                def read() -> str:
                    with LOCK:
                        return describe(prefab_edit.detail(Project(root), str(a.get("path") or ""),
                                                           prefab_edit.load_history(root)))
                return ToolOutput(await asyncio.to_thread(read))
            if op == "edit":
                edits = [{"path": e["path"], "file_id": str(e["file_id"]), "key": e["key"], "part": e.get("part"),
                          "value": str(e["value"])} for e in (a.get("edits") or [])]
                if not edits:
                    return ToolOutput("op=edit needs `edits`.", is_error=True)
                paths = sorted({e["path"] for e in edits})
                summary = (a.get("summary") or "").strip()[:200] or None
                await ctx.approve("edit", ", ".join(paths)[:300], {
                    "action": "prefab edit", "paths": paths,
                    "edits": [f"{e['path'].rsplit('/', 1)[-1]} {e['key']}{'.' + e['part'] if e['part'] else ''} → {e['value']}"
                              for e in edits[:20]]})

                def write() -> str:
                    with LOCK:
                        step, _ = prefab_edit.edit_many(Project(root), edits, summary, by="agent")
                    return step

                step = await asyncio.to_thread(write)
                for p in paths:
                    S.changes.notify(ctx.session_id, root / p, ctx.provider, ctx.model)
                return ToolOutput(f"Wrote {len(edits)} value(s) in {len(paths)} prefab(s) as step #{step}; the user can "
                                  "undo it in the Prefabs tab. Unity reimports the files when its window gets focus.")
            return ToolOutput("op must be list, detail, history or edit.", is_error=True)
        except HTTPException as e:
            return ToolOutput(f"prefabs {op}: {e.detail}", is_error=True)

    @S.tools.add("gallery", "List this session's Gallery tab, newest first: images, videos and audio the session made, "
                 "Unity screenshot requests (with failures and their reasons), user uploads, and files in the "
                 "Gallery's screenshot and imported folders. Use view_image on a listed path to look at one.",
                 obj({"kinds": {"type": "string", "description": "comma list of image,video,audio"},
                      "limit": {"type": "integer"}}), read_only=True)
    async def gallery_tool(ctx: ToolContext, a: dict) -> ToolOutput:
        from .gallery import list_gallery

        kinds = {k for k in str(a.get("kinds") or "").split(",") if k in ("image", "video", "audio")} or None
        limit = max(1, min(int(a.get("limit") or 30), MAX_LIST))
        entries = await asyncio.to_thread(list_gallery, S, ctx.session_id, limit, kinds)
        if not entries:
            return ToolOutput("The Gallery is empty.")
        lines = [f"{len(entries)} entries, newest first:"]
        for e in entries:
            state = "" if e.get("status") == "done" else f" [{e['status']}{': ' + e['reason'][:160] if e.get('reason') else ''}]"
            lines.append(f"- {_when(e['created_at'])} {e['kind']} from {e.get('source')}: "
                         f"{e.get('path') or e.get('title') or e.get('prompt') or ''}{state}")
        return ToolOutput("\n".join(lines))
