"""Item index API for the Artifacts page, the Outputs card and Cmd+K search, plus the
`list_items` / `get_item` / `read_output` agent tools. Agent-written files that look like artifacts or
media are indexed automatically when written."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query

from ..agent.tools import ToolContext, ToolOutput, obj, output_limits, wrap_untrusted
from ..config import data_dir, media_dir
from ..core.types import Message, TextBlock
from ..items import classify

if TYPE_CHECKING:
    from ..app import AppState

INDEXABLE_EXT = {".html", ".htm", ".svg", ".md", ".mmd", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp3",
                 ".wav", ".m4a", ".mp4", ".mov", ".webm", ".csv", ".json", ".xlsx", ".docx", ".pptx"}


def claim_unique(dest: Path) -> tuple[Path, Any]:
    """Create `dest`, or "name (2).ext", "name (3).ext", … if it exists (as Finder names copies),
    and return it opened for writing. Exclusive creation, so a file that appears meanwhile is
    never overwritten."""
    stem, suffix = dest.stem, dest.suffix
    for i in range(1, 10_000):
        cand = dest if i == 1 else dest.with_name(f"{stem} ({i}){suffix}")
        try:
            return cand, cand.open("xb")
        except FileExistsError:
            continue
    raise HTTPException(409, f"Too many copies of {dest.name} in {dest.parent}")


def _filters(tab: str | None, provider: str | None, model: str | None, source: str | None, kind: str | None,
             sessions: str | None, since: float | None, until: float | None) -> dict[str, Any]:
    prov = {"claude": "anthropic", "codex": "openai"}.get(provider or "", provider)
    return {"tab": tab, "provider": prov, "model": model, "source": source, "kind": kind,
            "sessions": [s for s in (sessions or "").split(",") if s] or None, "since": since, "until": until}


def _finished_card(S: "AppState", sub_id: str) -> dict | None:
    """The card of a subagent from an earlier run of the app (saved when it ended), with its session."""
    if not sub_id or "/" in sub_id or "\\" in sub_id or sub_id.startswith("."):
        return None
    f = data_dir() / "subagents" / f"{sub_id}.json"
    if not f.is_file():
        return None
    try:
        card = json.loads(f.read_text())["card"]
    except (ValueError, KeyError):
        return None
    row = S.db.one("SELECT session_id FROM jobs WHERE kind IN ('subagent','codex_cli') "
                   "AND json_extract(meta, '$.subagent')=? ORDER BY rowid DESC LIMIT 1", [sub_id])
    return {**card, "session_id": row["session_id"] if row else None}


def _not_running(card: dict) -> dict:
    """A finished subagent can't read new messages: say so, so the UI can offer the chat or a follow-up."""
    return {"ok": False, "status": "not_running", "subagent": card,
            "message": f"{card.get('name') or 'This subagent'} has finished ({card.get('status')}), "
                       "so it can't read new messages."}


