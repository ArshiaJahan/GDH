"""The agent's `unity` tool and the /api/unity routes (Unity backend: MCP or the official Unity CLI).

One structured tool instead of raw shell: the route (mcp | cli_live | cli_batch | raw_batch) is
chosen by the Unity backend setting (session → project → [unity].backend, see unity_bridge), and
every op returns {route, status, summary, errors, evidence, artifacts} plus the raw Unity output
wrapped as untrusted. Approvals (unity_bridge.ensure_allowed): status / commands / log never ask;
compile / test pass with the Unity gates' consent or the project's "always allow" and also run in
Plan only mode; everything else asks with a `unity` card and is refused in Plan only mode; eval
always shows its code. Compile and test results become quality-ladder evidence (L1 / L2) with
ts = when the run started, so an edit made during a long compile isn't covered by it.

Routes: GET /api/unity/state, GET /api/unity/info, PUT /api/unity/backend,
POST /api/unity/actions/{install_pipeline|close_editor|open_editor|use_mcp_once|update_cli},
POST /api/unity/jobs/{job_id}/cancel. Events: unity.state (after a backend change, a Unity job
or an action), unity.job (a job starts / ends), unity.action (an action's outcome).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..agent.tools import ToolContext, ToolOutput, obj, wrap_untrusted
from . import unity_cli as uc
from .unity_bridge import BACKENDS, ROUTE_LABELS, BridgeResult, get_bridge, is_unity_project

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

    from ..app import AppState

log = logging.getLogger(__name__)

PRESET = "unity-router"
_BG: set[asyncio.Future] = set()  # fire-and-forget state publishes
OPS = ["status", "compile", "test", "build", "import", "exec", "menu", "eval", "command", "commands", "screenshot",
       "play", "log", "open_editor", "close_editor", "install_pipeline"]

TOOL_DESCRIPTION = (
    "Drive Unity for this project through the harness. The route is chosen by the Unity backend setting: "
    "MCP for Unity, the official Unity CLI against the open Editor (live, needs com.unity.pipeline), or a batch "
    "run when the Editor is closed. Returns a structured result (route, status, summary, evidence) plus the raw "
    "Unity output as data. ops: status (route, Editor, CLI), compile, test (platform editmode|playmode, "
    "filter, category, assemblies), build (profile or target, out, dev), exec (method, args; batch), import "
    "(paths; batch), eval (code: C# run in the live Editor, always shown to the user first), command / commands "
    "(a live Pipeline command by name with params / the list of them), screenshot, play (action start|stop|"
    "status), menu (a menu item path, live), log (the last Unity job's log), open_editor, close_editor, "
    "install_pipeline. Prefer this tool to typing unity/unity.sh commands; when the route is mcp, use the "
    "MCP for Unity tools for scene work.")

SCHEMA = obj({
    "op": {"type": "string", "enum": OPS},
    "platform": {"type": "string", "enum": ["editmode", "playmode"]},
    "filter": {"type": "string"}, "category": {"type": "string"}, "assemblies": {"type": "string"},
    "force": {"type": "boolean", "description": "compile: a clean recompile (batch: needs unity.sh/HarnessCli)"},
    "profile": {"type": "string"}, "target": {"type": "string"}, "out": {"type": "string"},
    "dev": {"type": "boolean"},
    "method": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}},
    "no_quit": {"type": "boolean"},
    "paths": {"type": "array", "items": {"type": "string"}}, "menu": {"type": "string"},
    "code": {"type": "string"}, "name": {"type": "string"}, "params": {"type": "object"},
    "query": {"type": "string"},
    "action": {"type": "string", "enum": ["start", "stop", "status"]},
    "lines": {"type": "integer"},
    "timeout_s": {"type": "integer", "minimum": 10, "maximum": 3600},
    "route": {"type": "string", "enum": ["auto", "live", "batch"],
              "description": "require a live or batch route; only when the user asked"},
}, ["op"])


def gate_consent(app: "AppState", session: dict) -> dict[str, set[str]]:
    """The Unity gates preset's consent for this project (when it's on): what the user already
    allowed the harness to run without asking."""
    try:
        from .hooks import get_engine

        eng = get_engine(app)
        if eng is None:
            return {}
        for src in eng.sources(session):
            if src.kind == "preset" and src.name == PRESET and src.active:
                return src.consent_sets()
    except Exception:  # noqa: BLE001 — no consent is the safe answer
        log.debug("unity: couldn't read gate consent", exc_info=True)
    return {}


def _ladder(app: "AppState") -> Any:
    return app.extensions.get("ladder")


def record_evidence(app: "AppState", session: dict, op: str, r: BridgeResult, *, platform: str = "editmode",
                    category: str | None = None, test_filter: str | None = None,
                    assemblies: str | None = None) -> str | None:
    """L1 (compile) / L2 (tests) evidence for a tool-path result. Only pass / fail results count;
    ts = when the run started."""
    lad = _ladder(app)
    folder = session.get("folder")
    if lad is None or not folder or r.status not in ("pass", "fail"):
        return None
    ev = r.evidence or {}
    route = r.mode or ev.get("route") or ""
    ts = float(ev.get("started_at") or time.time())
    try:
        if op == "compile":
            return lad.record_evidence(folder, "L1", r.status, source=f"unity:compile:{route}", observed="tool",
                                       session_id=session["id"], path=ev.get("log"), ts=ts,
                                       detail={"kind": "compile", "route": route, "compile_errors": r.errors,
                                               "root_causes": ev.get("root_causes"), "summary": r.summary,
                                               "cmd": str(ev.get("cmd") or ev.get("command") or "")[:500]})
        from .ladder import evidence_from_nunit, story_ids_from_tests

        cats = [category] if category else []
        scope = "filtered" if (category or test_filter or assemblies) else "all"
        xml = ev.get("xml")
        if xml and Path(str(xml)).is_file():
            spec = evidence_from_nunit(Path(str(xml)), source=f"unity:test:{route}", observed="tool",
                                       cmd=str(ev.get("cmd") or ev.get("command") or ""), mode=platform,
                                       categories=cats, scope=scope, ts=ts, extra={"route": route})
            if spec:
                spec.pop("note", None)
                return lad.record_evidence(folder, session_id=session["id"], **spec)
        passed = [str(x) for x in ev.get("passed_names") or []]
        failed = [str(x) for x in ev.get("failed_names") or []]
        total = int(ev.get("total") or 0)
        n_failed = int(ev.get("failed") or len(failed) or (r.errors if r.status == "fail" else 0))
        n_passed = int(ev.get("passed") or len(passed))
        if r.status == "pass" and total <= 0:
            return None
        return lad.record_evidence(
            folder, "L2", "pass" if r.status == "pass" and n_failed == 0 and total > 0 else "fail",
            source=f"unity:test:{route}", observed="tool", session_id=session["id"], ts=ts,
            subjects=story_ids_from_tests(passed + failed),
            detail={"kind": "tests", "total": total, "passed_n": n_passed, "failed_n": n_failed, "skipped_n": 0,
                    "passed": passed, "failed": failed, "mode": platform, "categories": cats, "scope": scope,
                    "route": route, "summary": f"{n_passed}/{total} passed, {n_failed} failed"})
    except Exception:  # noqa: BLE001 — evidence is best effort, the result still goes back
        log.warning("unity: couldn't record evidence", exc_info=True)
        return None


def _format(op: str, r: BridgeResult, artifacts: dict | None = None) -> ToolOutput:
    ev = {k: v for k, v in (r.evidence or {}).items() if k not in ("state", "data", "passed_names")}
    head = {"route": r.mode or ev.get("route") or "", "status": r.status, "summary": r.summary, "errors": r.errors,
            "evidence": ev, "artifacts": {k: v for k, v in (artifacts or {}).items() if v}}
    text = f"Unity {op}: {r.status}. {r.summary}\n" + json.dumps(head, default=str, indent=1)[:8000]
    if r.report:
        text += "\n\n" + wrap_untrusted(r.report[:30000], f"unity:{op}")
    return ToolOutput(text, is_error=r.status in ("fail", "error"))


def _state_text(d: dict) -> str:
    lines = [f"Unity backend: {d.get('backend')} (from {d.get('backend_source')})",
             f"Route now: {d.get('route')} ({ROUTE_LABELS.get(d.get('route') or '', '')})",
             f"Routes per op: {json.dumps(d.get('routes') or {})}",
             f"Editor open: {d.get('editor_open')} · MCP connected: {d.get('mcp_connected')}"]
    cli = d.get("cli") or {}
    if cli:
        lines.append(f"Unity CLI: {cli.get('version') or 'not found'} {'' if cli.get('ok') else '(' + str(cli.get('reason')) + ')'}".rstrip())
    if d.get("live"):
        lines.append(f"Live Editor (Pipeline): {d['live'].get('state')} {d['live'].get('reason') or ''}".rstrip())
    if d.get("pipeline_in_manifest"):
        lines.append(f"com.unity.pipeline in manifest: {d['pipeline_in_manifest']}")
    if d.get("reason"):
        lines.append(f"Why unavailable: {d['reason']}")
    if d.get("actions"):
        lines.append("The user can: " + ", ".join(d["actions"]) + " (chip / Quality card).")
    if d.get("busy"):
        lines.append(f"Busy: {d['busy'].get('label')}")
    return "\n".join(lines)


async def publish_state(app: "AppState", session: dict) -> None:
    try:
        d = await get_bridge(app).full_state(session)
        app.bus.publish("unity.state", {**d, "session_id": session["id"]}, session["id"])
    except Exception:  # noqa: BLE001
        log.debug("unity.state publish failed", exc_info=True)


async def run_op(app: "AppState", session: dict, a: dict, cancel: asyncio.Event | None = None) -> ToolOutput:
    """One `unity` tool call (also used by tests without a model)."""
    op = str(a.get("op") or "")
    br = get_bridge(app)
    if not is_unity_project(session.get("folder")):
        return ToolOutput("This session's folder isn't a Unity project (no ProjectSettings/ProjectVersion.txt).",
                          is_error=True)
    root = Path(session["folder"]).expanduser().resolve()
    consent = gate_consent(app, session)
    plat = str(a.get("platform") or "editmode")
    want = a.get("route") or "auto"
    if op == "status":
        return ToolOutput(_state_text(await br.full_state(session)))
    cls = br.op_class("eval" if op == "menu" else op, str(a.get("name") or "") or None)
    if session.get("mode") == "plan" and cls not in ("read", "verify"):
        return ToolOutput(f"Plan only mode: Unity {op} isn't run (only status, compile and tests are). "
                          "Describe it instead.", is_error=True)
    if want != "auto" and op in ("compile", "test", "build", "exec", "eval", "command", "screenshot", "play"):
        st = await br.editor_state(session, "test" if op == "test" else op)
        is_live = st.mode in ("mcp", "cli_live")
        if (want == "live") != is_live:
            return ToolOutput(f"Unity {op}: the {want} route isn't what applies now (route {st.mode}"
                              f"{': ' + st.reason if st.reason else ''}). Open or close the Editor, or drop `route`.",
                              is_error=True)
    r: BridgeResult
    artifacts: dict[str, Any] = {}
    if op == "compile":
        r = await br.compile(session, consent=consent, force=bool(a.get("force")), source="tool", cancel=cancel)
        record_evidence(app, session, "compile", r)
        artifacts["log"] = r.evidence.get("log")
    elif op == "test":
        r = await br.run_tests(session, plat, category=a.get("category"), test_filter=a.get("filter"),
                               assemblies=a.get("assemblies"), consent=consent, source="tool", cancel=cancel)
        record_evidence(app, session, "test", r, platform=plat, category=a.get("category"),
                        test_filter=a.get("filter"), assemblies=a.get("assemblies"))
        artifacts["xml"] = r.evidence.get("xml")
    elif op == "build":
        r = await br.build(session, profile=a.get("profile"), target=a.get("target"), out=a.get("out"),
                           dev=bool(a.get("dev")), consent=consent, cancel=cancel)
        artifacts.update({"build": r.evidence.get("output"), "log": r.evidence.get("log")})
    elif op == "exec":
        r = await br.exec_method(session, str(a.get("method") or ""), list(a.get("args") or []),
                                 no_quit=bool(a.get("no_quit")), consent=consent, cancel=cancel)
    elif op == "import":
        r = await br.import_assets(session, list(a.get("paths") or []), force=bool(a.get("force")), consent=consent,
                                   cancel=cancel)
    elif op == "eval":
        r = await br.eval(session, str(a.get("code") or ""), consent=consent, timeout_s=a.get("timeout_s"))
    elif op == "menu":
        item = str(a.get("menu") or "").strip()
        if not item:
            return ToolOutput("menu needs `menu` (e.g. \"Tools/Rebuild Atlas\")", is_error=True)
        code = f"UnityEditor.EditorApplication.ExecuteMenuItem({json.dumps(item)});"
        r = await br.eval(session, code, consent=consent)
    elif op == "command":
        name = str(a.get("name") or "").strip()
        if not name:
            return ToolOutput("command needs `name` (see op commands)", is_error=True)
        r = await br.editor_command(session, name, dict(a.get("params") or {}), consent=consent,
                                    timeout_s=a.get("timeout_s"), cancel=cancel)
    elif op == "commands":
        r = await br.commands(session, a.get("query"))
    elif op == "screenshot":
        out = root / "Logs" / "harness" / "shots" / f"shot-{time.strftime('%Y%m%d-%H%M%S')}.png"
        if a.get("out"):
            q = Path(str(a["out"])).expanduser()
            out = q if q.is_absolute() else root / q
            if not (out.resolve() == root or root in out.resolve().parents):
                return ToolOutput("screenshot `out` must be inside the project", is_error=True)
        r = await br.screenshot(session, out, consent=consent)
        artifacts["screenshot"] = r.evidence.get("screenshot")
    elif op == "play":
        r = await br.play(session, str(a.get("action") or "start"), consent=consent)
    elif op == "log":
        return _last_log(root, int(a.get("lines") or 200))
    elif op in ("open_editor", "close_editor", "install_pipeline"):
        r = await setup_action(app, session, op)
    else:
        return ToolOutput(f"Unknown op {op!r}. ops: {', '.join(OPS)}", is_error=True)
    if op not in ("commands",):
        t = asyncio.ensure_future(publish_state(app, session))
        _BG.add(t)
        t.add_done_callback(_BG.discard)
    return _format(op, r, artifacts)


def _last_log(root: Path, lines: int) -> ToolOutput:
    d = root / "Logs" / "harness"
    logs = sorted((p for p in d.glob("*.log") if p.is_file()), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
    if not logs:
        return ToolOutput("No Unity job log yet (Logs/harness/ is empty).")
    p = logs[-1]
    try:
        with p.open("rb") as f:
            f.seek(max(0, p.stat().st_size - 400_000))
            text = f.read().decode(errors="replace")
    except OSError as e:
        return ToolOutput(f"Couldn't read {p}: {e}", is_error=True)
    tail = "\n".join(text.splitlines()[-max(10, min(lines, 2000)):])
    return ToolOutput(f"Last Unity log: {p.relative_to(root)}\n\n" + wrap_untrusted(tail, f"unity:log:{p.name}"))


async def setup_action(app: "AppState", session: dict, action: str) -> BridgeResult:
    """install_pipeline | close_editor | open_editor | update_cli: always a card (never automatic)."""
    br = get_bridge(app)
    root = Path(session["folder"]).expanduser().resolve()
    cli_st = await br.cli_status()
    if not (cli_st.info and cli_st.ok):
        return BridgeResult("skipped", f"needs the official Unity CLI: {cli_st.reason}", "unavailable")
    cli = cli_st.info
    cfg = uc.unity_cfg(app)
    if action == "install_pipeline":
        ver = str(cfg.get("pipeline_version") or "1.0.0")
        argv = uc.argv_pipeline_install(cli, root, ver)
        detail = (f"Adds `{uc.PIPELINE_PACKAGE}` {ver} to **Packages/manifest.json** (a tracked file changes; "
                  "packages-lock.json too). Unity loads it the next time its window gets focus.")
        op, label = "install_pipeline", "Unity · install Pipeline package"
    elif action == "close_editor":
        argv = uc.argv_close(cli, root, 30)
        detail = "**Unity exits without saving.** Save your scenes and assets in Unity first."
        op, label = "close_editor", "Unity · close Editor"
    elif action == "open_editor":
        argv = uc.argv_open(cli, root)
        detail = "Opens this project in the Unity Editor (its own version)."
        op, label = "open_editor", "Unity · open Editor"
    elif action == "update_cli":
        argv = uc.argv_self_update(cli)
        detail = "Updates the Unity CLI itself (`unity self-update`)."
        op, label = "self_update", "Unity CLI · self-update"
    else:
        return BridgeResult("error", f"unknown action {action}")
    if why := await br.ensure_allowed(session, op, op, route="cli", argv=argv, detail=detail):
        return BridgeResult("skipped", why, "cli")
    run = await br.runner.run(session, argv, project=root, label=label, timeout_s=300 if op != "self_update" else 900,
                              sweep=False)
    uc.invalidate_live(root)
    if op == "self_update":
        br._cli = None
    ok = run.exit_code == 0
    msg = run.error_message() or ("done" if ok else f"exit {run.exit_code}")
    return BridgeResult("pass" if ok else "fail", f"{label}: {msg}"[:400], "cli",
                        report=run.stderr_tail[-3000:], evidence={"cmd": run.cmd, "exit_code": run.exit_code})


def install(S: "AppState") -> None:
    """Register the `unity` tool (idempotent; tests call this on a bare AppState)."""
    get_bridge(S)
    if "unity" in S.tools.tools:
        return

    def offered(s: dict) -> bool:
        return is_unity_project(s.get("folder"))

    @S.tools.add("unity", TOOL_DESCRIPTION, SCHEMA, main_only=True, when=offered)
    async def unity(ctx: ToolContext, a: dict) -> ToolOutput:
        return await run_op(ctx.app, ctx.session, a, cancel=ctx.cancel)


def register(app_: "FastAPI", api: "APIRouter", S: "AppState") -> None:
    from fastapi import Body, HTTPException

    install(S)
    br = get_bridge(S)
    tasks: set[asyncio.Task] = set()

    def _session(sid: str | None) -> dict:
        s = S.store.get(sid) if sid else None
        if not s:
            raise HTTPException(404, "Session not found")
        return s

    @api.get("/unity/state")
    async def unity_state(session_id: str) -> dict:
        return await get_bridge(S).full_state(_session(session_id))

    @api.get("/unity/info")
    async def unity_info() -> dict:
        b = get_bridge(S)
        st = await b.cli_status(refresh=True)
        eds = await b.installed_editors(st.info) if st.info else []
        return {"cli": st.to_dict(), "editors": eds, "config": uc.unity_cfg(S)}

    @api.put("/unity/backend")
    async def set_backend(body: dict = Body(...)) -> dict:
        backend = body.get("backend")
        if backend is not None and backend not in BACKENDS:
            raise HTTPException(400, f"backend must be one of {', '.join(BACKENDS)} or null")
        scope = body.get("scope") or ("session" if body.get("session_id") else "project")
        s = S.store.get(body["session_id"]) if body.get("session_id") else None
        if scope == "session":
            if not s:
                raise HTTPException(404, "Session not found")
            s = S.store.update(s["id"], settings={"unity_backend": backend}) or s
        else:
            folder = (s or {}).get("folder") or body.get("project")
            if not folder or not Path(str(folder)).expanduser().is_dir():
                raise HTTPException(400, "A session with a folder or an existing project folder is needed")
            get_bridge(S).set_project_backend(folder, backend)
        if not s:
            return {"project": str(Path(str(body.get("project"))).expanduser().resolve()), "project_backend": backend}
        d = await get_bridge(S).full_state(s)
        S.bus.publish("unity.state", {**d, "session_id": s["id"]}, s["id"])
        return d

    @api.post("/unity/actions/{action}")
    async def action(action: str, body: dict = Body(...)) -> dict:
        s = _session(body.get("session_id"))
        if not is_unity_project(s.get("folder")):
            raise HTTPException(400, "Not a Unity project")
        if action not in ("install_pipeline", "close_editor", "open_editor", "use_mcp_once", "update_cli"):
            raise HTTPException(404, f"No action {action}")

        async def go() -> None:
            try:
                if action == "use_mcp_once":
                    r = await get_bridge(S).compile(s, consent=gate_consent(S, s), source="tool", force_route="mcp")
                    record_evidence(S, s, "compile", r)
                else:
                    r = await setup_action(S, s, action)
                S.bus.publish("unity.action", {"action": action, "status": r.status, "summary": r.summary}, s["id"])
            except Exception as e:  # noqa: BLE001
                log.warning("unity action %s failed", action, exc_info=True)
                S.bus.publish("unity.action", {"action": action, "status": "error", "summary": str(e)[:300]}, s["id"])
            await publish_state(S, s)

        t = asyncio.create_task(go())
        tasks.add(t)
        t.add_done_callback(tasks.discard)
        return {"status": "pending", "message": "Confirm on the card in the chat" if action != "use_mcp_once"
                else "Compiling over MCP for Unity once"}

    @api.post("/unity/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> dict:
        j = S.jobs.get(job_id)
        if not j or j.get("kind") != "unity":
            raise HTTPException(404, "No such Unity job")
        # The runner ends the process group and sweeps batch Unity left by this job itself.
        return {"cancelled": await S.jobs.cancel(job_id)}


__all__ = ["OPS", "gate_consent", "install", "record_evidence", "register", "run_op", "setup_action"]
