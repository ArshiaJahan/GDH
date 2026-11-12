"""Unity bridge: how the harness's own gates (and the agent's `unity` tool) compile, test and drive a
Unity project.

The user picks a **backend** (auto | mcp | cli: session setting → project default → [unity].backend);
each op resolves to a **route** now (editor_state):
- mcp       — MCP for Unity in the open Editor (below);
- cli_live  — the official Unity CLI against the open Editor's com.unity.pipeline server
              (`unity recompile`, `unity command run_tests|eval|screenshot|…`);
- cli_batch — the official Unity CLI in batch mode, Editor closed (`unity run|test|build`);
- raw_batch — headless-ops `unity.sh` (Editor closed, no official CLI, or `mcp` backend);
- unavailable — with a reason and, for an open Editor in CLI mode, `actions` the UI offers
              (install_pipeline, use_mcp_once, use_clone, close_editor).
Screenshots run on every route (screenshot(): MCP manage_camera, the Pipeline screenshot command or a temporary
camera via eval, unity.sh screenshot → HarnessCli.Screenshot in batch, never -nographics).
An open Editor without a live route can also run compile/tests on a copy of the project (unity_clone,
[unity].clone_when_open: ask = the use_clone action, always = route cli_batch with extra.clone).
Batch ops that need the headless-ops HarnessCli editor scripts (forced recompile, import, menu, a batch
screenshot (version 3), unity.sh builds, Harness.Headless.HarnessCli.* methods) return a `needs_harness` skipped result
with the install_harness action while they're missing (unity_harness; [unity].harness_scripts).
`mcp` backend = the previous behaviour exactly (MCP when open, unity.sh when closed). `cli` never
touches MCP for Unity. `auto` takes the best available ([unity].auto_live_order for an open Editor).
CLI runs go through unity_cli.UnityRunner (one Unity job per project, streamed to the Terminal
drawer, process-tree kill on cancel/timeout). Consent: a gate's preset consent carries
"unity_cli" op keys (compile, test:editmode, …), route-independent; anything else asks with an
approval card of kind "unity" (Plan only mode allows only status/compile/test).

The MCP and unity.sh paths (unchanged):
- **mcp**: the Unity editor has this project open and the session's `unity` MCP server (MCP for
  Unity) is connected. Compile = `read_console(clear)` → `refresh_unity(force, compile=request,
  wait_for_ready)` → `read_console` paged (compile-fix-loop step 6); tests = `run_tests` +
  `get_test_job` polling. Calls go through app.mcp.call under a `hook` role ToolContext, so the
  user's consent for those exact tools (gate preset / trusted hook file) is what lets them pass
  without a card; anything not consented asks as usual.
- **batchmode**: no editor has the project open. The headless-ops skill script
  (`skills/headless-ops/scripts/unity.sh compile|test …`) runs as a `run_command` job under the
  same hook context: approvals, the allowlist and Plan mode apply; the exact command line is what
  consent covers (see command()).
- otherwise (**unavailable**): the editor has the project open but MCP isn't reachable (or it's
  not a Unity project, or unity.sh is missing). Gates then report `skipped` with the reason (fail
  open, loudly): batchmode is never run while an editor has the project open.

Compiler output is parsed with compile-fix-loop's `parse_unity_log.py`, imported in-process (works
in the frozen app; a small regex fallback if the script is missing).

`BridgeResult.report` is raw outside text (Unity console, Unity log): callers must wrap it as
untrusted before a model sees it (HookResult.untrusted does that for gates).

Tests inject a fake: `app.extensions["unity_bridge"] = FakeUnityBridge(app, compile=[...])`, or a
real UnityBridge with `editor_open=` and a fake `unity.sh` on PATH (unity_sh() looks there first).
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import re
import shlex
import shutil
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ..skills import builtin_skills_dir
from . import unity_cli as uc
from . import unity_clone as uclone
from . import unity_harness as uh
from .hookbus import hook_context

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)

UNITY_SERVER = "unity"  # the MCP for Unity preset's server name ([mcp.presets.unity])
MCP_COMPILE_TOOLS = ("refresh_unity", "read_console")
MCP_TEST_TOOLS = ("run_tests", "get_test_job")
MCP_SHOT_TOOL = "manage_camera"  # MCP for Unity 10.x: action=screenshot (game_view, camera / view_position / view_rotation)
DEFAULT_GATE_TIMEOUT_S = 180     # [hooks] gate_timeout_s: MCP compile wait (focus/throttle) and test polling
DEFAULT_BATCH_TIMEOUT_S = 900    # [hooks] batchmode_timeout_s: a cold batchmode import can take minutes
MAX_CONSOLE_PAGES = 10
TEST_PLATFORMS = {"editmode": "EditMode", "edit": "EditMode", "playmode": "PlayMode", "play": "PlayMode"}

STALE_HINT = ("Unity seems throttled (an unfocused editor compiles slowly): bring the Unity window to "
              "the front, then run the gate again.")

BACKENDS = uc.BACKENDS
ROUTES = ("mcp", "cli_live", "cli_batch", "raw_batch", "unavailable")
ROUTE_LABELS = {"mcp": "MCP for Unity", "cli_live": "Unity CLI, live Editor", "cli_batch": "Unity CLI, batch",
                "raw_batch": "batch (unity.sh)", "unavailable": "unavailable", "files": "project files"}
# Which routes can run which op ("state" ops never need one).
OP_ROUTES: dict[str, tuple[str, ...]] = {
    "compile": ("mcp", "cli_live", "cli_batch", "raw_batch"),
    "test": ("mcp", "cli_live", "cli_batch", "raw_batch"),
    "build": ("cli_batch", "raw_batch"),
    "exec": ("cli_batch", "raw_batch"),
    "import": ("raw_batch",),
    "eval": ("cli_live",),
    "menu": ("cli_live", "raw_batch"),
    "command": ("cli_live",),
    "screenshot": ("mcp", "cli_live", "cli_batch", "raw_batch"),  # batch: unity.sh → HarnessCli.Screenshot
    "play": ("cli_live",),
}
# Approval classes (unity tool + gates): read never asks; verify asks unless consented (and runs in
# Plan only mode); change / code / setup always ask unless allowlisted and never run in Plan mode.
READ_OPS = {"status", "commands", "log"}
VERIFY_OPS = {"compile", "test"}
CODE_OPS = {"eval"}
SETUP_OPS = {"install_pipeline", "open_editor", "close_editor", "self_update", "install_harness"}
# Pipeline commands that only read (no card, Plan mode ok); anything else is a change (default-deny).
READ_COMMANDS = {"editor_status", "recompile_status", "test_status", "test status", "test list", "list_tests",
                 "get_scene_hierarchy", "find_gameobjects", "list_build_targets", "wait_status"}
ACTION_ORDER = ("install_pipeline", "use_mcp_once", "use_clone", "close_editor", "install_harness")
CLONE_OPS = {"compile", "test", "screenshot"}  # ops that may run on a copy of the project while the Editor holds it
CLONE_ACTION_OPS = {"compile", "test"}  # the chip's use_clone action (it compiles on the copy)
SHOT_HARNESS_VERSION = 3  # HarnessCli.Screenshot
SHOT_DIR = "Logs/harness/screenshots"  # git-ignored by Unity's default .gitignore (/[Ll]ogs/)
HARNESS_METHOD = "Harness.Headless.HarnessCli."
PROJECT_BACKEND_KEY = "unity.backend:"
ALLOW_KEY = "unity.allow:"


def project_key(folder: Path | str) -> str:
    """The same project key the ladder uses (resolved absolute path)."""
    return str(Path(folder).expanduser().resolve())


@dataclass
class EditorState:
    """mode: the route for the op asked about ("mcp" | "cli_live" | "cli_batch" | "raw_batch" |
    "unavailable"); reason explains "unavailable". The other fields describe the backend choice,
    the official CLI, the live Editor (Pipeline) state and the actions the UI may offer."""

    mode: str
    unity_project: bool = False
    editor_open: bool = False
    mcp_connected: bool = False
    reason: str = ""
    backend: str = "auto"
    backend_source: str = "global"            # global | project | session
    live: dict = field(default_factory=dict)  # LiveState.to_dict()
    cli: dict = field(default_factory=dict)   # CliStatus.to_dict()
    actions: list[str] = field(default_factory=list)
    routes: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)  # session/project/global backend, manifest facts, busy

    def to_dict(self) -> dict:
        return {"mode": self.mode, "route": self.mode, "unity_project": self.unity_project,
                "editor_open": self.editor_open, "mcp_connected": self.mcp_connected, "reason": self.reason,
                "backend": self.backend, "backend_source": self.backend_source, "live": self.live, "cli": self.cli,
                "actions": self.actions, "routes": self.routes, **self.extra}


@dataclass
class BridgeResult:
    """One compile or test run.

    - status: pass | fail | skipped | error. Only an observed, complete, passing run is "pass";
      timeouts, partial or empty results never are.
    - summary: one line for people and the model ("3 compile errors (2 root causes)").
    - report: the raw evidence text (errors in fix order, failing tests); outside content.
    - errors: compile errors (compile) or failed tests (tests).
    - evidence: structured facts for gate_runs.detail (mode, counts, names, log path)."""

    status: str
    summary: str
    mode: str = ""
    report: str = ""
    errors: int = 0
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"status": self.status, "summary": self.summary, "mode": self.mode, "report": self.report,
                "errors": self.errors, "evidence": self.evidence}


# ---------------------------------------------------------------- helpers


def is_unity_project(folder: Path | str | None) -> bool:
    return bool(folder) and (Path(folder) / "ProjectSettings" / "ProjectVersion.txt").is_file()


def skill_script(skill: str, rel: str) -> Path:
    """A script shipped with a built-in skill (trusted app content)."""
    return builtin_skills_dir() / skill / rel


_SCRIPT_CACHE: dict[str, tuple[float, ModuleType]] = {}


def load_script(path: Path) -> ModuleType | None:
    """Import a skill's Python script in-process (cached by mtime; works in the frozen app).
    None when it's missing or doesn't import."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = str(path)
    hit = _SCRIPT_CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        spec = importlib.util.spec_from_file_location(f"_ws_skill_{path.stem}_{abs(hash(key))}", path)
        if not spec or not spec.loader:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 — a broken skill script must not break the gate
        log.warning("couldn't import %s", path, exc_info=True)
        return None
    _SCRIPT_CACHE[key] = (mtime, mod)
    return mod


_UNTRUSTED_WRAP = re.compile(r'\A<(untrusted-[0-9a-f]+) source="[^"]*">\n(.*)\n</\1>', re.S)


def unwrap_untrusted(text: str) -> str:
    """The body of a finalized tool output's untrusted block (MCP results arrive wrapped), plus
    any notes after it; text without a wrapper comes back unchanged."""
    m = _UNTRUSTED_WRAP.match(text or "")
    return (m.group(2) + text[m.end():]) if m else (text or "")


_CS_ERR = re.compile(r"error CS\d{4}")


def parse_compile_output(text: str, *, console_json: Any = None) -> dict:
    """Compile errors in a Unity log / command output (or read_console JSON entries), grouped by
    root cause, via compile-fix-loop/scripts/parse_unity_log.py. Returns
    {errors, root_causes, report, warnings}."""
    mod = load_script(skill_script("compile-fix-loop", "scripts/parse_unity_log.py"))
    if mod is None:  # fallback: count `error CS` lines
        src = text or ""
        if console_json is not None:
            src = "\n".join(str(e.get("message", "")) if isinstance(e, dict) else str(e)
                            for e in _entries(console_json))
        lines = sorted({ln.strip() for ln in src.splitlines() if _CS_ERR.search(ln)})
        return {"errors": len(lines), "root_causes": len(lines), "warnings": 0, "report": "\n".join(lines[:40])}
    issues = mod.parse_console_json(console_json) if console_json is not None else mod.parse_text(text or "")
    issues = mod.dedupe(issues)
    errors = [i for i in issues if i["severity"] == "error" and i["kind"] in ("compile", "infra")]
    warnings = [i for i in issues if i["severity"] == "warning"]
    groups = mod.group_root_causes(errors)
    out = []
    if groups:
        out.append("ROOT CAUSES (fix in this order):")
        for n, g in enumerate(groups[:15], 1):
            extra = len(g["members"]) - 1
            out.append(f"{n:2d}. {g['cause']}")
            if h := mod.hint_for(g["root"]["message"]):
                out.append("    hint: " + h)
            out.append("    " + mod.fmt(g["root"]) + (f"  (+{extra} related)" if extra > 0 else ""))
        out.append("\nALL ERRORS (deduplicated):")
        out += ["  " + mod.fmt(i) for i in errors[:30]]
        if len(errors) > 30:
            out.append(f"  ... {len(errors) - 30} more")
    return {"errors": len(errors), "root_causes": len(groups), "warnings": len(warnings), "report": "\n".join(out)}