def _untrusted_item(it: dict) -> bool:
    """Items whose title or text came from outside: links (page titles, fetched text) and tool output."""
    meta = it.get("meta")
    return it.get("kind") == "link" or it.get("source") == "tool" or \
        bool(isinstance(meta, dict) and meta.get("untrusted"))


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    items = S.items

    # Index files the agent writes when they're artifacts/media/data (not every source edit).
    orig_notify = S.changes.notify

    def notify(session_id: str, path: Path, provider: str | None = None, model: str | None = None) -> None:
        orig_notify(session_id, path, provider, model)
        if path.is_file() and path.suffix.lower() in INDEXABLE_EXT:
            if not model:  # fall back to the session's model when the writer is unknown
                s = S.store.get(session_id)
                model = s["model"] if s else None
            items.add_file(path, source="agent", session_id=session_id,
                           provider=provider or (S.config.model(model).provider if model else None), model=model)

    S.changes.notify = notify  # type: ignore[method-assign]

    @api.get("/items")
    async def list_items(tab: str | None = None, provider: str | None = None, model: str | None = None,
                         source: str | None = None, kind: str | None = None, sessions: str | None = None,
                         since: float | None = None, until: float | None = None, grouped: bool = True):
        f = _filters(tab, provider, model, source, kind, sessions, since, until)
        return items.grouped(**f) if grouped else items.list(**f)

    @api.get("/items/search")
    async def search(q: str, tab: str | None = None, provider: str | None = None, model: str | None = None,
                     source: str | None = None, kind: str | None = None, sessions: str | None = None,
                     since: float | None = None, until: float | None = None):
        if not q.strip():
            return []
        return items.search(q, **_filters(tab, provider, model, source, kind, sessions, since, until))

    @api.get("/items/counts")
    async def counts(provider: str | None = None, sessions: str | None = None) -> dict:
        f = _filters(None, provider, None, None, None, sessions, None, None)
        out = {}
        for tab in ("artifacts", "media", "files", "links"):
            out[tab] = sum(g["count"] for g in items.grouped(**{**f, "tab": tab}))
        return out

    @api.get("/items/{iid}")
    async def get_item(iid: str) -> dict:
        it = items.get(iid)
        if not it:
            raise HTTPException(404)
        return {**it, "versions": items.versions(iid) if it["kind"] == "artifact" else []}

    @api.patch("/items/{iid}")
    async def patch_item(iid: str, body: dict = Body(...)) -> dict:
        it = items.get(iid)
        if not it:
            raise HTTPException(404)
        meta = {**it["meta"], **{k: v for k, v in body.items() if k in ("sensitive", "favorite")}}
        S.db.update("items", "id", iid, {"meta": json.dumps(meta), **({"title": body["title"]} if body.get("title") else {})})
        return items.get(iid)  # type: ignore[return-value]

    @api.delete("/items/{iid}")
    async def delete_item(iid: str, delete_file: bool = False) -> dict:
        it = items.get(iid)
        if not it:
            raise HTTPException(404)
        items.delete(iid)
        # Only files the app itself stored are removed from disk; the user's folders are left alone.
        if delete_file and it.get("path") and Path(it["path"]).resolve().is_relative_to(media_dir().resolve()):
            Path(it["path"]).unlink(missing_ok=True)
        return {"ok": True}

    @api.post("/items/{iid}/send")
    async def send_to(iid: str, body: dict = Body(...)) -> dict:
        """Attach an item to a session's next message, or hand it to a subagent."""
        it = items.get(iid)
        if not it:
            raise HTTPException(404)
        warn = None
        target = body.get("target", "chat")
        if target == "chat":
            s = S.store.get(body["session_id"])
            if not s:
                raise HTTPException(404)
            m = S.config.model(s["model"])
            mime = it.get("mime") or ""
            name = S.config.label(S.config.resolve(s["model"]))
            if mime.startswith(("audio/", "video/")):
                warn = f"{name} can't hear audio; the agent will be told to transcribe it first."
            elif mime.startswith("image/") and not m.vision:
                warn = f"{name} can't see images."
            return {"attachment": {"path": it["path"], "name": it["filename"] or it["title"], "mime": mime,
                                   "item_id": iid, "text": it.get("extracted_text") if it["kind"] == "link" else None},
                    "warning": warn}
        if target == "subagent":
            sub_id = body.get("subagent_id") or ""
            mgr = S.extensions.get("subagents")
            sub = getattr(mgr, "subs", {}).get(sub_id) if mgr else None
            if not sub:
                card = _finished_card(S, sub_id)
                if not card:
                    raise HTTPException(404, "No such subagent")
                return _not_running(card)
            if sub.status not in ("queued", "running"):
                return _not_running({**sub.card(), "session_id": sub.session_id})
            if sub.tier == "codex.cli":  # `codex exec` takes its brief once; it has no inbox
                return {"ok": False, "status": "no_inbox", "subagent": {**sub.card(), "session_id": sub.session_id},
                        "message": f"{sub.name} is a Codex CLI run, which can't take new messages while it works."}
            if (it.get("mime") or "").startswith(("audio/", "video/")):
                warn = "Subagents can't hear audio; send a transcript instead."
            sub.inbox.append(f"The user shared item {iid} at {it.get('path') or it.get('url')}. Its title:\n"
                             + wrap_untrusted(it["title"] or "", f"item:{iid} title"))
            return {"ok": True, "status": "sent", "warning": warn}
        if target == "followup":
            # Ask the session's main agent to follow up on a finished subagent's work with this item.
            sub_id = body.get("subagent_id") or ""
            mgr = S.extensions.get("subagents")
            sub = getattr(mgr, "subs", {}).get(sub_id) if mgr else None
            card = {**sub.card(), "session_id": sub.session_id} if sub else _finished_card(S, sub_id)
            if not card:
                raise HTTPException(404, "No such subagent")
            sid = card["session_id"]
            s = S.store.get(sid) if sid else None
            if not s:
                raise HTTPException(404, "The subagent's session is gone")
            if s["deleted"]:
                raise HTTPException(409, "This session is in Trash. Restore it first.")
            if S.runner.is_running(sid):
                raise HTTPException(409, "The main agent is still working; stop it or wait.")
            prov = S.config.model(s["model"]).provider
            if it["meta"].get("sensitive") and prov not in S.config.data_policy.get("sensitive_allowed", []):
                raise HTTPException(403, f"'{it['title']}' is marked sensitive and your data policy doesn't allow "
                                         f"sending it to {prov}. Change it in Settings → Data policy.")
            text = (f"Follow up on subagent {card['name']} ({card['id']}, {card['status']}) with item {iid} at "
                    f"{it.get('path') or it.get('url')} (its title: "
                    f"{wrap_untrusted(it['title'] or '', f'item:{iid} title')}). Look at the item (get_item), then ")
            if sub:
                text += ("check that subagent's result (get_subagent_result) and resume it with the item "
                         "(message_subagent) or spawn a follow-up unit.")
            else:  # from an earlier run of the app: only its card survives
                preview = (card.get("result_preview") or "").strip().rstrip(".")
                text += ("spawn a follow-up unit with the item. That subagent ran before the app restarted"
                         + (f"; its result began: {preview}" if preview else "") + ".")
            msg = Message(role="user", content=[TextBlock(text=text)])
            S.store.add_message(sid, msg)
            S.store.mark_read(sid, publish=False)
            if s["archived"]:
                S.store.update(sid, archived=False)
            S.runner.start(sid)
            return {"ok": True, "status": "followup", "session_id": sid, "message_id": msg.id}
        raise HTTPException(400, "target must be chat, subagent or followup")

    @api.post("/items/{iid}/copy-to-downloads")
    async def to_downloads(iid: str) -> dict:
        it = items.get(iid)
        if not it or not it.get("path"):
            raise HTTPException(404)
        src = Path(it["path"])
        if not src.is_file():
            raise HTTPException(404, "The file is gone")
        downloads = Path.home() / "Downloads"
        downloads.mkdir(exist_ok=True)
        with src.open("rb") as fin:
            dest, fout = claim_unique(downloads / src.name)  # never overwrites: "name (2).ext"
            with fout:
                shutil.copyfileobj(fin, fout)
        shutil.copystat(src, dest)
        return {"path": str(dest)}

    # ------------------------------------------------------------------ agent tools

    @S.tools.add("list_items", "List artifacts, media, files and links in this session (or search all sessions). "
                 "Check before launching work that may already be done.",
                 obj({"query": {"type": "string"}, "kind": {"type": "string", "enum": ["artifact", "media", "file", "link"]},
                      "all_sessions": {"type": "boolean"}, "limit": {"type": "integer"}}), read_only=True)
    async def tool_list(ctx: ToolContext, a: dict) -> ToolOutput:
        f: dict[str, Any] = {"kind": a.get("kind")}
        if not a.get("all_sessions"):
            f["session_id"] = ctx.session_id
        lim = min(int(a.get("limit") or 50), 200)
        if a.get("query"):
            rows = [it for g in items.search(a["query"], **f, limit=lim) for it in g["items"]]
        else:
            rows = items.list(**f, limit=lim)
        lines = [f"{r['id']}  {r['kind']}/{r['subtype'] or ''}  {r['title']}  {r.get('path') or r.get('url') or ''}"
                 f"  [{r['provider'] or ''} {r['model'] or ''}]" for r in rows]
        # Titles of links and tool results come from web pages and tools: the listing is outside content.
        return ToolOutput("\n".join(lines) or "No items.",
                          untrusted="list_items" if any(_untrusted_item(r) for r in rows) else None)

    @S.tools.add("get_item", "Get one item's details and its extracted text (PDF text, transcript, page title).",
                 obj({"id": {"type": "string"}, "max_chars": {"type": "integer"}}, ["id"]), read_only=True)
    async def tool_get(ctx: ToolContext, a: dict) -> ToolOutput:
        it = items.get(a["id"])
        if not it:
            return ToolOutput("No such item.", is_error=True)
        if not S.policy.item_allowed(it["id"], ctx.provider):
            return ToolOutput(f"Item {it['id']} is marked sensitive and the data policy doesn't allow sending it "
                              f"to {ctx.provider}.", is_error=True)
        text = (it.get("extracted_text") or "")[: int(a.get("max_chars") or 20000)]
        head = {k: it.get(k) for k in ("id", "kind", "subtype", "title", "path", "url", "mime", "size", "provider",
                                       "model", "source", "session_title", "version")}
        # Extracted text (a fetched page, a PDF, a transcript) and web titles are outside content.
        return ToolOutput(json.dumps(head, default=str) + ("\n\n" + text if text else ""),
                          untrusted=f"item:{it['id']}" if text or _untrusted_item(it) else None)

    @S.tools.add("read_output", "Read part of a tool output that was cut because it was too long (the cut result "
                 "names the item id and the offset to continue from).",
                 obj({"id": {"type": "string"}, "offset": {"type": "integer", "description": "First character, from 0"},
                      "limit": {"type": "integer", "description": "How many characters (default and max: the "
                                                                   "tool output cap, 30,000 unless configured)"}},
                     ["id"]), read_only=True, always=True)
    async def tool_read_output(ctx: ToolContext, a: dict) -> ToolOutput:
        it = items.get(a["id"])
        # Only this session's (or, for the Skills assistant, session-less) saved tool outputs.
        if not it or it.get("subtype") != "tool_output" or it.get("session_id") != ctx.session_id \
                or not it.get("path") or not Path(it["path"]).is_file():
            return ToolOutput("No such saved tool output in this session.", is_error=True)
        if not S.policy.item_allowed(it["id"], ctx.provider):
            return ToolOutput(f"Item {it['id']} is marked sensitive and the data policy doesn't allow sending it "
                              f"to {ctx.provider}.", is_error=True)
        text = Path(it["path"]).read_text(encoding="utf-8", errors="replace")
        cap = output_limits(ctx)[0] - 500  # room for the header and markers, so it isn't cut again
        start = max(int(a.get("offset") or 0), 0)
        end = min(start + min(max(int(a.get("limit") or cap), 1), cap), len(text))
        head = f"[{it['id']}: characters {start:,}–{end:,} of {len(text):,}]"
        tail = f"\n[{len(text) - end:,} more; continue with offset={end}]" if end < len(text) else "\n[end of output]"
        return ToolOutput(f"{head}\n{text[start:end]}{tail}", untrusted=(it.get("meta") or {}).get("untrusted"))
