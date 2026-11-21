"""ComfyPlug: the agent's `comfyplug` tool, /api/comfyplug and `gdw comfyplug`.

Images (Qwen Image 2.1), image edits, 3D models (Qwen reference -> TRELLIS.2), sound (Stable Audio 3) and any
other ComfyUI workflow (video included) on the user's own ComfyUI, on this machine or another one
([comfyplug].url). The generation code is the bundled `gamedevworkstation.comfyplug` package.

- ComfyUI is the user's own GPU: no credits and no approval card. Usage is recorded at $0 (feature
  "comfyplug:<action>") so the activity shows in My usage.
- ComfyUI runs one prompt at a time, so jobs here run one at a time too (a lock), each in a worker thread, as a job.
  A cancelled turn stops waiting; the ComfyUI job itself finishes on the server.
- Outputs go to `out` (a path in the session folder) or, without one, to <media>/comfyplug/. Each becomes an item,
  and images come back to the model so it can look at them before using them.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Body, FastAPI, HTTPException

from .. import comfyplug
from ..agent.tools import ToolContext, ToolDenied, ToolOutput
from ..config import media_dir
from ..core.types import ImageBlock, Usage, new_id
from ..comfyplug import client as cp_client
from ..comfyplug.workflow import MEDIA_EXTS

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)

ACTIONS = ("check", "image", "edit", "model", "sound", "workflow")
MODELS = {"image": "qwen-image-2.1", "edit": "qwen-image-2.1-edit", "model": "trellis-2", "sound": "stable-audio-3",
          "workflow": "comfyui-workflow"}
EXT = {"image": ".png", "edit": ".png", "model": ".glb", "sound": ".wav"}
MAX_IMAGES_BACK = 4  # images returned to the model per call
DEFAULTS = {"enabled": True, "url": "", "cli_path": "", "timeout_s": 1800}

TOOL_DESCRIPTION = (
    "ComfyPlug: generate media on the user's own ComfyUI (free, local GPU; one job at a time). Actions: "
    "check (is ComfyUI reachable); image (prompt; aspect '1:1 (Square)' | '9:16 (Portrait Widescreen)' | "
    "'16:9 (Widescreen)' | '21:9 (Ultrawide)'; transparent for an alpha PNG; 20-60 s); edit (image = item id or "
    "path, prompt = the instruction); model (3D GLB, 3-10 min: run ref_only first, look at the reference image, then "
    "rerun with from_image = that image); sound (prompt, seconds; variants N for N takes); workflow (any ComfyUI "
    "workflow JSON, e.g. a video one: workflow = path, slots = {\"<node id>.<input>\": value}, exts to keep). "
    "out = where to write it in the session folder (default: the app's media folder). Every output becomes an item. "
    "No brand, franchise, film or show names in prompts: describe the style. Look at each output before using it.")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "prompt": {"type": "string"},
        "out": {"type": "string", "description": "output path in the session folder (workflow: a folder)"},
        "seed": {"type": "integer"},
        "aspect": {"type": "string"},
        "steps": {"type": "integer"},
        "megapixels": {"type": "number"},
        "transparent": {"type": "boolean"},
        "image": {"type": "string", "description": "edit: the input image, an item id (itm_…) or a path"},
        "width": {"type": "integer"},
        "height": {"type": "integer"},
        "view": {"type": "string", "description": "model: e.g. 'three-quarter front view', 'straight front view'"},
        "faces": {"type": "integer"},
        "texture": {"type": "integer"},
        "ref_only": {"type": "boolean"},
        "from_image": {"type": "string", "description": "model: a reviewed reference image (item id or path)"},
        "image_seed": {"type": "integer"},
        "seconds": {"type": "number"},
        "category": {"type": "string"},
        "trim": {"type": "boolean", "description": "sound: cut silence, fade, normalise (default true)"},
        "sample_rate": {"type": "integer"},
        "variants": {"type": "integer"},
        "workflow": {"type": "string", "description": "workflow: a workflow JSON path, or a bundled template name"},
        "slots": {"type": "object", "description": "workflow: {\"<node id>.<input>\": value}"},
        "exts": {"type": "array", "items": {"type": "string"}, "description": "workflow: output extensions to keep"},
    },
    "required": ["action"],
}


class ComfyPlugError(Exception):
    """A request ComfyPlug can't run (bad arguments, ComfyUI unreachable, a failed job), with a readable message."""