def _entries(obj: Any) -> list:
    if isinstance(obj, dict):
        if isinstance(obj.get("result"), (dict, list)):
            return _entries(obj["result"])
        data = obj.get("data", obj.get("items", obj.get("lines")))
        if isinstance(data, dict):
            data = data.get("items", data.get("lines", []))
        return data if isinstance(data, list) else []
    return obj if isinstance(obj, list) else []


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        m = re.search(r"[\[{].*[\]}]", text or "", re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def _find(obj: Any, *keys: str) -> Any:
    """The first value of any of `keys`, searching dicts depth-first."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] is not None:
                return obj[k]
        for v in obj.values():
            if (r := _find(v, *keys)) is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            if (r := _find(v, *keys)) is not None:
                return r
    return None


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


_EXIT = re.compile(r"\Aexit code (-?\d+)\n?")
_RESULT = re.compile(r"^RESULT: (OK|FAIL)\b ?(.*)$", re.M)


def _cmd_result(text: str) -> tuple[int | None, str, str]:
    """(exit code, output, last RESULT line) of a run_command output."""
    m = _EXIT.match(text or "")
    if not m:
        return None, text or "", ""
    body = text[m.end():]
    res = _RESULT.findall(body)
    return int(m.group(1)), body, (f"RESULT: {res[-1][0]} {res[-1][1]}".strip() if res else "")


# ------------------------------------------------------------------ bridge


EditorProbe = Callable[[Path], Awaitable[bool]]


class UnityBridge:
    """app.extensions["unity_bridge"] (see get_bridge). Stateless apart from config reads, small
    caches and the per-project Unity job lock (unity_cli.UnityRunner)."""

    CLI_CACHE_S = 60.0

    def __init__(self, app: "AppState", *, editor_open: EditorProbe | None = None):
        self.app = app
        self._editor_open = editor_open
        self._cli: tuple[float, uc.CliStatus] | None = None
        self._editors: tuple[float, list[dict]] | None = None
        self._test_cmd: dict[str, tuple[float, str]] = {}
        self._eval_ok: dict[str, set[str]] = {}  # session id -> sha256 of eval code the user allowed
        self._harness_wanted: set[str] = set()  # projects where an op asked for the harness scripts

    # ----------------------------------------------------------- config

    def _hooks_cfg(self) -> dict:
        return getattr(self.app.config, "hooks", None) or {}

    def cfg(self) -> dict:
        return uc.unity_cfg(self.app)

    def gate_timeout(self) -> int:
        return max(int(self._hooks_cfg().get("gate_timeout_s") or DEFAULT_GATE_TIMEOUT_S), 5)

    def batch_timeout(self) -> int:
        v = self._hooks_cfg().get("batchmode_timeout_s") or (getattr(self.app.config, "unity", None) or {}).get(
            "batch_timeout_s") or max(DEFAULT_BATCH_TIMEOUT_S, self.gate_timeout())
        return min(max(int(v), 30), 1800)

    @property
    def runner(self) -> uc.UnityRunner:
        return uc.get_runner(self.app)

    # --------------------------------------------------------- backend choice

    def project_backend(self, project: Path | str) -> str | None:
        v = self.app.db.kv_get(PROJECT_BACKEND_KEY + project_key(project))
        return v if v in BACKENDS else None

    def set_project_backend(self, project: Path | str, backend: str | None) -> None:
        if backend is not None and backend not in BACKENDS:
            raise ValueError(f"backend must be one of {', '.join(BACKENDS)}")
        key = PROJECT_BACKEND_KEY + project_key(project)
        if backend is None:
            self.app.db.execute("DELETE FROM kv WHERE key=?", [key])
        else:
            self.app.db.kv_set(key, backend)

    @staticmethod
    def session_backend(session: dict) -> str | None:
        v = (session.get("settings") or {}).get("unity_backend")
        return v if v in BACKENDS else None

    def backend_for(self, session: dict) -> tuple[str, str]:
        """(backend, source): session.settings["unity_backend"] → the project default → [unity].backend."""
        if b := self.session_backend(session):
            return b, "session"
        folder = session.get("folder")
        if folder and (b := self.project_backend(folder)):
            return b, "project"
        return self.cfg()["backend"], "global"

    # --------------------------------------------------------- commands

    @staticmethod
    def unity_sh() -> Path | None:
        """The headless-ops wrapper: `unity.sh` on PATH first (a user's own wrapper, or a fake in
        tests), else the built-in skill's script."""
        if p := shutil.which("unity.sh"):
            return Path(p)
        p = skill_script("headless-ops", "scripts/unity.sh")
        return p if p.is_file() else None

    def command(self, project: Path | str, op: str, *, platform: str = "editmode",
                category: str | None = None, test_filter: str | None = None) -> str | None:
        """The exact unity.sh command line a batchmode (raw_batch) gate runs (consent is given for
        exactly these). op: "compile" | "test". None when unity.sh can't be found."""
        sh = self.unity_sh()
        if not sh:
            return None
        parts = ["bash", str(sh)]
        if op == "compile":
            parts += ["compile"]
        else:
            parts += ["test", TEST_PLATFORMS.get(platform.lower(), "EditMode").lower()]
            if category:
                parts += ["--category", category]
            if test_filter:
                parts += ["--filter", test_filter]
        parts += ["--project", str(Path(project))]
        return " ".join(shlex.quote(p) for p in parts)

    @staticmethod
    def op_key(op: str, platform: str | None = None) -> str:
        return f"test:{TEST_PLATFORMS.get((platform or 'editmode').lower(), 'EditMode').lower()}" if op in ("test", "tests") else op

    def consent_for(self, project: Path | str, ops: list[dict] | None = None) -> dict[str, set[str]]:
        """What the Unity gates need consent for in `project`: MCP tools ("unity__<tool>"), the
        exact unity.sh command lines, and route-independent Unity CLI op keys ("compile",
        "test:editmode", …). ops: [{"op": "compile"} | {"op": "test", "platform", "category",
        "filter"}] (default: compile + EditMode tests)."""
        ops = ops or [{"op": "compile"}, {"op": "test", "platform": "editmode"}]
        tools: set[str] = set()
        cmds: set[str] = set()
        keys: set[str] = set()
        for o in ops:
            tools |= {f"{UNITY_SERVER}__{t}" for t in (MCP_COMPILE_TOOLS if o["op"] == "compile" else MCP_TEST_TOOLS)}
            if c := self.command(project, o["op"], platform=o.get("platform") or "editmode",
                                 category=o.get("category"), test_filter=o.get("filter")):
                cmds.add(c)
            keys.add(self.op_key(o["op"], o.get("platform")))
        return {"mcp": tools, "run_command": cmds, "unity_cli": keys}

    def cli_consented(self, consent: dict | None, key: str) -> bool:
        """A gate consent covers this Unity CLI op: its op key, or (consent given before the CLI
        backend existed) the MCP tools of the same gate."""
        c = consent or {}
        if key in (c.get("unity_cli") or ()):
            return True
        legacy = MCP_COMPILE_TOOLS if key == "compile" else MCP_TEST_TOOLS if key.startswith("test:") else ()
        return bool(legacy) and {f"{UNITY_SERVER}__{t}" for t in legacy} <= set(c.get("mcp") or ())

    def allowed_ops(self, project: Path | str) -> set[str]:
        return set(self.app.db.kv_get(ALLOW_KEY + project_key(project)) or [])

    def allow_op(self, project: Path | str, key: str) -> None:
        cur = sorted(self.allowed_ops(project) | {key})
        self.app.db.kv_set(ALLOW_KEY + project_key(project), cur)

    @staticmethod
    def op_class(op: str, name: str | None = None) -> str:
        if op in READ_OPS:
            return "read"
        if op in VERIFY_OPS:
            return "verify"
        if op in CODE_OPS:
            return "code"
        if op in SETUP_OPS:
            return "setup"
        if op == "command" and name and name.strip() in READ_COMMANDS:
            return "read"
        return "change"

    async def ensure_allowed(self, session: dict, op: str, key: str, *, route: str, argv: list[str] | None = None,
                             consent: dict | None = None, detail: str = "", code: str | None = None,
                             name: str | None = None) -> str | None:
        """None when the op may run, else the refusal text. Plan only mode: read and verify ops only.
        Verify ops pass with gate consent or the project's "always allow"; everything else asks with a
        `unity` approval card (eval always shows its code; its allow is per session and per code)."""
        session = self.app.store.get(session["id"])
        if session is None:
            return "The session no longer exists."
        cls = self.op_class(op, name)
        mode = session.get("mode", "ask")
        if cls == "read":
            return None
        if mode == "plan" and cls != "verify":
            return f"Plan only mode: Unity {op} isn't run (only status, compile and tests are). Describe it instead."
        folder = session.get("folder") or ""
        if cls == "code":
            if self.cfg().get("eval") == "off":
                return "Unity eval is off ([unity].eval = \"off\")."
            sha = hashlib.sha256((code or "").encode()).hexdigest()
            if sha in self._eval_ok.get(session["id"], set()):
                return None
        elif self.cli_consented(consent, key) or key in self.allowed_ops(folder) \
                or self.app.approvals.allowlisted("unity", key):
            return None
        cmd = shlex.join(argv) if argv else ""
        risk = {"verify": "Compiles / runs tests; writes only Library/, Logs/ and Temp/.",
                "change": "Can change the project or the open scene.",
                "code": "Runs this C# inside the Unity Editor (full Editor access).",
                "setup": "Changes the project setup or the Editor process."}[cls]
        md = [f"**Route:** {ROUTE_LABELS.get(route, route)}", risk]
        if detail:
            md.append(detail)
        if code is not None:
            md.append("```csharp\n" + code[:6000] + "\n```")
        if cmd:
            md.append("```sh\n" + cmd[:4000] + "\n```")
        always = "Allow for this code in this session" if cls == "code" else f"Always allow `{key}` in this project"
        buttons = [{"id": "once", "label": "Run", "decision": "approve", "style": "primary"},
                   {"id": "always", "label": always, "decision": "approve"},
                   {"id": "deny", "label": "Decline", "decision": "deny", "style": "ghost"}]
        if cls == "setup":
            buttons = [buttons[0], buttons[2]]
        res = await self.app.approvals.ask(session["id"], "unity", {
            "subject": f"Unity {op}" + (f" `{name}`" if name else "") + f" ({ROUTE_LABELS.get(route, route)})",
            "markdown": "\n\n".join(md), "op": op, "key": key, "route": route, "argv": argv or [],
            "project": folder, "buttons": buttons})
        if res.get("status") != "approved":
            return f"User declined Unity {op}."
        if res.get("choice") == "always" and cls in ("code", "change", "verify"):
            if cls == "code":
                self._eval_ok.setdefault(session["id"], set()).add(hashlib.sha256((code or "").encode()).hexdigest())
            elif folder:
                self.allow_op(folder, key)
        return None

    # ------------------------------------------------------------ state

    async def editor_open(self, project: Path) -> bool:
        """Whether a Unity editor has `project` open (the router's pgrep rule, then the lockfile;
        not the lockfile while one of our own Unity jobs runs on it: that one holds it)."""
        if self._editor_open is not None:
            return await self._editor_open(project)
        ours = str(Path(project).expanduser().resolve()) in self.runner.busy
        return await editor_has_project(project, check_lock=not ours)

    async def mcp_ready(self, session: dict) -> tuple[bool, str]:
        """Whether the session's `unity` MCP server is connected (connecting it if it's on) and
        offers the compile tools."""
        mgr = self.app.mcp
        if mgr is None:
            return False, "MCP isn't available"
        try:
            if not any(s["name"] == UNITY_SERVER for s in mgr.enabled_for(session)):
                return False, f"the {UNITY_SERVER} connector is off for this session"
            c = mgr.conns.get(UNITY_SERVER)
            if not (c and c.session):
                c = await asyncio.wait_for(mgr.connect(UNITY_SERVER), 30)
            names = {t.name for t in (c.tools or [])}
        except Exception as e:  # noqa: BLE001
            return False, f"the {UNITY_SERVER} MCP server isn't reachable ({str(e)[:200]})"
        if not set(MCP_COMPILE_TOOLS) <= names:
            return False, f"the {UNITY_SERVER} MCP server doesn't offer {', '.join(MCP_COMPILE_TOOLS)}"
        return True, ""

    async def cli_status(self, refresh: bool = False) -> uc.CliStatus:
        """The official Unity CLI (found, version, usable). Cached a minute."""
        if not refresh and self._cli and time.monotonic() - self._cli[0] < self.CLI_CACHE_S:
            return self._cli[1]
        st = await asyncio.to_thread(uc.find_unity_cli, self.cfg())
        self._cli = (time.monotonic(), st)
        return st

    async def installed_editors(self, cli: uc.UnityCliInfo | None = None) -> list[dict]:
        if self._editors and time.monotonic() - self._editors[0] < self.CLI_CACHE_S:
            return self._editors[1]
        cli = cli or (await self.cli_status()).info
        eds: list[dict] = []
        if cli:
            r = await self.runner.quick(uc.argv_editors(cli), timeout_s=30)
            data = r.data
            if isinstance(data, list):
                eds = [{"version": str(e.get("version")), "architecture": e.get("architecture"),
                        "location": e.get("location")} for e in data if isinstance(e, dict)]
        self._editors = (time.monotonic(), eds)
        return eds

    async def editor_state(self, session: dict, op: str = "compile", *, wait: bool = False,
                           force_route: str | None = None, memo: dict | None = None) -> EditorState:
        """The route `op` would take now (§ module doc), plus everything the chip shows. wait=True
        (when about to run): a starting / load-pending live Editor gets [unity].live_wait_s first.
        memo: shares the Editor / MCP probes between several calls (full_state)."""
        memo = {} if memo is None else memo

        async def mcp_ok() -> tuple[bool, str]:
            if "mcp" not in memo:
                memo["mcp"] = await self.mcp_ready(session)
            return memo["mcp"]

        folder = session.get("folder")
        root = Path(folder).expanduser().resolve() if folder else None
        if not root or not is_unity_project(root):
            return EditorState("unavailable", reason="not a Unity project (no ProjectSettings/ProjectVersion.txt)")
        cfg = self.cfg()
        backend, source = self.backend_for(session)
        extra = {"session_backend": self.session_backend(session), "project_backend": self.project_backend(root),
                 "global_backend": cfg["backend"], "pipeline_in_manifest": uc.pipeline_in_manifest(root),
                 "mcp_in_manifest": uc.mcp_in_manifest(root), "busy": self.runner.busy.get(str(root))}
        st = EditorState("unavailable", True, backend=backend, backend_source=source, extra=extra)
        if "open" not in memo:
            memo["open"] = await self.editor_open(root)
        st.editor_open = is_open = memo["open"]
        need_cli = backend != "mcp"
        cli = await self.cli_status() if need_cli else None
        if cli:
            st.cli = cli.to_dict()
        usable = cli.info if cli and cli.ok else None
        if force_route == "mcp":
            ok, why = await mcp_ok()
            st.mcp_connected = ok
            st.mode, st.reason = ("mcp", "") if ok and is_open else ("unavailable", why or "Unity isn't open")
            return st
        if "harness" not in memo:
            memo["harness"] = await asyncio.to_thread(self._harness_info, root, cfg)
        st.extra["harness"] = memo["harness"]
        if force_route == "clone":
            if is_open and self._clone_ok(op, usable, cfg):
                self._use_clone(st)
            else:
                st.reason = ("a copy is only used while the Editor holds the project" if not is_open else
                             f"`{op}` can't run on a copy of the project" if op not in CLONE_OPS else
                             "running on a copy is off ([unity].clone_when_open = \"never\")"
                             if cfg.get("clone_when_open") == "never" else
                             f"running on a copy needs the official Unity CLI: {cli.reason if cli else 'not checked'}")
            st.routes = {op: st.mode}
            return st
        if is_open:
            order = ["mcp"] if backend == "mcp" else ["cli_live"] if backend == "cli" else \
                [r for r in (cfg.get("auto_live_order") or ["mcp", "cli_live"]) if r in ("mcp", "cli_live")] or ["mcp", "cli_live"]
            whys: list[str] = []
            for choice in order:
                if choice == "mcp":
                    ok, why = await mcp_ok()
                    st.mcp_connected = ok
                    if ok and "mcp" in OP_ROUTES.get(op, ("mcp",)):
                        st.mode = "mcp"
                        break
                    whys.append(f"the MCP bridge isn't reachable: {why}" if not ok else "MCP for Unity can't run this op")
                else:
                    if not usable:
                        whys.append(f"the Unity CLI live route isn't available: {cli.reason if cli else 'not checked'}")
                        continue
                    live = await uc.live_state(self.runner, usable, root, editor_open=True)
                    if wait and live.state in ("starting", "load_pending"):
                        n = uc.cfg_int(cfg, "live_wait_s", 1, 600)
                        await self.runner.quick(uc.argv_status(usable, root, until_ready_s=n), cwd=root, timeout_s=n + 15)
                        uc.invalidate_live(root)
                        live = await uc.live_state(self.runner, usable, root, editor_open=True)
                    st.live = live.to_dict()
                    if live.state == "ready" and "cli_live" in OP_ROUTES.get(op, ("cli_live",)):
                        st.mode = "cli_live"
                        break
                    if live.state == "ready":
                        whys.append(f"the live Editor can't run `{op}` (close Unity for a batch run)")
                    elif live.state == "load_pending":
                        whys.append("Switch to the Unity window once so it loads the Pipeline package")
                    else:
                        whys.append(live.reason or f"Pipeline: {live.state}")
            if st.mode == "unavailable":
                if backend == "mcp":
                    st.reason = (f"Unity has this project open but the MCP bridge isn't reachable: "
                                 f"{whys[0].split('reachable: ', 1)[-1] if whys else ''}. Start MCP for Unity in the editor "
                                 "(Window > MCP for Unity) and turn on the unity connector; batchmode can't run "
                                 "while the editor has the project open.")
                elif cfg.get("clone_when_open") == "always" and self._clone_ok(op, usable, cfg):
                    self._use_clone(st)
                else:
                    st.reason = ("Unity has this project open but " + "; ".join(whys)
                                 + ". Batch mode can't run while the Editor has the project open.")
                    st.actions = self._actions(st, usable, op)
        else:
            routes = OP_ROUTES.get(op, ("cli_batch", "raw_batch"))
            if backend != "mcp" and usable and cfg.get("prefer_official_cli", True) and "cli_batch" in routes:
                st.mode = "cli_batch"
            elif "raw_batch" in routes and self.unity_sh():
                st.mode = "raw_batch"
            elif "raw_batch" in routes:
                st.reason = "headless-ops/scripts/unity.sh not found"
            elif any(r in routes for r in ("mcp", "cli_live")):
                st.reason = f"`{op}` needs the Unity Editor open (with the Pipeline package)"
            else:
                st.reason = f"`{op}` needs the official Unity CLI: {cli.reason if cli else 'CLI backend is off'}"
        if st.extra["harness"].get("offer") and "install_harness" not in st.actions:
            st.actions = [a for a in ACTION_ORDER if a in {*st.actions, "install_harness"}]
        st.routes = {"compile": st.mode} if op == "compile" else {op: st.mode}
        return st

    def _actions(self, st: EditorState, cli: uc.UnityCliInfo | None, op: str = "compile") -> list[str]:
        out = []
        live = st.live.get("state")
        if cli and live == "absent":
            out.append("install_pipeline")
        if st.extra.get("mcp_in_manifest") and st.backend == "cli":
            out.append("use_mcp_once")
        if self.cfg().get("clone_when_open", "ask") == "ask" and op in CLONE_ACTION_OPS and self._clone_ok(op, cli, self.cfg()):
            out.append("use_clone")
        if cli:
            out.append("close_editor")
        return [a for a in ACTION_ORDER if a in out]

    # ------------------------------------------------------------ clone + harness

    @staticmethod
    def _clone_ok(op: str, cli: uc.UnityCliInfo | None, cfg: dict) -> bool:
        """Whether `op` may run as cli_batch on a copy of the project (§2.5 action 3)."""
        return (bool(cli) and op in CLONE_OPS and cfg.get("clone_when_open", "ask") != "never"
                and bool(cfg.get("prefer_official_cli", True)))

    @staticmethod
    def _use_clone(st: EditorState) -> None:
        st.mode = "cli_batch"
        st.extra["clone"] = True
        st.actions = []
        st.reason = f"Unity has this project open: batch jobs run {uclone.CLONE_NOTE}"

    async def _on_clone(self, session: dict, run: Callable[[Path], Awaitable[BridgeResult]]) -> BridgeResult:
        """Bring the copy up to date, then run(clone root) under the clone's lock; the result is
        labelled as coming from a copy (summary + evidence.clone)."""
        root = Path(session["folder"]).expanduser().resolve()
        async with uclone.lock(root):
            try:
                info = await uclone.sync_clone(root, timeout_s=uc.cfg_int(self.cfg(), "batch_timeout_s", 30, 4 * 3600))
            except uclone.CloneError as e:
                return BridgeResult("skipped", f"couldn't copy the project for a batch run: {e}", "cli_batch",
                                    evidence={"route": "cli_batch", "clone": True})
            r = await run(Path(info["clone"]))
        r.summary = f"{r.summary} ({uclone.CLONE_NOTE})"
        r.evidence.update({"clone": True, "clone_dir": info["clone"], "clone_first": info["first"],
                           "project": str(root)})
        return r

    def _harness_info(self, root: Path, cfg: dict) -> dict:
        """The harness scripts' status for the state (+ "offer": show the install_harness action:
        an op asked for them, or an older shipped version is installed)."""
        try:
            h = uh.harness_status(root)
        except OSError as e:  # templates missing from the app bundle
            return {"installed": False, "error": str(e), "offer": False}
        on = cfg.get("harness_scripts", "ask") != "never"
        wanted = project_key(root) in self._harness_wanted and not h["installed"]
        out = {k: h[k] for k in ("installed", "version", "current_version", "outdated", "modified", "path")}
        out["offer"] = on and (wanted or h["outdated"])
        if out["offer"] and not h["installed"] and uh.external_harness(root):
            out["offer"] = False
        return out

    def harness_installed(self, root: Path | str) -> None:
        self._harness_wanted.discard(project_key(root))

    async def _needs_harness(self, root: Path, what: str, mode: str, *, min_version: int = 1) -> BridgeResult | None:
        """A `needs_harness` skipped result when `what` needs HarnessCli or a newer installed version
        ([unity].harness_scripts = "never": None, unity.sh then reports it missing as before)."""
        if self.cfg().get("harness_scripts", "ask") == "never":
            return None
        present = await asyncio.to_thread(uh.harness_present, root)
        h = await asyncio.to_thread(uh.harness_status, root)
        upgrade = h["installed"] and h["version"] < min_version
        if present and not upgrade:
            return None
        self._harness_wanted.add(project_key(root))
        reason = (f"version {h['version']} is installed but version {min_version} or newer is required. Upgrade them"
                  if upgrade else "the project doesn't have them. The user can install them")
        return BridgeResult(
            "skipped", f"needs_harness: {what} needs the headless-ops harness editor scripts (HarnessCli); "
                       f"{reason} with the install_harness action "
                       f"(3 editor scripts in {uh.HARNESS_DIR}, kept out of git; asks first), or op install_harness.",
            mode, evidence={"route": mode, "needs_harness": True, "actions": ["install_harness"],
                            "harness": h})

    async def full_state(self, session: dict) -> dict:
        """editor_state for compile plus the route of test/build/eval (for the chip and the API)."""
        memo: dict = {}
        st = await self.editor_state(session, "compile", memo=memo)
        d = st.to_dict()
        routes = {"compile": st.mode}
        if st.unity_project:
            for op in ("test", "build", "eval"):
                routes[op] = (await self.editor_state(session, op, memo=memo)).mode
        d["routes"] = routes
        return d

    def _skip(self, st: EditorState) -> "BridgeResult":
        return BridgeResult("skipped", st.reason, mode=st.mode, evidence={"state": st.to_dict()})

    def _paths(self, root: Path, op: str, ext: str = "log") -> Path:
        d = root / "Logs" / "harness"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{op}-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.{ext}"

    async def _editor_arg(self, root: Path, cli: uc.UnityCliInfo) -> tuple[Path | None, str]:
        """(--editor-path to pass or None, a setup problem). Only a configured editor_path is
        passed; otherwise the CLI resolves the project's version itself — we just check it's there."""
        cfg = self.cfg()
        if cfg.get("editor_path"):
            p, why = uc.find_editor_binary(root, cfg)
            return (p, "") if p else (None, why)
        p, why = uc.find_editor_binary(root, cfg, await self.installed_editors(cli))
        return None, ("" if p else why)

    # ---------------------------------------------------------- compile

    async def compile(self, session: dict, *, consent: dict[str, set[str]] | None = None, force: bool = False,
                      source: str = "gate", cancel: asyncio.Event | None = None,
                      force_route: str | None = None) -> BridgeResult:
        st = await self.editor_state(session, "compile", wait=True, force_route=force_route)
        if st.mode == "mcp":
            return await self._compile_mcp(session, consent)
        if st.extra.get("clone"):
            r = await self._on_clone(session, lambda r: self._compile_cli_batch(session, st, consent, source, cancel,
                                                                              root=r))
            if force:
                r.summary += "; force=True is not supported on the clone path (regular batch compile only)"
            return r
        if force and st.mode in ("cli_batch", "raw_batch"):
            root = Path(session["folder"]).expanduser().resolve()
            if nh := await self._needs_harness(root, "a forced recompile in batch mode", st.mode):
                return nh
        if st.mode == "raw_batch":
            return await self._compile_batch(session, consent, source=source, force=force, cancel=cancel)
        if st.mode == "cli_live":
            return await self._compile_live(session, st, consent, source, cancel)
        if st.mode == "cli_batch":
            if force:  # a forced clean recompile needs HarnessCli (no -quit): unity.sh
                if self.unity_sh():
                    return await self._compile_batch(session, consent, source=source, force=True, cancel=cancel)
            return await self._compile_cli_batch(session, st, consent, source, cancel)
        if st.live.get("state") == "safe_mode":
            return self._compile_safe_mode(session, st)
        return self._skip(st)

    async def _cli_info(self) -> uc.UnityCliInfo:
        st = await self.cli_status()
        assert st.info is not None
        return st.info

    async def _compile_live(self, session: dict, st: EditorState, consent: dict | None, source: str,
                            cancel: asyncio.Event | None) -> BridgeResult:
        root = Path(session["folder"]).expanduser().resolve()
        cli = await self._cli_info()
        t = uc.cfg_int(self.cfg(), "live_timeout_s", 10, 3600)
        argv = uc.argv_recompile(cli, root, t)
        if why := await self.ensure_allowed(session, "compile", "compile", route="cli_live", argv=argv, consent=consent):
            return BridgeResult("skipped", f"Unity CLI compile didn't run: {why}", "cli_live", evidence={"cmd": shlex.join(argv)})
        run = await self.runner.run(session, argv, project=root, label="Unity compile · CLI live", timeout_s=t,
                                    cancel=cancel, sweep=False)
        r = uc.result_from_recompile(run)
        r.evidence["started_at"] = run.started_at
        r.evidence["job_id"] = run.job_id
        uc.invalidate_live(root)
        if r.status == "skipped" and r.evidence.get("unreachable"):
            if st.backend == "auto":
                ok, _ = await self.mcp_ready(session)
                if ok:
                    return await self._compile_mcp(session, consent)
            live = await uc.live_state(self.runner, cli, root, editor_open=True, use_cache=False)
            if live.state == "safe_mode":
                st.live = live.to_dict()
                return self._compile_safe_mode(session, st)
        return r

    def _compile_safe_mode(self, session: dict, st: EditorState) -> BridgeResult:
        """Safe Mode: the Editor booted with compile errors, so no bridge loads. The errors come from
        the Editor log (this project's lines only); never a pass."""
        root = Path(session["folder"]).expanduser().resolve()
        text, src = uc.safe_mode_errors(root)
        ev = {"route": "cli_live", "source": "editor_log_safe_mode", "log": src, "state": st.to_dict()}
        if not text:
            return BridgeResult("skipped", "Unity opened this project in Safe Mode (compile errors at boot) but the "
                                           "Editor log shows none for it: fix them in Unity, or close it for a batch "
                                           "compile", "cli_live", evidence=ev)
        p = parse_compile_output(text)
        n = p["errors"] or 1
        ev.update({"errors": n, "root_causes": p["root_causes"]})
        return BridgeResult("fail", f"{n} compile error{'s' if n != 1 else ''} ({p['root_causes']} root "
                                    f"cause{'s' if p['root_causes'] != 1 else ''}; Unity is in Safe Mode)", "cli_live",
                            report=p["report"] or text[-4000:], errors=n, evidence=ev)

    async def _compile_cli_batch(self, session: dict, st: EditorState, consent: dict | None, source: str,
                                 cancel: asyncio.Event | None, *, root: Path | None = None) -> BridgeResult:
        """root: where Unity runs (default the session's project; a clone for use_clone)."""
        root = root or Path(session["folder"]).expanduser().resolve()
        cli = await self._cli_info()
        cfg = self.cfg()
        editor, problem = await self._editor_arg(root, cli)
        if problem:
            return BridgeResult("skipped", problem, "cli_batch", evidence={"route": "cli_batch"})
        t = min(uc.cfg_int(cfg, "batch_timeout_s", 30, 4 * 3600), 4 * 3600)
        logp = self._paths(root, "compile")
        args = (["-nographics"] if cfg.get("nographics", True) else []) + [str(a) for a in cfg.get("extra_editor_args") or []]
        argv = uc.argv_run_batch(cli, root, logp, t, args, editor_path=editor)
        if why := await self.ensure_allowed(session, "compile", "compile", route="cli_batch", argv=argv, consent=consent):
            return BridgeResult("skipped", f"batch compile didn't run: {why}", "cli_batch", evidence={"cmd": shlex.join(argv)})
        run = await self.runner.run(session, argv, project=root, label="Unity compile · CLI batch", timeout_s=t,
                                    log_path=logp, cancel=cancel)
        r = uc.result_from_run_compile(run)
        r.evidence.update({"started_at": run.started_at, "job_id": run.job_id})
        return r

    async def _mcp(self, session: dict, tool: str, args: dict, consent: dict | None, timeout: float) -> tuple[bool, str]:
        """(ok, raw text) of one unity MCP tool call under the hook context."""
        from .mcp_feature import tool_name

        ctx = hook_context(self.app, session, consent=consent)
        out = await asyncio.wait_for(self.app.mcp.call(ctx, tool_name(UNITY_SERVER, tool), args), timeout)
        return not out.is_error, unwrap_untrusted(out.text)

    async def _compile_mcp(self, session: dict, consent: dict | None) -> BridgeResult:
        t = self.gate_timeout()
        ev: dict[str, Any] = {"mode": "mcp", "started_at": time.time()}
        try:
            await self._mcp(session, "read_console", {"action": "clear"}, consent, 30)
            ok, text = await self._mcp(session, "refresh_unity", {"mode": "force", "scope": "all", "compile": "request",
                                                                 "wait_for_ready": True}, consent, t)
            if not ok:
                hint = STALE_HINT if "stale" in text.lower() or "throttl" in text.lower() else ""
                return BridgeResult("skipped", f"refresh_unity failed: {text[:300]}. {hint}".strip(), "mcp",
                                    evidence=ev)
            entries: list = []
            cursor: Any = "0"
            for _ in range(MAX_CONSOLE_PAGES):
                ok, text = await self._mcp(session, "read_console", {
                    "action": "get", "types": ["error"], "format": "json", "include_stacktrace": False,
                    "page_size": "200", "cursor": str(cursor)}, consent, 60)
                if not ok:
                    return BridgeResult("skipped", f"read_console failed: {text[:300]}", "mcp", evidence=ev)
                obj = _json(text)
                if obj is None:
                    return BridgeResult("skipped", "read_console returned no JSON", "mcp", evidence=ev)
                entries += _entries(obj)
                cursor = _find(obj, "nextCursor", "next_cursor")
                if cursor in (None, "", 0, "0"):
                    break
        except asyncio.TimeoutError:
            return BridgeResult("skipped", f"Unity didn't finish compiling within {t}s. {STALE_HINT}", "mcp",
                                evidence={**ev, "timeout_s": t})
        p = parse_compile_output("", console_json={"data": entries})
        ev.update({"errors": p["errors"], "root_causes": p["root_causes"], "console_entries": len(entries)})
        if p["errors"]:
            return BridgeResult("fail", f"{p['errors']} compile error{'s' if p['errors'] != 1 else ''} "
                                        f"({p['root_causes']} root cause{'s' if p['root_causes'] != 1 else ''})",
                                "mcp", report=p["report"], errors=p["errors"], evidence=ev)
        return BridgeResult("pass", "0 compile errors", "mcp", evidence=ev)

    async def _run(self, session: dict, cmd: str, consent: dict | None) -> tuple[int | None, str, str, str]:
        """Run a command line as a run_command job under the hook context.
        (exit code or None when it didn't run, output, RESULT line, refusal text)."""
        ctx = hook_context(self.app, session, consent=consent)
        out = await self.app.tools.run(ctx, "run_command", {"command": cmd, "timeout_s": self.batch_timeout()})
        code, body, res = _cmd_result(out.text)
        return code, body, res, ("" if code is not None else out.text)

    async def _raw(self, session: dict, op: str, args: list[str], consent: dict | None, *, source: str,
                   key: str, label: str, timeout_s: int | None = None, cancel: asyncio.Event | None = None,
                   root: Path | None = None, detail: str = "") -> tuple[int | None, str, str, str, float]:
        """Run `bash unity.sh <args> --project P`. Gates: as a run_command job under the hook context
        (consent = the exact command line, as before). The unity tool: after a `unity` approval, as a
        Unity job (Plan only mode may run compile/test). (code, output, RESULT line, refusal, started).
        root: where Unity runs (default the session's project; a clone for a run on a copy)."""
        root = root or Path(session["folder"]).expanduser().resolve()
        sh = self.unity_sh()
        assert sh
        argv = ["bash", str(sh), *args, "--project", str(root)]
        cmd = " ".join(shlex.quote(p) for p in argv)
        t0 = time.time()
        if source == "gate":
            code, body, res, refused = await self._run(session, cmd, consent)
            return code, body, res, refused, t0
        if why := await self.ensure_allowed(session, op, key, route="raw_batch", argv=argv, consent=consent,
                                            detail=detail):
            return None, "", "", why, t0
        t = timeout_s or self.batch_timeout()
        from ..services import default_shell  # the login shell, as run_command (the user's UNITY_PATH etc.)

        run = await self.runner.run(session, [default_shell(), "-lc", cmd], project=root, label=label, timeout_s=t,
                                    grace_s=0, cancel=cancel, merge=True)
        if run.exit_code is None:
            return None, run.stderr_tail, "", "cancelled" if run.cancelled else (run.error or "didn't run"), run.started_at
        body = run.stderr_tail
        res = _RESULT.findall(body)
        return run.exit_code, body, (f"RESULT: {res[-1][0]} {res[-1][1]}".strip() if res else ""), "", run.started_at

    async def _compile_batch(self, session: dict, consent: dict | None, *, source: str = "gate", force: bool = False,
                             cancel: asyncio.Event | None = None) -> BridgeResult:
        root = Path(session["folder"]).expanduser().resolve()
        cmd = self.command(root, "compile")
        assert cmd
        args = ["compile"] + (["--force"] if force else [])
        code, body, res, refused, t0 = await self._raw(session, "compile", args, consent, source=source, key="compile",
                                                       label="Unity compile · unity.sh", cancel=cancel)
        ev: dict[str, Any] = {"mode": "raw_batch", "route": "raw_batch", "command": cmd, "exit_code": code,
                              "result": res, "started_at": t0}
        mode = "raw_batch"
        if code is None:
            return BridgeResult("skipped", f"batchmode compile didn't run: {refused[:300]}", mode, evidence=ev)
        if code == 0:
            return BridgeResult("pass", "0 compile errors" + (f" ({res[len('RESULT: OK '):]})" if res else ""),
                                mode, evidence=ev)
        if code == 4:
            return BridgeResult("skipped", "Unity has this project open (unity.sh refused batchmode) and the MCP "
                                           "bridge isn't reachable. Start MCP for Unity in the editor.", mode,
                                evidence=ev)
        if code == 124:
            return BridgeResult("skipped", f"batchmode compile timed out after {self.batch_timeout()}s", mode,
                                evidence=ev)
        if code == 3:
            return BridgeResult("skipped", f"Unity batchmode isn't set up: {res or body[-300:]}", mode, evidence=ev)
        p = parse_compile_output(body)
        if p["errors"] or "compile-errors" in res:
            n = p["errors"] or 1
            ev.update({"errors": n, "root_causes": p["root_causes"]})
            return BridgeResult("fail", f"{n} compile error{'s' if n != 1 else ''} ({p['root_causes']} root "
                                        f"cause{'s' if p['root_causes'] != 1 else ''})", mode,
                                report=p["report"] or body[-4000:], errors=n, evidence=ev)
        return BridgeResult("error", f"Unity batchmode failed without compile errors: {res or f'exit {code}'}",
                            mode, report=body[-2000:], evidence=ev)

    # ------------------------------------------------------------ tests

    async def run_tests(self, session: dict, platform: str = "editmode", *, category: str | None = None,
                        test_filter: str | None = None, consent: dict[str, set[str]] | None = None,
                        assemblies: str | None = None, source: str = "gate",
                        cancel: asyncio.Event | None = None) -> BridgeResult:
        st = await self.editor_state(session, "test", wait=True)
        if st.mode == "mcp":
            return await self._tests_mcp(session, platform, category, test_filter, consent)
        if st.extra.get("clone"):
            return await self._on_clone(session, lambda r: self._tests_cli_batch(
                session, platform, category, test_filter, assemblies, consent, source, cancel, root=r))
        if st.mode == "raw_batch":
            return await self._tests_batch(session, platform, category, test_filter, consent, source=source,
                                           cancel=cancel)
        if st.mode == "cli_batch":
            return await self._tests_cli_batch(session, platform, category, test_filter, assemblies, consent, source,
                                               cancel)
        if st.mode == "cli_live":
            return await self._tests_live(session, platform, category, test_filter, assemblies, consent, cancel)
        if st.live.get("state") == "safe_mode":
            return BridgeResult("skipped", "Unity is in Safe Mode (compile errors at boot): tests can't run until it "
                                           "compiles", "cli_live", evidence={"state": st.to_dict()})
        return self._skip(st)

    async def _tests_cli_batch(self, session: dict, platform: str, category: str | None, test_filter: str | None,
                               assemblies: str | None, consent: dict | None, source: str,
                               cancel: asyncio.Event | None, *, root: Path | None = None) -> BridgeResult:
        root = root or Path(session["folder"]).expanduser().resolve()
        cli = await self._cli_info()
        cfg = self.cfg()
        editor, problem = await self._editor_arg(root, cli)
        if problem:
            return BridgeResult("skipped", problem, "cli_batch", evidence={"route": "cli_batch"})
        t = uc.cfg_int(cfg, "test_timeout_s", 30, 4 * 3600)
        mode = TEST_PLATFORMS.get(platform.lower(), "EditMode")
        xml = self._paths(root, f"tests-{mode.lower()}", "xml")
        try:
            argv = uc.argv_test_batch(cli, root, platform, xml, t, test_filter=test_filter, category=category,
                                      assemblies=assemblies, nographics=bool(cfg.get("nographics", True)),
                                      editor_path=editor)
        except ValueError as e:
            return BridgeResult("error", str(e), "cli_batch")
        key = self.op_key("test", platform)
        if why := await self.ensure_allowed(session, "test", key, route="cli_batch", argv=argv, consent=consent):
            return BridgeResult("skipped", f"batch tests didn't run: {why}", "cli_batch", evidence={"cmd": shlex.join(argv)})
        run = await self.runner.run(session, argv, project=root, label=f"Unity tests · {mode} · CLI batch",
                                    timeout_s=t, log_path=xml.with_suffix(".log"), cancel=cancel)
        r = uc.result_from_test_batch(run, xml, platform)
        r.evidence.update({"started_at": run.started_at, "job_id": run.job_id, "category": category,
                           "filter": test_filter, "assemblies": assemblies})
        return r

    async def live_test_command(self, cli: uc.UnityCliInfo, root: Path) -> str:
        """The live Editor's test command: `run_tests` (Pipeline 1.0 docs) or `test run` (0.10)."""
        hit = self._test_cmd.get(str(root))
        if hit and time.monotonic() - hit[0] < 300:
            return hit[1]
        run = await self.runner.quick(uc.argv_command_list(cli, root, "test"), cwd=root, timeout_s=30)
        name = uc.find_command(run.data, "run_tests", "test run", "tests run") or "run_tests"
        self._test_cmd[str(root)] = (time.monotonic(), name)
        return name

    async def _tests_live(self, session: dict, platform: str, category: str | None, test_filter: str | None,
                          assemblies: str | None, consent: dict | None, cancel: asyncio.Event | None) -> BridgeResult:
        root = Path(session["folder"]).expanduser().resolve()
        cli = await self._cli_info()
        t = uc.cfg_int(self.cfg(), "live_test_timeout_s", 30, 4 * 3600)
        name = await self.live_test_command(cli, root)
        mode = TEST_PLATFORMS.get(platform.lower(), "EditMode")
        params: dict[str, Any] = {"mode": mode.lower()}
        if category:
            params.update({"filter": category, "filter-type": "category"})
        elif assemblies:
            params.update({"filter": assemblies, "filter-type": "assembly"})
        elif test_filter:
            params.update({"filter": test_filter})
        params["timeout"] = t
        argv = uc.argv_command(cli, root, name, params, timeout_s=60, detach=True)
        key = self.op_key("test", platform)
        if why := await self.ensure_allowed(session, "test", key, route="cli_live", argv=argv, consent=consent):
            return BridgeResult("skipped", f"live tests didn't run: {why}", "cli_live", evidence={"cmd": shlex.join(argv)})
        async with self.runner.lock(root):
            start = await self.runner.run(session, argv, project=root, label=f"Unity tests · {mode} · CLI live",
                                          timeout_s=60, locked=False, cancel=cancel, sweep=False)
            job = _find(start.data, "jobId", "job_id", "jobid", "id") if start.exit_code == 0 else None
            if not job:
                if start.exit_code == 0 and start.data is not None:  # ran synchronously
                    r = uc.result_from_job(start, platform)
                else:
                    r = BridgeResult("skipped", f"live tests didn't start: {start.error_message()[:300] or start.error or f'exit {start.exit_code}'}",
                                     "cli_live", evidence={"cmd": start.cmd, "exit_code": start.exit_code})
                r.evidence["started_at"] = start.started_at
                return r
            wait = uc.argv_job(cli, root, "wait", str(job), t)
            finished = False
            try:
                run = await self.runner.run(session, wait, project=root, label=f"Unity tests · {mode} · waiting",
                                            timeout_s=t, locked=False, cancel=cancel, sweep=False)
                finished = not (run.cancelled or run.timed_out or run.exit_code is None)
            finally:
                if not finished:  # stop the Editor's detached test job too (also on a turn cancel)
                    await asyncio.shield(self.runner.quick(uc.argv_job(cli, root, "cancel", str(job)), cwd=root,
                                                           timeout_s=30))
        r = uc.result_from_job(run, platform)
        r.evidence.update({"started_at": start.started_at, "job": str(job), "command": name, "category": category,
                           "filter": test_filter})
        return r

    async def _tests_mcp(self, session: dict, platform: str, category: str | None, test_filter: str | None,
                         consent: dict | None) -> BridgeResult:
        plat = TEST_PLATFORMS.get(platform.lower(), "EditMode")
        args: dict[str, Any] = {"mode": plat, "include_failed_tests": True}
        if category:
            args["category_names"] = [category]
        if test_filter:
            args["test_names"] = [test_filter]
        ev: dict[str, Any] = {"mode": "mcp", "platform": plat, "category": category, "filter": test_filter,
                              "started_at": time.time()}
        deadline = time.monotonic() + max(self.gate_timeout(), 60)
        try:
            ok, text = await self._mcp(session, "run_tests", args, consent, 60)
            obj = _json(text)
            job = _find(obj, "job_id", "jobId") if obj is not None else None
            if not ok or not job:
                return BridgeResult("skipped", f"run_tests didn't start: {text[:300]}", "mcp", evidence=ev)
            while True:
                ok, text = await self._mcp(session, "get_test_job", {"job_id": str(job), "wait_timeout": 30,
                                                                   "include_failed_tests": True}, consent, 60)
                obj = _json(text)
                status = str(_find(obj, "status") or "").lower() if obj is not None else ""
                if not ok or obj is None:
                    return BridgeResult("skipped", f"get_test_job failed: {text[:300]}", "mcp", evidence=ev)
                if status not in ("running", "pending", "queued", "started", "in_progress"):
                    break
                if time.monotonic() > deadline:
                    return BridgeResult("skipped", "tests didn't finish in time (a partial run never counts)",
                                        "mcp", evidence=ev)
        except asyncio.TimeoutError:
            return BridgeResult("skipped", f"Unity didn't answer in time. {STALE_HINT}", "mcp", evidence=ev)
        return self._test_summary(obj, "mcp", ev)

    def _test_summary(self, obj: Any, mode: str, ev: dict) -> BridgeResult:
        total = _int(_find(obj, "total", "testCount", "total_tests"))
        passed = _int(_find(obj, "passed", "passCount", "passed_tests"))
        failed = _int(_find(obj, "failed", "failCount", "failed_count"))
        if failed is None and isinstance(_find(obj, "failures", "failed_tests", "failedTests"), list):
            failed = len(_find(obj, "failures", "failed_tests", "failedTests"))
        fails = _find(obj, "failures", "failed_tests", "failedTests")
        names = [str(f.get("fullName") or f.get("name") or f) if isinstance(f, dict) else str(f)
                 for f in (fails if isinstance(fails, list) else [])][:30]
        msgs = [f"FAILED {str(f.get('fullName') or f.get('name') or '?')} :: {str(f.get('message') or '')[:300]}"
                for f in (fails if isinstance(fails, list) else []) if isinstance(f, dict)][:30]
        ev.update({"total": total, "passed": passed, "failed": failed, "failed_names": names})
        if failed:
            return BridgeResult("fail", f"{failed} failing test{'s' if failed != 1 else ''}"
                                        + (f" of {total}" if total else ""), mode,
                                report="\n".join(msgs or names), errors=failed, evidence=ev)
        if not total and not passed:
            return BridgeResult("skipped", "no tests ran (an empty run never counts as a pass)", mode, evidence=ev)
        return BridgeResult("pass", f"{passed if passed is not None else total} tests passed", mode, evidence=ev)

    async def _tests_batch(self, session: dict, platform: str, category: str | None, test_filter: str | None,
                           consent: dict | None, *, source: str = "gate",
                           cancel: asyncio.Event | None = None) -> BridgeResult:
        root = Path(session["folder"]).expanduser().resolve()
        cmd = self.command(root, "test", platform=platform, category=category, test_filter=test_filter)
        assert cmd
        args = ["test", TEST_PLATFORMS.get(platform.lower(), "EditMode").lower()]
        if category:
            args += ["--category", category]
        if test_filter:
            args += ["--filter", test_filter]
        code, body, res, refused, t0 = await self._raw(session, "test", args, consent, source=source,
                                                       key=self.op_key("test", platform),
                                                       label="Unity tests · unity.sh", cancel=cancel)
        mode = "raw_batch"
        ev: dict[str, Any] = {"mode": mode, "route": mode, "command": cmd, "exit_code": code, "result": res,
                              "platform": TEST_PLATFORMS.get(platform.lower(), "EditMode"), "started_at": t0}
        if code is None:
            return BridgeResult("skipped", f"batchmode tests didn't run: {refused[:300]}", mode, evidence=ev)
        if code in (3, 4, 124):
            why = {3: "Unity batchmode isn't set up", 4: "Unity has this project open and MCP isn't reachable",
                   124: "the test run timed out"}[code]
            return BridgeResult("skipped", f"{why}: {res}".strip(": "), mode, evidence=ev)
        counts = {k: _int(v) for k, v in re.findall(r"\b(total|passed|failed|skipped)=(\d+)", body)}
        ev.update(counts)
        fails = [ln.strip() for ln in body.splitlines() if ln.startswith("FAILED ")][:30]
        ev["failed_names"] = [f[len("FAILED "):].split(" :: ")[0] for f in fails]
        if m := re.search(r"\(xml ([^)]+)\)", res):
            ev["xml"] = m.group(1).strip()
        if code == 0 and (counts.get("total") or counts.get("passed")):
            return BridgeResult("pass", f"{counts.get('passed', counts.get('total'))} tests passed", mode,
                                evidence=ev)
        if code == 2:
            n = counts.get("failed") or len(fails) or 1
            return BridgeResult("fail", f"{n} failing test{'s' if n != 1 else ''}"
                                        + (f" of {counts['total']}" if counts.get("total") else ""), mode,
                                report="\n".join(fails) or body[-3000:], errors=n, evidence=ev)
        p = parse_compile_output(body)
        if p["errors"]:
            return BridgeResult("fail", f"tests can't run: {p['errors']} compile errors", mode,
                                report=p["report"], errors=p["errors"], evidence=ev)
        return BridgeResult("skipped" if code == 0 else "error", f"no usable test results ({res or f'exit {code}'})",
                            mode, report=body[-2000:], evidence=ev)

    # ------------------------------------------------------------ other ops (the unity tool)

    async def _route(self, session: dict, op: str) -> tuple[EditorState, Path]:
        st = await self.editor_state(session, op, wait=True)
        return st, Path(session["folder"]).expanduser().resolve()

    async def build(self, session: dict, *, profile: str | None = None, target: str | None = None,
                    out: str | None = None, dev: bool = False, consent: dict | None = None,
                    cancel: asyncio.Event | None = None) -> BridgeResult:
        if not (profile or target):
            return BridgeResult("error", "build needs `profile` (a Build Profile asset or name) or `target`")
        st, root = await self._route(session, "build")
        if st.mode == "unavailable":
            return self._skip(st)
        cfg = self.cfg()
        t = uc.cfg_int(cfg, "build_timeout_s", 60, 6 * 3600)
        out_p = Path(out).expanduser() if out else root / "Builds" / (profile or target or "build").replace("/", "_")
        if not out_p.is_absolute():
            out_p = root / out_p
        if st.mode == "cli_batch" and not dev:
            cli = await self._cli_info()
            editor, problem = await self._editor_arg(root, cli)
            if problem:
                return BridgeResult("skipped", problem, "cli_batch")
            logp = self._paths(root, "build")
            try:
                argv = uc.argv_build(cli, root, profile=profile, target=target, out=out_p, log=logp, timeout_s=t,
                                     editor_path=editor)
            except ValueError as e:
                return BridgeResult("error", str(e), "cli_batch")
            if why := await self.ensure_allowed(session, "build", "build", route="cli_batch", argv=argv, consent=consent):
                return BridgeResult("skipped", why, "cli_batch")
            run = await self.runner.run(session, argv, project=root, label=f"Unity build · {profile or target}",
                                        timeout_s=t, log_path=logp, cancel=cancel)
            r = uc.result_from_build(run)
            r.evidence["started_at"] = run.started_at
            return r
        if nh := await self._needs_harness(root, "a development build" if dev else "a batch build through unity.sh",
                                           st.mode):
            return nh
        if not self.unity_sh():
            return BridgeResult("skipped", "a development build needs headless-ops unity.sh (HarnessCli)", st.mode)
        args = ["build", str(profile or target), "--out", str(out_p)] + (["--dev"] if dev else [])
        code, body, res, refused, t0 = await self._raw(session, "build", args, consent, source="tool", key="build",
                                                       label=f"Unity build · {profile or target} · unity.sh",
                                                       timeout_s=t, cancel=cancel)
        return _raw_result("build", code, body, res, refused, t0)

    async def exec_method(self, session: dict, method: str, args: list[str] | None = None, *, no_quit: bool = False,
                          consent: dict | None = None, cancel: asyncio.Event | None = None) -> BridgeResult:
        if not re.fullmatch(r"[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+", method or ""):
            return BridgeResult("error", "method must be a static method's full name, e.g. Ns.Class.Method")
        args = [str(a) for a in args or []]
        st, root = await self._route(session, "exec")
        if st.mode == "unavailable":
            return self._skip(st)
        t = uc.cfg_int(self.cfg(), "batch_timeout_s", 30, 4 * 3600)
        harness = method.startswith("Harness.")
        if st.mode == "cli_batch" and not no_quit and not harness:
            cli = await self._cli_info()
            editor, problem = await self._editor_arg(root, cli)
            if problem:
                return BridgeResult("skipped", problem, "cli_batch")
            logp = self._paths(root, "exec")
            try:
                argv = uc.argv_run_batch(cli, root, logp, t, ["-executeMethod", method, *args], editor_path=editor)
            except ValueError as e:
                return BridgeResult("error", str(e), "cli_batch")
            if why := await self.ensure_allowed(session, "exec", "exec", route="cli_batch", argv=argv, consent=consent):
                return BridgeResult("skipped", why, "cli_batch")
            run = await self.runner.run(session, argv, project=root, label=f"Unity exec · {method}", timeout_s=t,
                                        log_path=logp, cancel=cancel)
            text = run.log_text()
            ev = {"route": "cli_batch", "exit_code": run.exit_code, "cmd": run.cmd, "log": str(logp),
                  "started_at": run.started_at}
            if run.exit_code == 0:
                return BridgeResult("pass", f"{method} finished (exit 0)", "cli_batch", report=text[-3000:], evidence=ev)
            if run.timed_out or run.cancelled:
                return BridgeResult("skipped", f"{method} {'was cancelled' if run.cancelled else 'timed out'}",
                                    "cli_batch", evidence=ev)
            return BridgeResult("fail", f"{method} failed (exit {run.exit_code})", "cli_batch", report=text[-4000:],
                                evidence=ev)
        if method.startswith(HARNESS_METHOD) and (nh := await self._needs_harness(root, f"`{method}`", st.mode)):
            return nh
        if not self.unity_sh():
            return BridgeResult("skipped", "headless-ops unity.sh not found", st.mode)
        a = ["exec", method, *(["--no-quit"] if no_quit else [])] + (["--", *args] if args else [])
        code, body, res, refused, t0 = await self._raw(session, "exec", a, consent, source="tool", key="exec",
                                                       label=f"Unity exec · {method} · unity.sh", timeout_s=t,
                                                       cancel=cancel)
        return _raw_result("exec", code, body, res, refused, t0)

    async def import_assets(self, session: dict, paths: list[str] | None = None, *, force: bool = False,
                            consent: dict | None = None, cancel: asyncio.Event | None = None) -> BridgeResult:
        st, root = await self._route(session, "import")
        if st.mode == "unavailable":
            return self._skip(st)
        if nh := await self._needs_harness(root, "an asset import", st.mode):
            return nh
        paths = [p for p in (paths or []) if p.startswith("Assets/") or p.startswith("Packages/")]
        a = ["import", *paths] + (["--force"] if force else [])
        code, body, res, refused, t0 = await self._raw(session, "import", a, consent, source="tool", key="import",
                                                       label="Unity import · unity.sh", cancel=cancel)
        return _raw_result("import", code, body, res, refused, t0)

    async def menu_item(self, session: dict, item: str, *, consent: dict | None = None,
                        cancel: asyncio.Event | None = None) -> BridgeResult:
        """Run a menu item: in the live Editor (cli_live: eval of EditorApplication.ExecuteMenuItem,
        shown first), or with the Editor closed through unity.sh `menu` (HarnessCli.MenuItem, then
        AssetDatabase.SaveAssets)."""
        item = (item or "").strip()
        if not item or len(item) > 400 or "/" not in item or any(c in item for c in "\r\n\0") or item.startswith("-"):
            return BridgeResult("error", "menu needs a menu item path, e.g. \"Tools/Rebuild Atlas\"")
        st, root = await self._route(session, "menu")
        if st.mode == "cli_live":
            return await self.eval(session, f"UnityEditor.EditorApplication.ExecuteMenuItem({json.dumps(item)});",
                                   consent=consent)
        if st.mode != "raw_batch":
            return self._skip(st) if st.mode == "unavailable" else BridgeResult(
                "skipped", f"menu items run in the live Editor or in batch (now {st.mode})", st.mode)
        if nh := await self._needs_harness(root, "a menu item in batch mode", st.mode, min_version=2):
            return nh
        if not self.unity_sh():
            return BridgeResult("skipped", "headless-ops unity.sh not found", st.mode)
        code, body, res, refused, t0 = await self._raw(session, "menu", ["menu", item], consent, source="tool", key="menu",
                                                       label=f"Unity menu · {item} · unity.sh", cancel=cancel)
        return _raw_result("menu", code, body, res, refused, t0)

    async def editor_command(self, session: dict, name: str, params: dict | None = None, *,
                             consent: dict | None = None, timeout_s: int | None = None, op: str = "command",
                             key: str | None = None, code: str | None = None, label: str | None = None,
                             cancel: asyncio.Event | None = None) -> BridgeResult:
        """Run a Pipeline command in the live Editor (cli_live only)."""
        st, root = await self._route(session, "command")
        if st.mode != "cli_live":
            if st.live.get("state") == "safe_mode":
                return BridgeResult("skipped", "Unity is in Safe Mode: no live commands until it compiles", "cli_live")
            return self._skip(st) if st.mode == "unavailable" else BridgeResult(
                "skipped", f"`{name}` needs the Unity CLI live route (the Editor open with com.unity.pipeline); "
                           f"now: {st.mode}", st.mode, evidence={"state": st.to_dict()})
        cli = await self._cli_info()
        t = timeout_s or uc.cfg_int(self.cfg(), "live_timeout_s", 10, 3600)
        try:
            argv = uc.argv_command(cli, root, name, params or {}, timeout_s=t)
        except ValueError as e:
            return BridgeResult("error", str(e), "cli_live")
        k = key or f"command:{name}"
        if why := await self.ensure_allowed(session, op, k, route="cli_live", argv=argv, consent=consent, code=code,
                                            name=name if op == "command" else None):
            return BridgeResult("skipped", why, "cli_live")
        cls = self.op_class(op, name)
        if cls == "read":
            run = await self.runner.quick(argv, cwd=root, timeout_s=t + 15)
        else:
            run = await self.runner.run(session, argv, project=root, label=label or f"Unity {name} · CLI live",
                                        timeout_s=t, cancel=cancel, sweep=False)
        ev = {"route": "cli_live", "exit_code": run.exit_code, "cmd": run.cmd, "error_code": run.error_code(),
              "started_at": run.started_at}
        data = run.data
        report = json.dumps(data, indent=1, default=str)[:20000] if data is not None else run.stderr_tail[-3000:]
        if run.exit_code == 0:
            return BridgeResult("pass", f"{name} ok", "cli_live", report=report, evidence={**ev, "data": data})
        if run.cancelled or run.timed_out:
            return BridgeResult("skipped", f"{name} {'was cancelled' if run.cancelled else 'timed out'}", "cli_live",
                                evidence=ev)
        return BridgeResult("fail", f"{name} failed (exit {run.exit_code}): {run.error_message()[:300]}", "cli_live",
                            report=report, evidence=ev)

    async def eval(self, session: dict, code: str, *, consent: dict | None = None,
                   timeout_s: int | None = None) -> BridgeResult:
        if not (code or "").strip():
            return BridgeResult("error", "eval needs `code`")
        return await self.editor_command(session, "eval", {"code": code}, consent=consent, timeout_s=timeout_s, op="eval",
                                  key="eval", code=code, label="Unity eval · CLI live")

    async def commands(self, session: dict, query: str | None = None) -> BridgeResult:
        st, root = await self._route(session, "command")
        if st.mode != "cli_live":
            return BridgeResult("skipped", st.reason or f"the Pipeline command list needs the live route (now {st.mode})",
                                st.mode)
        cli = await self._cli_info()
        run = await self.runner.quick(uc.argv_command_list(cli, root, query), cwd=root, timeout_s=30)
        if run.exit_code != 0:
            return BridgeResult("fail", f"couldn't list the Editor's commands: {run.error_message()[:300]}", "cli_live")
        return BridgeResult("pass", "Pipeline commands", "cli_live",
                            report=json.dumps(run.data, indent=1, default=str)[:30000])

    async def screenshot(self, session: dict, out: Path, *, consent: dict | None = None,
                         width: int | None = None, height: int | None = None, camera: str | None = None,
                         cam_pos: Any = None, cam_rot: Any = None, fov: float | None = None, scene: str | None = None,
                         view_target: str | None = None, time_of_day: str | None = None, allow_clone: bool = False,
                         ctx: Any = None, cancel: asyncio.Event | None = None) -> BridgeResult:
        """One PNG at `out` on the route the Editor allows now (OP_ROUTES["screenshot"]):
        - mcp: MCP for Unity `manage_camera` action=screenshot (game_view; `camera`, or a temporary camera at
          view_position / view_rotation / view_target that the tool removes again);
        - cli_live: the Pipeline `screenshot` command (the Game view as it is), or, with framing (camera, cam_pos,
          cam_rot, fov, view_target), an eval of a fixed snippet that renders a HideAndDontSave temporary camera
          and destroys it again (the eval card shows the code);
        - cli_batch / raw_batch (the Editor closed): unity.sh `screenshot` → HarnessCli.Screenshot (version 3; opens
          `scene` without saving it; never -nographics). With the Editor open but no live route, `allow_clone` runs it
          on a copy of the project files when [unity].clone_when_open isn't "never" (the card says so).
        MCP uses MCP tool approvals; live framing uses an eval card showing the code; plain live and batch
        use a Unity screenshot card (key "screenshot", "always allow" per project). `ctx` (a tool context)
        makes the MCP call under that context's approvals instead of the hook context.
        evidence: route, screenshot (the file or None), shot (the framing asked for and, from batch, what was used)."""
        session = self.app.store.get(session["id"])
        if session is None:
            return BridgeResult("error", "The session no longer exists.")
        if session.get("mode") == "plan":
            return BridgeResult("error", "Plan only mode: further captures are refused.")
        out = Path(out).resolve()
        if out.suffix.lower() != ".png":
            return BridgeResult("error", "screenshot `out` must be a .png path")
        st, root = await self._route(session, "screenshot")
        if not out.is_relative_to(root / SHOT_DIR):
            return BridgeResult("error", f"screenshot `out` must be inside {root / SHOT_DIR}")
        if st.mode == "unavailable" and allow_clone and st.editor_open:
            alt = await self.editor_state(session, "screenshot", force_route="clone")
            if alt.extra.get("clone"):
                st = alt
        if st.mode == "unavailable":
            return self._skip(st)
        if st.mode == "mcp" and not self._has_shot_mcp():
            return BridgeResult("skipped", "The connected Unity MCP server doesn't expose manage_camera.", "mcp")
        if st.live.get("state") == "safe_mode" and st.mode == "cli_live":
            return BridgeResult("skipped", "Unity is in Safe Mode: no live commands until it compiles", "cli_live")
        try:
            width, height = _shot_size(width, 1920), _shot_size(height, 1080)
        except (TypeError, ValueError, OverflowError):
            return BridgeResult("error", "Screenshot width and height must be integers.", st.mode)
        shot = {k: v for k, v in {"camera": camera, "cam_pos": cam_pos, "cam_rot": cam_rot, "fov": fov, "scene": scene,
                                  "view_target": view_target, "width": width, "height": height,
                                  "time_of_day": time_of_day}.items() if v not in (None, "")}
        out.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        if st.mode == "mcp":
            r = await self._shot_mcp(session, root, out, shot, consent, ctx, t0)
        elif st.mode == "cli_live":
            framed = any(k in shot for k in ("camera", "cam_pos", "cam_rot", "fov", "view_target"))
            r = await (self._shot_live_framed(session, out, shot, consent) if framed else
                       self._shot_live(session, root, out, width, height, consent))
        else:
            r = await self._shot_batch(session, st, root, out, shot, consent, cancel)
        r.mode = r.mode or st.mode
        r.evidence.setdefault("route", st.mode)
        r.evidence["screenshot"] = str(out) if out.is_file() and out.stat().st_mtime >= t0 - 1 else None
        r.evidence["shot"] = {**shot, **(r.evidence.get("shot") or {})}
        r.evidence.setdefault("started_at", t0)
        if r.status == "pass" and not r.evidence["screenshot"]:
            r.status, r.summary = "fail", f"{r.summary}; but no image was written to {out}"
        return r

    async def screenshot_route(self, session: dict) -> tuple[EditorState, BridgeResult | None]:
        """The route a screenshot would take now, and why it can't run (None when it can): with the Editor open and
        no live route, a copy of the project when [unity].clone_when_open allows it (ask or always); a batch route
        needs HarnessCli version 3 (a needs_harness result). Probes only: nothing runs, nothing asks."""
        st = await self.editor_state(session, "screenshot", wait=True)
        if st.mode == "mcp" and not self._has_shot_mcp():
            return st, BridgeResult("skipped", "The connected Unity MCP server doesn't expose manage_camera.", "mcp")
        if st.mode == "unavailable" and st.editor_open and self.cfg().get("clone_when_open", "ask") != "never":
            alt = await self.editor_state(session, "screenshot", force_route="clone")
            if alt.extra.get("clone"):
                st = alt
        if st.mode == "unavailable":
            return st, BridgeResult("skipped", st.reason or "Unity can't take a screenshot now", "unavailable",
                                    evidence={"route": "unavailable", "actions": list(st.actions), "state": st.to_dict()})
        if st.mode in ("cli_batch", "raw_batch"):
            root = Path(session["folder"]).expanduser().resolve()
            if nh := await self._needs_harness(root, "a batch screenshot (HarnessCli.Screenshot)", st.mode,
                                               min_version=SHOT_HARNESS_VERSION):
                return st, nh
            if not self.unity_sh():
                return st, BridgeResult("skipped", "headless-ops unity.sh not found", st.mode, evidence={"route": st.mode})
        return st, None

    def _has_shot_mcp(self) -> bool:
        mgr = self.app.mcp
        conn = getattr(mgr, "conns", {}).get(UNITY_SERVER)
        return bool(conn and any(t.name == MCP_SHOT_TOOL for t in (conn.tools or [])))

    async def _shot_live(self, session: dict, root: Path, out: Path, width: int | None, height: int | None,
                         consent: dict | None) -> BridgeResult:
        cli = await self._cli_info()
        listing = await self.runner.quick(uc.argv_command_list(cli, root, "screenshot"), cwd=root, timeout_s=30)
        name = uc.find_command(listing.data, "screenshot")
        if not name:
            listing2 = await self.runner.quick(uc.argv_command_list(cli, root, "capture"), cwd=root, timeout_s=30)
            name = uc.find_command(listing2.data, "capture_game_view") or "screenshot"
        params: dict[str, Any] = {"output": str(out)} if name == "screenshot" else {"source": "screen", "save_path": str(out)}
        if name == "screenshot":
            params["width"] = _shot_size(width, 1920)
            params["height"] = _shot_size(height, 1080)
        return await self.editor_command(session, name, params, consent=consent, op="screenshot", key="screenshot",
                                         label="Unity screenshot · CLI live")

    async def _shot_live_framed(self, session: dict, out: Path, shot: dict, consent: dict | None) -> BridgeResult:
        try:
            code = live_shot_code(out, **{k: shot.get(k) for k in ("width", "height", "camera", "cam_pos", "cam_rot",
                                                                   "fov", "view_target")})
        except ValueError as e:
            return BridgeResult("error", str(e), "cli_live")
        return await self.editor_command(session, "eval", {"code": code}, consent=consent, op="eval", key="eval",
                                         code=code, label="Unity screenshot (temporary camera) · CLI live")

    async def _mcp_out(self, session: dict, tool: str, args: dict, consent: dict | None, timeout: float,
                       ctx: Any = None) -> Any:
        """The whole ToolOutput (text and images) of one unity MCP tool call, under `ctx` or the hook context."""
        from .mcp_feature import tool_name
        from ..agent.tools import ToolOutput

        session = self.app.store.get(session["id"])
        if session is None:
            return ToolOutput("The session no longer exists.", is_error=True)
        if session.get("mode") == "plan" and tool in (MCP_SHOT_TOOL, "manage_editor"):
            return ToolOutput("Plan only mode: further captures and play are refused.", is_error=True)
        c = replace(ctx, session=session) if ctx else hook_context(self.app, session, consent=consent)
        # MCPManager.call includes the user's approval wait; short execution timeouts must not cut it off.
        timeout = max(timeout, uc.cfg_int(self.cfg(), "screenshot_timeout_s", 60, 4 * 3600))
        return await asyncio.wait_for(self.app.mcp.call(c, tool_name(UNITY_SERVER, tool), args), timeout)

    async def _shot_mcp(self, session: dict, root: Path, out: Path, shot: dict, consent: dict | None, ctx: Any,
                        t0: float) -> BridgeResult:
        if not self._has_shot_mcp():
            return BridgeResult("skipped", "The connected Unity MCP server doesn't expose manage_camera.", "mcp")
        w, h = _shot_size(shot.get("width"), 1920), _shot_size(shot.get("height"), 1080)
        try:
            rel_dir = out.parent.resolve().relative_to(root).as_posix()
        except ValueError:
            return BridgeResult("error", "screenshot `out` must be inside the project on the MCP route", "mcp")
        args: dict[str, Any] = {"action": "screenshot", "capture_source": "game_view", "include_image": True,
                                "max_resolution": max(w, h), "screenshot_file_name": out.stem, "output_folder": rel_dir}
        if shot.get("camera"):
            args["camera"] = str(shot["camera"])
        try:
            if shot.get("cam_pos") is not None:
                args["view_position"] = [float(x) for x in uc.vec_arg(shot["cam_pos"]).split(",")]
            if shot.get("cam_rot") is not None:
                args["view_rotation"] = [float(x) for x in uc.vec_arg(shot["cam_rot"]).split(",")]
        except ValueError as e:
            return BridgeResult("error", str(e), "mcp")
        if shot.get("view_target"):
            args["view_target"] = str(shot["view_target"])
        ev: dict[str, Any] = {"route": "mcp", "tool": f"{UNITY_SERVER}.{MCP_SHOT_TOOL}", "args": args, "started_at": t0}
        if shot.get("fov") is not None:
            ev["note"] = "MCP for Unity's screenshot has no field-of-view parameter; fov was not applied"
        assets = root / "Assets"
        # Snapshot before the call: timestamps alone cannot distinguish pre-existing folders/metas.
        assets_before = await asyncio.to_thread(lambda: set(assets.rglob("*")))
        try:
            res = await self._mcp_out(session, MCP_SHOT_TOOL, args, consent, max(self.gate_timeout(), 120), ctx)
        except asyncio.TimeoutError:
            return BridgeResult("skipped", "MCP for Unity didn't answer the screenshot in time", "mcp", evidence=ev)
        except KeyError:
            return BridgeResult("skipped", "The connected Unity MCP server no longer exposes manage_camera.", "mcp", evidence=ev)
        text = unwrap_untrusted(res.text or "")
        if res.is_error:
            return BridgeResult("fail", f"manage_camera screenshot failed: {text[:300]}", "mcp", report=text[-3000:],
                                evidence=ev)
        found = _find_shot(root, out, text, t0)
        if found in assets_before:
            found = None  # never move an existing asset, even if MCP rewrote its timestamp
        if found and found != out:
            try:
                shutil.move(str(found), str(out))  # our own fresh capture, saved elsewhere by the tool (e.g. Assets/)
                ev["moved_from"] = str(found)
                _cleanup_shot_assets(assets, found, assets_before, t0)
            except OSError as e:
                ev["move_error"] = str(e)
                out = found
        elif not found and res.images:
            try:
                out.write_bytes(res.images[0].load_bytes())  # the inline PNG (include_image) when no file turned up
                ev["from_inline_image"] = True
            except Exception as e:  # noqa: BLE001
                ev["inline_error"] = f"{type(e).__name__}: {e}"[:200]
        ok = out.is_file()
        return BridgeResult("pass" if ok else "fail",
                            f"screenshot saved to {out}" if ok else "manage_camera returned no image file",
                            "mcp", report=text[-3000:], evidence=ev)

    async def _shot_batch(self, session: dict, st: EditorState, root: Path, out: Path, shot: dict,
                          consent: dict | None, cancel: asyncio.Event | None) -> BridgeResult:
        if nh := await self._needs_harness(root, "a batch screenshot (HarnessCli.Screenshot)", st.mode,
                                           min_version=SHOT_HARNESS_VERSION):
            return nh
        if not self.unity_sh():
            return BridgeResult("skipped", "headless-ops unity.sh not found", st.mode)
        try:
            args = uc.sh_screenshot_args(out, width=int(shot.get("width") or 1920), height=int(shot.get("height") or 1080),
                                         scene=shot.get("scene"), camera=shot.get("camera"), cam_pos=shot.get("cam_pos"),
                                         cam_rot=shot.get("cam_rot"), fov=shot.get("fov"),
                                         time_of_day=shot.get("time_of_day"))
        except (TypeError, ValueError) as e:
            return BridgeResult("error", str(e), st.mode)
        t = uc.cfg_int(self.cfg(), "screenshot_timeout_s", 60, 4 * 3600)
        detail = ("Renders one PNG with the Editor closed: opens the scene in batch mode **without saving it**, "
                  f"with a graphics device (no -nographics), and writes only **{out}**.")

        async def run(at: Path) -> BridgeResult:
            note = detail + (f" Runs {uclone.CLONE_NOTE}." if at != root else "")
            code, body, res, refused, t0 = await self._raw(session, "screenshot", args, consent, source="tool",
                                                           key="screenshot", label="Unity screenshot · unity.sh",
                                                           timeout_s=t, cancel=cancel, root=at, detail=note)
            r = _raw_result("screenshot", code, body, res, refused, t0)
            r.mode = st.mode
            r.evidence.update({"route": st.mode, "runner": "unity.sh", "args": args, "shot": _shot_used(res or body)})
            return r

        if st.extra.get("clone"):
            return await self._on_clone(session, run)
        return await run(root)

    async def play(self, session: dict, action: str = "start", *, consent: dict | None = None) -> BridgeResult:
        """start: set_autotick (keeps an unfocused Editor ticking) + editor_play; stop: editor_stop;
        status: editor_status."""
        if action == "status":
            return await self.editor_command(session, "editor_status", {}, consent=consent, op="command")
        if action == "stop":
            return await self.editor_command(session, "editor_stop", {}, consent=consent, op="play", key="play")
        r = await self.editor_command(session, "set_autotick", {}, consent=consent, op="play", key="play")
        if r.status not in ("pass",) and "declined" in r.summary.lower():
            return r
        return await self.editor_command(session, "editor_play", {}, consent=consent, op="play", key="play", timeout_s=60)


def _raw_result(op: str, code: int | None, body: str, res: str, refused: str, t0: float) -> BridgeResult:
    ev = {"route": "raw_batch", "exit_code": code, "result": res, "started_at": t0}
    if code is None:
        return BridgeResult("skipped", f"unity.sh {op} didn't run: {refused[:300]}", "raw_batch", evidence=ev)
    if code == 0:
        return BridgeResult("pass", res or f"{op} ok", "raw_batch", report=body[-3000:], evidence=ev)
    if code in (3, 4, 124):
        why = {3: "Unity batchmode isn't set up", 4: "Unity has this project open", 124: "timed out"}[code]
        return BridgeResult("skipped", f"{why}: {res}".strip(": "), "raw_batch", report=body[-2000:], evidence=ev)
    return BridgeResult("fail", res or f"unity.sh {op} failed (exit {code})", "raw_batch", report=body[-4000:], evidence=ev)


_SHOT_USED = re.compile(r"scene=(?P<scene>\S+).*?pos=(?P<pos>[-\d.,]+) rot=(?P<rot>[-\d.,]+) fov=(?P<fov>[-\d.]+)")


def _shot_size(value: Any, default: int) -> int:
    return max(16, min(int(default if value is None else value), 8192))


def _cleanup_shot_assets(assets: Path, png: Path, before: set[Path], t0: float) -> None:
    """Remove only this new capture's sidecars and newly-created, now-empty asset folders."""
    if not png.is_relative_to(assets) or png in before:
        return

    def remove_meta(path: Path) -> None:
        meta = Path(str(path) + ".meta")
        if meta not in before and not meta.is_symlink() and meta.is_file() and meta.stat().st_ctime >= t0:
            meta.unlink()

    try:
        remove_meta(png)
        parent = png.parent
        while parent != assets and parent.is_relative_to(assets):
            if parent in before or parent.is_symlink() or parent.stat().st_ctime < t0:
                break
            parent.rmdir()  # refuses nonempty folders, including anything another capture is using
            remove_meta(parent)
            parent = parent.parent
    except OSError:
        log.debug("Unity screenshot asset cleanup stopped at an occupied or unavailable path", exc_info=True)


def _shot_used(text: str) -> dict:
    """What HarnessCli.Screenshot reported using (`SHOT OK … scene=… pos=x,y,z rot=x,y,z fov=f`)."""
    lines = [ln for ln in (text or "").splitlines() if "SHOT OK" in ln or ln.startswith("RESULT: OK screenshot")]
    m = _SHOT_USED.search(lines[-1]) if lines else None
    if not m:
        return {}
    vec = lambda v: [float(x) for x in v.split(",")]  # noqa: E731
    try:
        return {"used_scene": m["scene"], "used_pos": vec(m["pos"]), "used_rot": vec(m["rot"]), "used_fov": float(m["fov"])}
    except ValueError:
        return {}


def _find_shot(root: Path, out: Path, text: str, t0: float) -> Path | None:
    """The PNG an MCP screenshot wrote: `out`, a name starting with out's stem in its folder (or the same folder
    under Assets/), or a .png path in the result text; only files inside the project written since t0."""
    cands = [out, *sorted(out.parent.glob(f"{out.stem}*.png"))]
    try:
        rel = out.parent.resolve().relative_to(root)
        alt = root / "Assets" / rel
        cands += sorted(alt.glob(f"{out.stem}*.png")) if alt.is_dir() else []
    except ValueError:
        pass
    for raw in re.findall(r"([A-Za-z0-9_~./\\:-][A-Za-z0-9_ ~./\\:-]*?\.png)\b", text or ""):
        q = Path(raw.strip().strip("'\"")).expanduser()
        cands.append(q if q.is_absolute() else root / q)
    for c in cands:
        try:
            p = c.resolve()
            if p.is_file() and (p == root or root in p.parents) and p.stat().st_mtime >= t0 - 1:
                return p
        except OSError:
            continue
    return None


def _cs(v: Any) -> str:
    """A C# float literal."""
    return uc._num(v) + "f"


def live_shot_code(out: Path, *, width: Any = None, height: Any = None, camera: str | None = None, cam_pos: Any = None,
                   cam_rot: Any = None, fov: Any = None, view_target: str | None = None) -> str:
    """C# for the live Editor (cli_live eval): render a HideAndDontSave temporary camera (settings copied from
    `camera` or Camera.main) into a RenderTexture, write a PNG to `out`, destroy everything again. Nothing in the
    open scene changes or gets dirty. Only numbers and JSON-quoted strings are interpolated."""
    w, h = _shot_size(width, 1920), _shot_size(height, 1080)
    q = json.dumps
    lines = [
        "var __go = UnityEditor.EditorUtility.CreateGameObjectWithHideFlags(\"HarnessScreenshotCamera\", "
        "UnityEngine.HideFlags.HideAndDontSave, typeof(UnityEngine.Camera));",
        f"var __rt = new UnityEngine.RenderTexture({w}, {h}, 24);",
        f"var __tex = new UnityEngine.Texture2D({w}, {h}, UnityEngine.TextureFormat.RGB24, false);",
        "var __prev = UnityEngine.RenderTexture.active;",
        "try {",
        "  var __cam = __go.GetComponent<UnityEngine.Camera>();",
        "  UnityEngine.Camera __src = UnityEngine.Camera.main;",
    ]
    if camera:
        name = str(camera).strip()
        if not name or any(c in name for c in "\r\n\0"):
            raise ValueError(f"bad camera name {camera!r}")
        lines += [
            "  __src = null;",
            "  foreach (var __c in UnityEngine.Object.FindObjectsByType<UnityEngine.Camera>(UnityEngine.FindObjectsInactive.Include, "
            "UnityEngine.FindObjectsSortMode.None))",
            f"    if (string.Equals(__c.name, {q(name)}, System.StringComparison.OrdinalIgnoreCase)) {{ __src = __c; break; }}",
            f"  if (__src == null) throw new System.Exception(\"camera not found: \" + {q(name)});",
        ]
    lines += ["  if (__src != null) { __cam.CopyFrom(__src); __go.transform.SetPositionAndRotation(__src.transform.position, "
              "__src.transform.rotation); }"]
    if cam_pos is not None:
        x, y, z = uc.vec_arg(cam_pos).split(",")
        lines.append(f"  __go.transform.position = new UnityEngine.Vector3({_cs(x)}, {_cs(y)}, {_cs(z)});")
    if cam_rot is not None:
        x, y, z = uc.vec_arg(cam_rot).split(",")
        lines.append(f"  __go.transform.eulerAngles = new UnityEngine.Vector3({_cs(x)}, {_cs(y)}, {_cs(z)});")
    elif view_target:
        t = str(view_target).strip()
        if any(c in t for c in "\r\n\0"):
            raise ValueError(f"bad view_target {view_target!r}")
        lines += [f"  var __t = UnityEngine.GameObject.Find({q(t)});",
                  "  if (__t != null) __go.transform.LookAt(__t.transform);"]
    if fov is not None:
        f = float(fov)
        if not 0.1 < f < 179:
            raise ValueError("fov must be between 0.1 and 179")
        lines.append(f"  __cam.fieldOfView = {_cs(f)};")
    lines += [
        "  __cam.targetTexture = __rt;",
        "  __cam.Render();",
        "  UnityEngine.RenderTexture.active = __rt;",
        f"  __tex.ReadPixels(new UnityEngine.Rect(0, 0, {w}, {h}), 0, 0);",
        "  __tex.Apply();",
        f"  System.IO.Directory.CreateDirectory({q(str(Path(out).parent))});",
        f"  System.IO.File.WriteAllBytes({q(str(out))}, UnityEngine.ImageConversion.EncodeToPNG(__tex));",
        "} finally {",
        "  UnityEngine.RenderTexture.active = __prev;",
        "  UnityEngine.Object.DestroyImmediate(__go);",
        "  __rt.Release(); UnityEngine.Object.DestroyImmediate(__rt);",
        "  UnityEngine.Object.DestroyImmediate(__tex);",
        "}",
    ]
    return "\n".join(lines)


async def editor_has_project(project: Path, *, check_lock: bool = True) -> bool:
    """unity-router's rule: `pgrep -fil "Unity.app/Contents/MacOS/Unity.*-projectpath .*/<Folder>( |$)"`
    (case-insensitive: the Hub spells it -projectpath), then an open Temp/UnityLockfile (lsof)."""
    name = re.sub(r"([][.^$*+?(){}|\\])", r"\\\1", project.name)
    pat = rf"Unity\.app/Contents/MacOS/Unity.*-projectpath[= ].*/{name}/?( |$)"

    async def run(*argv: str) -> str:
        if not shutil.which(argv[0]):
            return ""
        try:
            p = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.DEVNULL, stdin=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(p.communicate(), 5)
            return out.decode(errors="replace").strip()
        except (OSError, asyncio.TimeoutError):
            return ""

    if out := await run("pgrep", "-fil", pat):
        # A batch-mode Unity (ours, on this project) isn't "the Editor has it open" for routing.
        if any("-batchmode" not in ln.lower() for ln in out.splitlines() if ln.strip()):
            return True
    lock = project / "Temp" / "UnityLockfile"
    return check_lock and lock.exists() and bool(await run("lsof", "-t", str(lock)))


def get_bridge(app: "AppState") -> UnityBridge:
    """The app's bridge (tests replace it with a FakeUnityBridge in app.extensions)."""
    b = app.extensions.get("unity_bridge")
    if b is None:
        b = app.extensions["unity_bridge"] = UnityBridge(app)
    return b  # type: ignore[return-value]


class FakeUnityBridge(UnityBridge):
    """For tests: scripted results instead of Unity. `compile` / `tests` (and build / exec /
    eval / command) are lists of BridgeResult (or dicts) consumed in order (the last one repeats);
    calls are recorded as (op, session_id, consent). `route` overrides the mode results report."""

    def __init__(self, app: "AppState", *, compile: list | None = None, tests: list | None = None,
                 state: EditorState | None = None, route: str | None = None, build: list | None = None,
                 exec: list | None = None, eval: list | None = None, command: list | None = None,
                 shots: list | None = None):
        super().__init__(app)
        self._compile = list(compile or [BridgeResult("pass", "0 compile errors", "fake")])
        self._tests = list(tests or [BridgeResult("pass", "1 tests passed", "fake")])
        self._build = list(build or [BridgeResult("pass", "build succeeded", "fake")])
        self._exec = list(exec or [BridgeResult("pass", "exec ok", "fake")])
        self._eval = list(eval or [BridgeResult("pass", "eval ok", "fake")])
        self._command = list(command or [BridgeResult("pass", "command ok", "fake")])
        # screenshot: a "pass" result writes a small PNG at `out` (evidence.screenshot), like a real capture.
        self._shots = list(shots or [BridgeResult("pass", "screenshot ok", "fake")])
        self.shot_calls: list[dict] = []
        self.state = state or EditorState("mcp", True, True, True)
        self.route = route
        self.calls: list[tuple[str, str, dict | None]] = []

    def _next(self, q: list) -> BridgeResult:
        r = q.pop(0) if len(q) > 1 else q[0]
        r = r if isinstance(r, BridgeResult) else BridgeResult(**r)
        if self.route:
            r = BridgeResult(r.status, r.summary, self.route, r.report, r.errors, dict(r.evidence))
        return r

    def _has_shot_mcp(self) -> bool:
        return self.state.mode == "mcp"  # the scripted fake supplies screenshots without a real MCP connection

    async def editor_state(self, session: dict, op: str = "compile", *, wait: bool = False,
                           force_route: str | None = None, memo: dict | None = None) -> EditorState:
        return self.state

    async def compile(self, session: dict, *, consent: dict[str, set[str]] | None = None, force: bool = False,
                      source: str = "gate", cancel: asyncio.Event | None = None,
                      force_route: str | None = None) -> BridgeResult:
        self.calls.append(("compile", session["id"], consent))
        return self._next(self._compile)

    async def run_tests(self, session: dict, platform: str = "editmode", *, category: str | None = None,
                        test_filter: str | None = None, consent: dict[str, set[str]] | None = None,
                        assemblies: str | None = None, source: str = "gate",
                        cancel: asyncio.Event | None = None) -> BridgeResult:
        self.calls.append(("tests", session["id"], consent))
        return self._next(self._tests)

    async def build(self, session: dict, **kw: Any) -> BridgeResult:  # type: ignore[override]
        self.calls.append(("build", session["id"], kw.get("consent")))
        return self._next(self._build)

    async def exec_method(self, session: dict, method: str, args: list[str] | None = None,  # type: ignore[override]
                          **kw: Any) -> BridgeResult:
        self.calls.append(("exec", session["id"], kw.get("consent")))
        return self._next(self._exec)

    async def eval(self, session: dict, code: str, **kw: Any) -> BridgeResult:  # type: ignore[override]
        self.calls.append(("eval", session["id"], kw.get("consent")))
        return self._next(self._eval)

    async def editor_command(self, session: dict, name: str, params: dict | None = None,  # type: ignore[override]
                             **kw: Any) -> BridgeResult:
        self.calls.append(("command", session["id"], kw.get("consent")))
        return self._next(self._command)

    async def screenshot(self, session: dict, out: Path, **kw: Any) -> BridgeResult:  # type: ignore[override]
        self.calls.append(("screenshot", session["id"], kw.get("consent")))
        self.shot_calls.append({"out": str(out), **{k: v for k, v in kw.items() if k not in ("ctx", "cancel")}})
        r = self._next(self._shots)
        r = BridgeResult(r.status, r.summary, r.mode or self.state.mode, r.report, r.errors, dict(r.evidence))
        shot = {k: kw[k] for k in ("camera", "cam_pos", "cam_rot", "fov", "scene", "view_target", "width", "height")
                if kw.get(k) not in (None, "")}
        r.evidence.setdefault("route", r.mode)
        r.evidence["shot"] = {**shot, **(r.evidence.get("shot") or {})}
        if r.status == "pass":
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            r.evidence["screenshot"] = str(out)
        return r


__all__ = ["BACKENDS", "ROUTES", "SHOT_DIR", "BridgeResult", "EditorState", "FakeUnityBridge", "UnityBridge",
           "editor_has_project", "get_bridge", "is_unity_project", "live_shot_code", "load_script", "parse_compile_output",
           "unwrap_untrusted", "UNITY_SERVER"]
