"""HTTP + WebSocket API. Binds to 127.0.0.1; every route except /health and the static
UI needs the session token (Authorization: Bearer <token>, or ?token=<token>)."""
from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
import re
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .app import AppState
from .buildinfo import version_info
from .config import PROVIDERS, data_dir, load_error, media_dir
from .core.media import prepare_image
from .core.types import AudioBlock, FileBlock, ImageBlock, Message, TextBlock, new_id
from .events import REPLAY_MAX
from .skills import get_skill, pinned_skill_names, skill_invocation, skill_load_text, skill_lru

WS_OVERFLOW = 4000  # close code: this client fell too far behind; reconnect with ?since=<last seq>

# /api/file serves these inline as they are; a browser shows them but runs nothing in them.
# Anything else (HTML, SVG, XML/XSL, XHTML, MHTML, unknown types, …) gets `Content-Security-Policy:
# sandbox` (no scripts, opaque origin) so a served file can never act with the app's origin and token.
SAFE_INLINE = re.compile(r"(image/(png|jpeg|gif|webp|avif|bmp|x-icon|vnd\.microsoft\.icon|heic|heif|tiff)"
                         r"|audio/[\w.+-]+|video/[\w.+-]+|application/pdf|text/plain|application/json)")


def file_headers(p: Path) -> dict[str, str]:
    """Response headers for a local file served by /api/file."""
    mime = (mimetypes.guess_type(p.name)[0] or "").lower()
    headers = {"X-Content-Type-Options": "nosniff"}
    if not SAFE_INLINE.fullmatch(mime):
        headers["Content-Security-Policy"] = "sandbox"
    return headers


def servable(S: AppState, path: str, *, session: dict | None = None, strict: bool = True) -> Path:
    """Resolve a file under app data or the allowed session folders/worktrees, else 404."""
    try:
        p = Path(path).resolve(strict=strict)
        sessions = [session] if session is not None else S.store.list(view="all")
        allowed = [data_dir().resolve()]
        for s in sessions:
            if s.get("folder"):
                allowed.append(Path(s["folder"]).expanduser().resolve())
            allowed.append(S.worktrees_root(s["id"]).resolve())
        if not p.is_file() or not any(p.is_relative_to(r) for r in allowed):
            raise HTTPException(404)
        return p
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(404) from None


# The app page in browser mode (`uv run gamedevworkstation`): like the desktop window's CSP for what matters
# against injected Markdown/HTML. No remote images at all (they load only through POST
# /api/remote-image, shown from blob:), media only from here, the backend and ElevenLabs' voice
# previews. Scripts, styles, workers (Monaco) and connections are left as they are.
SPA_CSP = ("img-src 'self' data: blob: http://127.0.0.1:*; "
           "media-src 'self' data: blob: http://127.0.0.1:* https://storage.googleapis.com https://*.elevenlabs.io; "
           "object-src 'none'; base-uri 'self'; frame-ancestors 'none'")


def frontend_dist() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "frontend"
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