def settings(app: "AppState") -> dict:
    """[comfyplug] merged over the defaults."""
    return {**DEFAULTS, **(getattr(app.config, "comfyplug", None) or {})}


def _int(a: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = a.get(key)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ComfyPlugError(f"{key} must be a whole number from {lo} to {hi}")
    return int(v)


def _num(a: dict, key: str, default: float, lo: float, hi: float) -> float:
    v = a.get(key)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ComfyPlugError(f"{key} must be a number from {lo} to {hi}")
    return float(v)


class ComfyPlugService:
    def __init__(self, app: "AppState"):
        self.app = app
        self.lock = asyncio.Lock()

    # ---------------------------------------------------------------- paths

    def _resolver(self, ctx: ToolContext | None, session: dict | None):
        """write=False/True path resolver: the tool's session roots, or (REST) the session's folder."""
        if ctx is not None:
            return lambda p, write=False: ctx.resolve_path(p, write=write)
        folder = Path(session["folder"]).expanduser().resolve() if session and session.get("folder") else None

        def resolve(p: str, write: bool = False) -> Path:
            raw = Path(p).expanduser()
            if raw.is_absolute():
                full = raw.resolve()
            elif folder is not None:
                full = (folder / raw).resolve()
            else:
                raise ToolDenied("A relative path needs a session with a folder.")
            if folder is not None and full != folder and folder not in full.parents and not raw.is_absolute():
                raise ToolDenied(f"{p} is outside the session folder")
            return full
        return resolve

    def _input(self, ref: str, resolve) -> Path:
        """An item id or a path -> an existing local file."""
        if ref.startswith("itm_"):
            it = self.app.items.get(ref)
            if not it or not it.get("path"):
                raise ComfyPlugError(f"No item {ref} with a file")
            p = Path(it["path"])
        else:
            p = resolve(ref)
        if not p.is_file():
            raise ComfyPlugError(f"{ref}: no such file")
        return p

    def _output(self, a: dict, action: str, resolve) -> Path:
        if a.get("out"):
            p = resolve(str(a["out"]), write=True)
            if action != "workflow" and not p.suffix:
                p = p.with_suffix(EXT[action])
            return p
        d = media_dir() / "comfyplug"
        d.mkdir(parents=True, exist_ok=True)
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{action}-{new_id()[:6]}"
        return d / stamp if action == "workflow" else d / (stamp + EXT[action])

    # -------------------------------------------------------------- running

    def _configure(self) -> dict:
        cfg = settings(self.app)
        cp_client.configure(url=str(cfg.get("url") or "") or None, cli=str(cfg.get("cli_path") or "") or None)
        return cfg

    def status(self) -> dict:
        """Blocking: what `check` reports."""
        cfg = self._configure()
        out: dict[str, Any] = {"enabled": bool(cfg.get("enabled")), "url": cp_client.comfy_url(),
                               "remote": cp_client.is_remote()}
        try:
            stats = cp_client.check_server(timeout=5)
            out["server"] = {"ok": True, "version": (stats.get("system") or {}).get("comfyui_version"),
                             "devices": [d.get("name") for d in stats.get("devices") or [] if isinstance(d, dict)]}
        except comfyplug.ComfyError as e:
            out["server"] = {"ok": False, "error": str(e)}
        for key, find in (("comfy_cli", cp_client.find_comfy), ("ffmpeg", cp_client.find_ffmpeg)):
            try:
                out[key] = find()
            except comfyplug.ComfyError as e:
                out[key] = None
                out[f"{key}_error"] = str(e)
        return out

    def _plan(self, action: str, a: dict, resolve) -> tuple[str, Any]:
        """Check the arguments and resolve the paths (fast, on the event loop); returns (title, blocking call)."""
        prompt = str(a.get("prompt") or "").strip()
        if action in ("image", "edit", "model", "sound") and not prompt:
            raise ComfyPlugError(f"{action} needs a prompt")
        out = self._output(a, action, resolve)
        seed = _int(a, "seed", {"image": 11, "edit": 11}.get(action, 1), 0, 2**53)
        if action == "image":
            kw = dict(seed=seed, aspect=str(a.get("aspect") or "1:1 (Square)"), steps=_int(a, "steps", 25, 1, 100),
                      megapixels=_num(a, "megapixels", 1.0, 0.1, 4.0), transparent=bool(a.get("transparent")))
            return f"Image: {prompt[:48]}", lambda: [comfyplug.generate_image(prompt, str(out), **kw)]
        if action == "edit":
            if not a.get("image"):
                raise ComfyPlugError("edit needs image (an item id or a path)")
            src = self._input(str(a["image"]), resolve)
            w, h = a.get("width"), a.get("height")
            if (w is None) != (h is None):
                raise ComfyPlugError("pass both width and height, or neither")
            kw = dict(seed=seed, steps=_int(a, "steps", 25, 1, 100),
                      width=None if w is None else _int(a, "width", 0, 64, 4096),
                      height=None if h is None else _int(a, "height", 0, 64, 4096))
            return f"Edit: {prompt[:48]}", lambda: [comfyplug.edit_image(str(src), prompt, str(out), **kw)]
        if action == "model":
            if out.suffix.lower() != ".glb":
                raise ComfyPlugError("model out must be a .glb path")
            ref = self._input(str(a["from_image"]), resolve) if a.get("from_image") else None
            kw = dict(seed=seed, view=str(a.get("view") or "three-quarter front view"),
                      ref_only=bool(a.get("ref_only")), from_image=str(ref) if ref else None,
                      image_seed=None if a.get("image_seed") is None else _int(a, "image_seed", 1, 0, 2**53),
                      faces=_int(a, "faces", 12000, 500, 500_000), texture=_int(a, "texture", 1024, 256, 4096))

            def run_model() -> list[str]:
                r = comfyplug.generate_model(prompt, str(out), **kw)
                return [p for p in (r.get("ref") if not ref else None, r.get("glb")) if p]
            return (f"3D reference: {prompt[:40]}" if kw["ref_only"] else f"3D model: {prompt[:44]}"), run_model
        if action == "sound":
            variants = _int(a, "variants", 0, 0, 8)
            kw = dict(seconds=_num(a, "seconds", 2.0, 0.5, 60.0), seed=seed, category=str(a.get("category") or "SFX"),
                      trim=a.get("trim") is not False, sample_rate=_int(a, "sample_rate", 44100, 8000, 96000))
            if variants:
                def run_variants() -> list[str]:
                    outs = comfyplug.generate_variants(prompt, str(out.parent), out.stem, n=variants, **kw)
                    good = [o for o in outs if isinstance(o, str)]
                    bad = [o for o in outs if isinstance(o, tuple)]
                    if not good:
                        raise comfyplug.ComfyError(f"every take failed: {bad[0][1][:300]}")
                    if bad:
                        log.info("comfyplug: %d of %d takes failed", len(bad), variants)
                    return good
                return f"Sound ×{variants}: {prompt[:40]}", run_variants
            return f"Sound: {prompt[:48]}", lambda: [comfyplug.generate_sound(prompt, str(out), **kw)]
        if action == "workflow":
            ref = str(a.get("workflow") or "").strip()
            if not ref:
                raise ComfyPlugError("workflow needs workflow (a workflow JSON path, or a bundled template name)")
            bundled = "/" not in ref and os.sep not in ref and (Path(cp_client.WORKFLOW_DIR) / ref).is_file()
            wf = ref if bundled else str(self._input(ref, resolve))
            slots = a.get("slots") or {}
            if not isinstance(slots, dict) or not all(isinstance(k, str) and "." in k for k in slots):
                raise ComfyPlugError('slots must be an object like {"6.text": "a red fox", "3.seed": 7}')
            exts = a.get("exts") or list(MEDIA_EXTS)
            if not isinstance(exts, list) or not all(isinstance(e, str) and e for e in exts):
                raise ComfyPlugError("exts must be a list of extensions, e.g. [\".mp4\"]")
            timeout = int(settings(self.app).get("timeout_s") or 1800)
            return (f"Workflow: {Path(ref).name}",
                    lambda: comfyplug.run_any(wf, str(out), slots, exts, timeout, prefix=out.name))
        raise ComfyPlugError(f"unknown action {action!r} (use one of {', '.join(ACTIONS)})")

    async def run(self, a: dict, *, session: dict | None, source: str, ctx: ToolContext | None = None) -> dict:
        """Run one action. Returns {"action", "paths", "items", "elapsed_s"} (check: {"action", "status"})."""
        action = str(a.get("action") or "")
        if action not in ACTIONS:
            raise ComfyPlugError(f"action must be one of {', '.join(ACTIONS)}")
        if not settings(self.app).get("enabled"):
            raise ComfyPlugError("ComfyPlug is turned off ([comfyplug] enabled = false in Settings).")
        if action == "check":
            return {"action": "check", "status": await asyncio.to_thread(self.status)}
        sid = session["id"] if session else None
        scope = self.app.usage.capture_scope(sid)
        title, call = self._plan(action, a, self._resolver(ctx, session))
        jid = self.app.jobs.start(sid, "comfyplug", title, meta={"action": action})
        t0 = time.monotonic()
        try:
            async with self.lock:
                self._configure()
                paths = await asyncio.to_thread(call)
        except asyncio.CancelledError:
            self.app.jobs.finish(jid, "cancelled")
            raise
        except (comfyplug.ComfyError, OSError) as e:
            self.app.jobs.log(jid, str(e))
            self.app.jobs.finish(jid, "failed")
            raise ComfyPlugError(str(e)) from e
        elapsed = round(time.monotonic() - t0, 1)
        items = []
        for p in paths:
            iid = self.app.items.add_file(p, source="tool" if source == "agent" else source, session_id=sid,
                                          provider="comfyplug", model=MODELS[action],
                                          message_id=ctx.message_id if ctx else None, title=Path(p).name,
                                          meta={"feature": f"comfyplug:{action}", "prompt": a.get("prompt"),
                                                "seed": a.get("seed"), "elapsed_s": elapsed})
            if iid:
                items.append(iid)
        self.app.usage.record(provider="comfyplug", model=MODELS[action], feature=f"comfyplug:{action}",
                              session_id=sid, role="tool" if source == "agent" else "main", usage=Usage(),
                              latency_ms=int(elapsed * 1000), scope=scope)
        self.app.jobs.finish(jid, "done", outputs=len(paths))
        out = {"action": action, "paths": [str(p) for p in paths], "items": items, "elapsed_s": elapsed}
        self.app.bus.publish("comfyplug.generated", out, sid)
        return out


def _check_text(st: dict) -> str:
    srv = st["server"]
    lines = [f"ComfyUI at {st['url']}: " + (f"ok (version {srv.get('version') or '?'}"
                                            + (f", {', '.join(d for d in srv.get('devices') or [] if d)}" if srv.get("devices") else "")
                                            + ")" if srv["ok"] else f"NOT answering. {srv['error']}"),
             f"comfy-cli: {st.get('comfy_cli') or st.get('comfy_cli_error')}",
             f"ffmpeg (sound only): {st.get('ffmpeg') or st.get('ffmpeg_error')}"]
    if not srv["ok"]:
        lines.append("Ask the user to start ComfyUI (or set [comfyplug].url to the machine that runs it); "
                     "don't try to start, install or update it yourself.")
    return "\n".join(lines)


async def _images_back(paths: list[str]) -> list[ImageBlock]:
    from .ladder import _fit_image

    blocks = []
    for p in paths:
        mime = mimetypes.guess_type(p)[0] or ""
        if not mime.startswith("image/") or len(blocks) >= MAX_IMAGES_BACK:
            continue
        try:
            send, smime, _dims, _note = await asyncio.to_thread(_fit_image, Path(p), mime)
        except Exception:  # noqa: BLE001  (the files are saved; showing them is best effort)
            log.info("comfyplug: couldn't attach %s", p, exc_info=True)
            continue
        if send is not None:
            blocks.append(ImageBlock(media_type=smime, path=str(send), name=Path(p).name))
    return blocks


def install(S: "AppState") -> ComfyPlugService:
    """Register the `comfyplug` tool (idempotent; tests call this on a bare AppState)."""
    svc = S.extensions.get("comfyplug")
    if isinstance(svc, ComfyPlugService):
        return svc
    svc = ComfyPlugService(S)
    S.extensions["comfyplug"] = svc

    @S.tools.add("comfyplug", TOOL_DESCRIPTION, SCHEMA, when=lambda s: bool(settings(S).get("enabled")))
    async def comfyplug_tool(ctx: ToolContext, a: dict) -> ToolOutput:
        try:
            r = await svc.run(a, session=ctx.session, source="agent", ctx=ctx)
        except (ComfyPlugError, ToolDenied) as e:
            return ToolOutput(f"comfyplug {a.get('action')}: {e}", is_error=True)
        if r["action"] == "check":
            return ToolOutput(_check_text(r["status"]), is_error=not r["status"]["server"]["ok"])
        listed = ", ".join(f"{p} (item {i})" for p, i in zip(r["paths"], r["items"])) or ", ".join(r["paths"])
        text = f"comfyplug {r['action']}: {len(r['paths'])} file(s) in {r['elapsed_s']:.0f}s: {listed}"
        if r["action"] == "model" and a.get("ref_only"):
            text += ("\nThis is the 3D reference image only. Look at it; if it is good, rerun model with "
                     "from_image set to it (same out and seed), else change the prompt or image_seed.")
        return ToolOutput(text, items=r["items"], images=await _images_back(r["paths"]))

    return svc


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    svc = install(S)

    @api.get("/comfyplug/status")
    async def status() -> dict:
        return await asyncio.to_thread(svc.status)

    @api.post("/comfyplug/run")
    async def run(body: dict = Body(...)) -> dict:
        sid = body.get("session_id")
        session = S.store.get(sid) if sid else None
        if sid and not session:
            raise HTTPException(404, "Session not found")
        try:
            return await svc.run(body, session=session, source="user")
        except (ComfyPlugError, ToolDenied) as e:
            raise HTTPException(400, str(e)) from e


def cli(argv: list[str]) -> int:
    """`gdw comfyplug <command> ...`: ComfyPlug's own CLI, pointed at [comfyplug].url / cli_path from your settings
    unless COMFY_URL / COMFY_CLI are set."""
    from ..comfyplug.cli import main

    try:
        from ..config import load_config

        cfg = {**DEFAULTS, **(getattr(load_config(), "comfyplug", None) or {})}
        cp_client.configure(url=None if os.environ.get("COMFY_URL") else (cfg.get("url") or None),
                            cli=None if os.environ.get("COMFY_CLI") else (cfg.get("cli_path") or None))
    except Exception:  # noqa: BLE001  (settings are a convenience here; the environment still works)
        log.debug("comfyplug cli: settings not loaded", exc_info=True)
    return main(argv)