class TokenAuth(BaseHTTPMiddleware):
    def __init__(self, app: Any, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and request.method != "OPTIONS":
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip() \
                or request.query_params.get("token", "")
            if not hmac.compare_digest(supplied, self.token):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def attachment_block(a: dict) -> Any:
    path, name = a["path"], a.get("name") or Path(a["path"]).name
    mime = a.get("mime") or mimetypes.guess_type(name)[0] or "application/octet-stream"
    if mime.startswith("image/"):  # send_path: a JPEG copy the model can take (HEIC, huge photos, …)
        return ImageBlock(media_type=a.get("send_mime") or mime, path=a.get("send_path") or path, name=name,
                          item_id=a.get("item_id"))
    if mime.startswith(("audio/", "video/")):
        return AudioBlock(media_type=mime, path=path, name=name, item_id=a.get("item_id"),
                          transcript=a.get("transcript"))
    from .items import extract_text

    return FileBlock(media_type=mime, path=path, name=name, item_id=a.get("item_id"),
                     text=a.get("text") or (extract_text(path, mime) if mime != "application/pdf" else None))


def create_app(token: str, state: AppState | None = None) -> FastAPI:
    app_state = state or AppState()
    import os

    if os.environ.get("GDW_FAKE_PROVIDERS") == "1":  # dev/demo only: no API calls
        from .providers.fake import FakeProvider

        for prov in ("anthropic", "openai"):
            for prof in app_state.config.profiles(prov):
                app_state.providers.override(prov, prof, FakeProvider(prov, delay=0.4))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        app_state.on_startup()
        for hook in list(app_state.extensions.values()):
            start = getattr(hook, "astart", None)
            if start:
                await start()
        yield
        await app_state.shutdown()

    app = FastAPI(title="GameDevWorkstation", lifespan=lifespan)
    app.state.ws = app_state
    app.add_middleware(TokenAuth, token=token)
    # The desktop app loads the UI from tauri://localhost and calls this server on 127.0.0.1.
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(CORSMiddleware, allow_origins=["tauri://localhost", "http://tauri.localhost",
                                                      "http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["Authorization", "Content-Type"], max_age=600)
    api = APIRouter(prefix="/api")
    S = app_state

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "version": __version__}

    # ------------------------------------------------------------------ state

    @api.get("/state")
    async def get_state() -> dict:
        c = S.config
        return {
            "orchestrator": c.orchestrator, "tiers": c.tiers, "tier_models": c.tier_models(), "accounts": c.accounts,
            "models": {k: v.model_dump() for k, v in c.models.items()},
            "delegation": c.delegation, "limits": c.limits, "modes": c.modes, "appearance": c.appearance,
            "elevenlabs": c.elevenlabs, "sessions": c.sessions, "last_seq": S.bus.last_seq(), "paused_all": S.usage.paused_all,
            "features": {k: getattr(v, "available", True) for k, v in S.extensions.items()},
            "data_dir": str(data_dir()),
            "default_skills": S.db.kv_get("skills_global", ["delegation"]),  # what a new session starts with
            "config_error": load_error(),  # config.toml was unreadable and set aside at startup
            "version": version_info(),
            "update": updates.pending_update() if (updates := S.extensions.get("updates")) else None,  # type: ignore[attr-defined]
        }

    # --------------------------------------------------------------- sessions

    @api.get("/sessions")
    async def list_sessions(q: str | None = None, view: str = "active") -> list[dict]:
        """view: active (default; not archived, not in Trash) | archived | trash | all."""
        return S.store.list(q, view)

    from .features import sessions_mgmt

    # Before the /sessions/{sid} routes, so /sessions/search and /sessions/bulk aren't read as ids.
    sessions_mgmt.register(app, api, S)

    def _model_arg(value: Any, current: str | None = None) -> str:
        """A tier key or configured model id from the client → model id; anything else is a 400
        (so `/model sol` can't set the literal "sol"). The session's current model is always accepted."""
        if current is not None and value == current:
            return value
        try:
            return S.config.resolve_known(str(value))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @api.post("/sessions")
    async def create_session(body: dict = Body(default={})) -> dict:
        folder = body.get("folder")
        if folder:
            f = Path(folder).expanduser()
            if not f.is_dir():
                raise HTTPException(400, f"Folder not found: {f}")
            folder = str(f.resolve())
        group_id = sessions_mgmt.valid_group(S, body.get("group_id"))
        s = S.store.create(title=body.get("title") or "New session", folder=folder,
                           model=_model_arg(body["model"]) if body.get("model") else None,
                           effort=body.get("effort"), mode=body.get("mode"))  # skill disclosure: store.create
        if group_id:  # ⌘N in a grouped session: the new one joins that group
            s = S.store.update(s["id"], group_id=group_id) or s
        return s

    @api.get("/sessions/{sid}")
    async def get_session(sid: str) -> dict:
        s = S.store.get(sid)
        if not s:
            raise HTTPException(404)
        return {**s, "running": S.runner.is_running(sid)}

    @api.patch("/sessions/{sid}")
    async def patch_session(sid: str, body: dict = Body(...)) -> dict:
        cur = S.store.get(sid)
        if not cur:
            raise HTTPException(404)
        if "folder" in body and body["folder"]:
            f = Path(body["folder"]).expanduser()
            if not f.is_dir():
                raise HTTPException(400, f"Folder not found: {f}")
            body["folder"] = str(f.resolve())
        if body.get("model"):
            body["model"] = _model_arg(body["model"], cur.get("model"))
        if body.get("harness") == "codex_cli" and not shutil.which("codex"):
            raise HTTPException(400, "Codex CLI isn't installed (npm i -g @openai/codex)")
        if body.get("harness") not in (None, cur["harness"]) and (camp := S.extensions.get("campaigns")) is not None \
                and (c := camp.of_session(cur)) and c["status"] not in ("done", "abandoned"):
            # campaign_* / chain_step_done tools, autopilot and the gates live in the built-in loop
            raise HTTPException(400, f"This session runs {c['title']}, a {c['kind']} that needs the built-in loop.")

        def bad_accounts(acc: Any) -> bool:  # {provider: profile}: the session's key profile per provider
            return acc is not None and (not isinstance(acc, dict) or any(
                p not in PROVIDERS or v not in S.config.profiles(p) for p, v in acc.items()))

        settings = body.get("settings")
        if settings is not None and not isinstance(settings, dict):
            raise HTTPException(400, "settings must be an object")
        if bad_accounts(body.get("accounts")) or bad_accounts((settings or {}).get("accounts")):
            raise HTTPException(400, "Unknown provider or account profile")
        if "account" in body and body["account"] not in S.config.profiles("anthropic"):  # legacy: the Anthropic one
            raise HTTPException(400, "Unknown account profile")
        if "group_id" in body:
            body["group_id"] = sessions_mgmt.valid_group(S, body["group_id"])
        if "sort_order" in body:
            body["sort_order"] = sessions_mgmt.number_arg(body["sort_order"] or 0, "sort_order")
        if body.get("title") and body["title"] != cur["title"]:  # renamed by hand: auto-title leaves it alone
            body["settings"] = {**(body.get("settings") or {}), "title_source": "user"}
        out = S.store.update(sid, **body)
        # Skills ticked in the Connectors card turn on the MCP servers they use, like invoking them.
        new_skills = (settings or {}).get("skills")
        if S.mcp and isinstance(new_skills, list):
            before = set(cur["settings"].get("skills") or [])
            if S.mcp.enable_for_skills(sid, [x for x in new_skills if isinstance(x, str) and x not in before]):
                out = S.store.get(sid)
        return out

    @api.delete("/sessions/{sid}")
    async def delete_session(sid: str, purge: bool = False) -> dict:
        """Move to Trash (restorable), or with ?purge=1 delete for good. Either way the run, its jobs
        and its approval cards are stopped first."""
        if not S.store.get(sid):
            raise HTTPException(404)
        S.store.trash(sid)  # first, so no new message can start a run while we stop this one
        if purge:
            await sessions_mgmt.purge_session(S, sid)  # also removes its subagent worktrees
        else:
            await sessions_mgmt.halt_session(S, sid)
        return {"ok": True, "purged": purge}

    def _msg_out(m: Message) -> dict:
        return {**S.store.message_dict(m), "created_at": m.meta.get("created_at")}

    @api.get("/sessions/{sid}/messages")
    async def get_messages(sid: str) -> list[dict]:
        """Every message, compacted ones included (exports, API clients). The UI pages with /messages/page."""
        return [_msg_out(m) for m in S.store.messages(sid)]

    @api.get("/sessions/{sid}/messages/page")
    async def get_messages_page(sid: str, before: str | None = None, limit: int = Query(150, ge=1, le=1000),
                                compacted: bool = False) -> dict:
        """Newest `limit` messages older than `before`; compacted ones only with compacted=1."""
        if not S.store.get(sid):
            raise HTTPException(404)
        page = S.store.messages_page(sid, before=before, limit=limit, include_compacted=compacted)
        return {**page, "messages": [_msg_out(m) for m in page["messages"]]}

    @api.post("/sessions/{sid}/messages")
    async def send_message(sid: str, body: dict = Body(...)) -> dict:
        s = S.store.get(sid)
        if not s:
            raise HTTPException(404)
        if S.runner.is_running(sid):
            raise HTTPException(409, "Agent is still working; stop it or wait.")
        if s["deleted"]:
            raise HTTPException(409, "This session is in Trash. Restore it first.")
        prov_name = S.config.model(s["model"]).provider
        allowed = S.config.data_policy.get("sensitive_allowed", [])
        for a in body.get("attachments", []):
            it = S.items.get(a["item_id"]) if a.get("item_id") else None
            if it and it["meta"].get("sensitive") and prov_name not in allowed:
                raise HTTPException(403, f"'{it['title']}' is marked sensitive and your data policy doesn't allow "
                                         f"sending it to {prov_name}. Change it in Settings → Data policy.")
        attachments = [dict(a) for a in body.get("attachments", [])]
        for a in attachments:  # images attached from Artifacts etc. weren't prepared at upload
            mime = a.get("mime") or mimetypes.guess_type(a.get("name") or a["path"])[0] or ""
            if mime.startswith("image/") and not a.get("send_path"):
                a["send_path"], a["send_mime"], _note = await asyncio.to_thread(
                    prepare_image, a["path"], mime, media_dir() / "converted")
        text = body.get("text") or ""
        skill = (body.get("skill") or "").strip()
        if skill:
            # Invoking a skill turns it on for the session (follow-up turns keep it) and tells the
            # model, in the message itself, to follow it now.
            if not get_skill(skill):
                raise HTTPException(400, f"Unknown skill: {skill}")
            enabled = s["settings"].get("skills", [])
            if skill not in enabled:
                S.store.update(sid, settings={"skills": [*enabled, skill]})
            if s["settings"].get("skill_mode") == "progressive":
                from .agent.context import skill_load_positions

                if (skill not in pinned_skill_names(s["settings"])
                        and skill not in skill_load_positions(S.runner.model_history(sid))):
                    S.store.add_message(sid, Message(role="user", content=[TextBlock(text=skill_load_text(skill))],
                                                     meta={"skill_load": skill}))
                S.store.update(sid, settings={"loaded_skills": skill_lru(
                    s["settings"], skill, int(S.config.skills.get("max_loaded", 3)))})
            if S.mcp:  # and the MCP servers it uses ([skills.mcp_on_invoke]); they connect before the turn
                S.mcp.enable_for_skills(sid, [skill])
            prefix = skill_invocation(skill)
            if not text.startswith(prefix):
                text = prefix + (f"\n\n{text}" if text.strip() else "")
        parts: list[Any] = []
        if text:
            parts.append(TextBlock(text=text))
        for a in attachments:
            parts.append(attachment_block(a))
        if not parts:
            raise HTTPException(400, "empty message")
        msg = Message(role="user", content=parts, meta={"invoked_skill": skill} if skill else {})
        prov = S.config.model(s["model"]).provider
        for a, b in zip(attachments, parts[len(parts) - len(attachments):]):
            if not b.item_id and a.get("send_path") and a["send_path"] != a["path"]:  # the item is the original
                b.item_id = S.items.add_file(a["path"], source="user", session_id=sid, provider=prov,
                                             model=s["model"], message_id=msg.id, title=b.name)
        S.items.index_message(sid, msg, provider=prov, model=s["model"], source="user")
        S.store.add_message(sid, msg)
        S.store.mark_read(sid, publish=False)  # the user is looking at it
        if s["archived"]:  # talking to an archived session brings it back
            S.store.update(sid, archived=False)
        if s["title"] == "New session" and text:
            S.store.update(sid, title=_title_from(body.get("text") or text), settings={"title_source": "message"})
        S.runner.start(sid)
        return {"id": msg.id}

    @api.post("/sessions/{sid}/stop")
    async def stop_session(sid: str) -> dict:
        return {"stopped": await S.runner.stop(sid, notice=True)}

    @api.post("/sessions/{sid}/clear")
    async def clear_session(sid: str) -> dict:
        S.store.clear(sid)
        return {"ok": True}

    @api.get("/sessions/{sid}/export")
    async def export_session(sid: str) -> Response:
        s = S.store.get(sid)
        if not s:
            raise HTTPException(404)
        lines = [f"# {s['title']}\n"]
        for m in S.store.messages(sid):
            if m.meta.get("tool_results"):
                continue
            body = m.text()
            calls = [f"`{c.name}`" for c in m.tool_calls()]
            if body or calls:
                lines.append(f"## {m.role}\n\n{body}" + (f"\n\n_tools: {', '.join(calls)}_" if calls else ""))
        fname = re.sub(r"[^\w\- ]", "", s["title"])[:60] or "session"
        return PlainTextResponse("\n\n".join(lines), headers={
            "content-disposition": f'attachment; filename="{fname}.md"'})

    # ---------------------------------------------------------------- uploads

    @api.post("/uploads")
    async def upload(file: UploadFile, session_id: str | None = Query(None)) -> dict:
        d = media_dir() / "uploads" / new_id()
        d.mkdir(parents=True)
        name = Path(file.filename or "upload").name
        dest = d / name
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        mime = file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        out = {"path": str(dest), "name": name, "mime": mime, "size": dest.stat().st_size}
        if mime.startswith("image/"):
            # Convert/shrink once now (HEIC, > 5 MB), so no later turn sends something the provider rejects.
            send, send_mime, note = await asyncio.to_thread(prepare_image, dest, mime, d / "send")
            out.update({"send_path": send, "send_mime": send_mime, **({"note": note} if note else {})})
        return out

    @api.get("/file")
    async def get_file(path: str, download: bool = False) -> FileResponse:
        p = servable(S, path, strict=False)
        return FileResponse(p, filename=p.name if download else None, headers=file_headers(p),
                            content_disposition_type="attachment" if download else "inline")

    @api.get("/file/resolve")
    async def resolve_file(path: str) -> dict:
        """For the desktop shell's open_file: which real path to open in its default app (404 if this
        isn't a file /api/file would serve), so the web view can't have arbitrary files opened."""
        return {"path": str(servable(S, path, strict=False))}

    # -------------------------------------------------------------- approvals

    @api.get("/approvals")
    async def list_approvals(session_id: str | None = None) -> list[dict]:
        return S.approvals.pending(session_id)

    @api.post("/approvals/{aid}")
    async def resolve_approval(aid: str, body: dict = Body(...)) -> dict:
        try:
            res = S.approvals.resolve(aid, body["decision"], choice=body.get("choice"), note=body.get("note"))
        except KeyError:
            raise HTTPException(404) from None
        except ValueError as e:  # a choice that isn't one of the card's buttons
            raise HTTPException(400, str(e)) from None
        res.pop("token", None)  # the token goes to the waiting agent, not the browser
        return res

    # ------------------------------------------------------------------- jobs

    @api.get("/jobs")
    async def list_jobs(session_id: str | None = None, limit: int = 50) -> list[dict]:
        return S.jobs.list(session_id, limit)

    @api.post("/jobs/{jid}/cancel")
    async def cancel_job(jid: str) -> dict:
        return {"cancelled": await S.jobs.cancel(jid)}

    @api.get("/limits")
    async def limits_status() -> dict:
        return S.usage.status()

    @api.post("/limits/resume")
    async def resume_limits(body: dict | None = Body(None)) -> dict:
        """Resume anyway: the daily pause, or with session_id that session's pause."""
        if sid := (body or {}).get("session_id"):
            S.usage.resume_session(sid)
        else:
            S.usage.resume_all()
        return {"ok": True, **S.usage.status()}

    # -------------------------------------------------------------- websocket

    @app.websocket("/ws")
    async def ws(websocket: WebSocket, token: str = "", since: int = 0):
        if not hmac.compare_digest(token, app.state.token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        q = S.bus.subscribe()
        try:
            gap = S.bus.replay_gap(since)  # what it missed was pruned
            missed = [] if gap else S.bus.replay(since, limit=REPLAY_MAX + 1)
            if gap or len(missed) > REPLAY_MAX:
                # It reloads its state from the REST API instead.
                await websocket.send_text(json.dumps({"type": "ws.resync", "seq": S.bus.last_seq()}))
            else:
                for ev in missed:
                    await websocket.send_text(json.dumps(ev, default=str))
            await websocket.send_text(json.dumps({"type": "ws.ready", "seq": S.bus.last_seq()}))

            async def reader():
                try:
                    while True:
                        msg = await websocket.receive_text()
                        handler = S.extensions.get("ws_handler")
                        if handler:
                            await handler.handle(json.loads(msg))  # type: ignore[attr-defined]
                finally:
                    q.close()  # the client went away: end the send loop too

            rtask = asyncio.create_task(reader())
            try:
                while (ev := await q.get()) is not None:
                    await websocket.send_text(json.dumps(ev, default=str))
                if q.overflowed:  # fell too far behind: close so the client reconnects with its last seq
                    await websocket.close(code=WS_OVERFLOW, reason="behind; reconnect")
            finally:
                rtask.cancel()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            S.bus.unsubscribe(q)

    app.state.token = token
    app.state.api = api
    from .routes import register_routes

    register_routes(app, api, S)
    app.include_router(api)

    dist = frontend_dist()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path == "api" or path.startswith("api/"):  # unknown API routes are errors, not the app page
            raise HTTPException(404)
        f = (dist / path).resolve()
        if path and f.is_file() and dist.resolve() in f.parents:
            return FileResponse(f)
        if path.startswith("assets/"):  # a chunk from an older build: fail the module load cleanly, not with the app page
            raise HTTPException(404)
        idx = dist / "index.html"
        if idx.exists():
            return FileResponse(idx, headers={"Cache-Control": "no-store", "Content-Security-Policy": SPA_CSP})
        return PlainTextResponse("Frontend not built. Run `make frontend` (or `npm run dev` in frontend/).", 404)

    return app


def _title_from(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return (t[:48] + "…") if len(t) > 48 else t
