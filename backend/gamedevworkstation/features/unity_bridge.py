"""Unity bridge: how the harness's own gates compile and test a Unity project.

Two paths, chosen per call by editor_state():
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
import importlib.util
import json
import logging
import re
import shlex
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ..skills import builtin_skills_dir
from .hookbus import hook_context

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)

UNITY_SERVER = "unity"  # the MCP for Unity preset's server name ([mcp.presets.unity])
MCP_COMPILE_TOOLS = ("refresh_unity", "read_console")
MCP_TEST_TOOLS = ("run_tests", "get_test_job")
DEFAULT_GATE_TIMEOUT_S = 180     # [hooks] gate_timeout_s: MCP compile wait (focus/throttle) and test polling
DEFAULT_BATCH_TIMEOUT_S = 900    # [hooks] batchmode_timeout_s: a cold batchmode import can take minutes
MAX_CONSOLE_PAGES = 10
TEST_PLATFORMS = {"editmode": "EditMode", "edit": "EditMode", "playmode": "PlayMode", "play": "PlayMode"}

STALE_HINT = ("Unity seems throttled (an unfocused editor compiles slowly): bring the Unity window to "
              "the front, then run the gate again.")


@dataclass
class EditorState:
    """mode: "mcp" | "batchmode" | "unavailable"; reason explains "unavailable"."""

    mode: str
    unity_project: bool = False
    editor_open: bool = False
    mcp_connected: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {"mode": self.mode, "unity_project": self.unity_project, "editor_open": self.editor_open,
                "mcp_connected": self.mcp_connected, "reason": self.reason}


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
    """app.extensions["unity_bridge"] (see get_bridge). Stateless apart from config reads."""

    def __init__(self, app: "AppState", *, editor_open: EditorProbe | None = None):
        self.app = app
        self._editor_open = editor_open

    # ----------------------------------------------------------- config

    def _hooks_cfg(self) -> dict:
        return getattr(self.app.config, "hooks", None) or {}

    def gate_timeout(self) -> int:
        return max(int(self._hooks_cfg().get("gate_timeout_s") or DEFAULT_GATE_TIMEOUT_S), 5)

    def batch_timeout(self) -> int:
        v = self._hooks_cfg().get("batchmode_timeout_s") or max(DEFAULT_BATCH_TIMEOUT_S, self.gate_timeout())
        return min(max(int(v), 30), 1800)

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
        """The exact command line a batchmode gate runs (consent is given for exactly these).
        op: "compile" | "test". None when unity.sh can't be found."""
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

    def consent_for(self, project: Path | str, ops: list[dict] | None = None) -> dict[str, set[str]]:
        """What the Unity gates need consent for in `project`: MCP tools ("unity__<tool>") and the
        exact command lines. ops: [{"op": "compile"} | {"op": "test", "platform", "category",
        "filter"}] (default: compile + EditMode tests)."""
        ops = ops or [{"op": "compile"}, {"op": "test", "platform": "editmode"}]
        tools: set[str] = set()
        cmds: set[str] = set()
        for o in ops:
            tools |= {f"{UNITY_SERVER}__{t}" for t in (MCP_COMPILE_TOOLS if o["op"] == "compile" else MCP_TEST_TOOLS)}
            if c := self.command(project, o["op"], platform=o.get("platform") or "editmode",
                                 category=o.get("category"), test_filter=o.get("filter")):
                cmds.add(c)
        return {"mcp": tools, "run_command": cmds}

    # ------------------------------------------------------------ state

    async def editor_open(self, project: Path) -> bool:
        """Whether a Unity editor has `project` open (the router's pgrep rule, then the lockfile)."""
        if self._editor_open is not None:
            return await self._editor_open(project)
        return await editor_has_project(project)

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

    async def editor_state(self, session: dict) -> EditorState:
        folder = session.get("folder")
        root = Path(folder).expanduser().resolve() if folder else None
        if not root or not is_unity_project(root):
            return EditorState("unavailable", reason="not a Unity project (no ProjectSettings/ProjectVersion.txt)")
        is_open = await self.editor_open(root)
        if is_open:
            ok, why = await self.mcp_ready(session)
            if ok:
                return EditorState("mcp", True, True, True)
            return EditorState("unavailable", True, True, False,
                               f"Unity has this project open but the MCP bridge isn't reachable: {why}. Start MCP for "
                               "Unity in the editor (Window > MCP for Unity) and turn on the unity connector; "
                               "batchmode can't run while the editor has the project open.")
        if not self.unity_sh():
            return EditorState("unavailable", True, False, False, "headless-ops/scripts/unity.sh not found")
        return EditorState("batchmode", True, False, False)

    # ---------------------------------------------------------- compile

    async def compile(self, session: dict, *, consent: dict[str, set[str]] | None = None) -> BridgeResult:
        st = await self.editor_state(session)
        if st.mode == "mcp":
            return await self._compile_mcp(session, consent)
        if st.mode == "batchmode":
            return await self._compile_batch(session, consent)
        return BridgeResult("skipped", st.reason, mode=st.mode, evidence={"state": st.to_dict()})

    async def _mcp(self, session: dict, tool: str, args: dict, consent: dict | None, timeout: float) -> tuple[bool, str]:
        """(ok, raw text) of one unity MCP tool call under the hook context."""
        from .mcp_feature import tool_name

        ctx = hook_context(self.app, session, consent=consent)
        out = await asyncio.wait_for(self.app.mcp.call(ctx, tool_name(UNITY_SERVER, tool), args), timeout)
        return not out.is_error, unwrap_untrusted(out.text)

    async def _compile_mcp(self, session: dict, consent: dict | None) -> BridgeResult:
        t = self.gate_timeout()
        ev: dict[str, Any] = {"mode": "mcp"}
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

    async def _compile_batch(self, session: dict, consent: dict | None) -> BridgeResult:
        root = Path(session["folder"]).expanduser().resolve()
        cmd = self.command(root, "compile")
        assert cmd
        code, body, res, refused = await self._run(session, cmd, consent)
        ev: dict[str, Any] = {"mode": "batchmode", "command": cmd, "exit_code": code, "result": res}
        if code is None:
            return BridgeResult("skipped", f"batchmode compile didn't run: {refused[:300]}", "batchmode", evidence=ev)
        if code == 0:
            return BridgeResult("pass", "0 compile errors" + (f" ({res[len('RESULT: OK '):]})" if res else ""),
                                "batchmode", evidence=ev)
        if code == 4:
            return BridgeResult("skipped", "Unity has this project open (unity.sh refused batchmode) and the MCP "
                                           "bridge isn't reachable. Start MCP for Unity in the editor.", "batchmode",
                                evidence=ev)
        if code == 124:
            return BridgeResult("skipped", f"batchmode compile timed out after {self.batch_timeout()}s", "batchmode",
                                evidence=ev)
        if code == 3:
            return BridgeResult("skipped", f"Unity batchmode isn't set up: {res or body[-300:]}", "batchmode", evidence=ev)
        p = parse_compile_output(body)
        if p["errors"] or "compile-errors" in res:
            n = p["errors"] or 1
            ev.update({"errors": n, "root_causes": p["root_causes"]})
            return BridgeResult("fail", f"{n} compile error{'s' if n != 1 else ''} ({p['root_causes']} root "
                                        f"cause{'s' if p['root_causes'] != 1 else ''})", "batchmode",
                                report=p["report"] or body[-4000:], errors=n, evidence=ev)
        return BridgeResult("error", f"Unity batchmode failed without compile errors: {res or f'exit {code}'}",
                            "batchmode", report=body[-2000:], evidence=ev)

    # ------------------------------------------------------------ tests

    async def run_tests(self, session: dict, platform: str = "editmode", *, category: str | None = None,
                        test_filter: str | None = None, consent: dict[str, set[str]] | None = None) -> BridgeResult:
        st = await self.editor_state(session)
        if st.mode == "mcp":
            return await self._tests_mcp(session, platform, category, test_filter, consent)
        if st.mode == "batchmode":
            return await self._tests_batch(session, platform, category, test_filter, consent)
        return BridgeResult("skipped", st.reason, mode=st.mode, evidence={"state": st.to_dict()})

    async def _tests_mcp(self, session: dict, platform: str, category: str | None, test_filter: str | None,
                         consent: dict | None) -> BridgeResult:
        plat = TEST_PLATFORMS.get(platform.lower(), "EditMode")
        args: dict[str, Any] = {"mode": plat, "include_failed_tests": True}
        if category:
            args["category_names"] = [category]
        if test_filter:
            args["test_names"] = [test_filter]
        ev: dict[str, Any] = {"mode": "mcp", "platform": plat, "category": category, "filter": test_filter}
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
                           consent: dict | None) -> BridgeResult:
        root = Path(session["folder"]).expanduser().resolve()
        cmd = self.command(root, "test", platform=platform, category=category, test_filter=test_filter)
        assert cmd
        code, body, res, refused = await self._run(session, cmd, consent)
        ev: dict[str, Any] = {"mode": "batchmode", "command": cmd, "exit_code": code, "result": res,
                              "platform": TEST_PLATFORMS.get(platform.lower(), "EditMode")}
        if code is None:
            return BridgeResult("skipped", f"batchmode tests didn't run: {refused[:300]}", "batchmode", evidence=ev)
        if code in (3, 4, 124):
            why = {3: "Unity batchmode isn't set up", 4: "Unity has this project open and MCP isn't reachable",
                   124: "the test run timed out"}[code]
            return BridgeResult("skipped", f"{why}: {res}".strip(": "), "batchmode", evidence=ev)
        counts = {k: _int(v) for k, v in re.findall(r"\b(total|passed|failed|skipped)=(\d+)", body)}
        ev.update(counts)
        fails = [ln.strip() for ln in body.splitlines() if ln.startswith("FAILED ")][:30]
        ev["failed_names"] = [f[len("FAILED "):].split(" :: ")[0] for f in fails]
        if code == 0 and (counts.get("total") or counts.get("passed")):
            return BridgeResult("pass", f"{counts.get('passed', counts.get('total'))} tests passed", "batchmode",
                                evidence=ev)
        if code == 2:
            n = counts.get("failed") or len(fails) or 1
            return BridgeResult("fail", f"{n} failing test{'s' if n != 1 else ''}"
                                        + (f" of {counts['total']}" if counts.get("total") else ""), "batchmode",
                                report="\n".join(fails) or body[-3000:], errors=n, evidence=ev)
        p = parse_compile_output(body)
        if p["errors"]:
            return BridgeResult("fail", f"tests can't run: {p['errors']} compile errors", "batchmode",
                                report=p["report"], errors=p["errors"], evidence=ev)
        return BridgeResult("skipped" if code == 0 else "error", f"no usable test results ({res or f'exit {code}'})",
                            "batchmode", report=body[-2000:], evidence=ev)


async def editor_has_project(project: Path) -> bool:
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

    if await run("pgrep", "-fi", pat):
        return True
    lock = project / "Temp" / "UnityLockfile"
    return lock.exists() and bool(await run("lsof", "-t", str(lock)))


def get_bridge(app: "AppState") -> UnityBridge:
    """The app's bridge (tests replace it with a FakeUnityBridge in app.extensions)."""
    b = app.extensions.get("unity_bridge")
    if b is None:
        b = app.extensions["unity_bridge"] = UnityBridge(app)
    return b  # type: ignore[return-value]


class FakeUnityBridge(UnityBridge):
    """For tests: scripted results instead of Unity. `compile` / `tests` are lists of
    BridgeResult (or dicts) consumed in order (the last one repeats); calls are recorded as
    (op, session_id, consent)."""

    def __init__(self, app: "AppState", *, compile: list | None = None, tests: list | None = None,
                 state: EditorState | None = None):
        super().__init__(app)
        self._compile = list(compile or [BridgeResult("pass", "0 compile errors", "fake")])
        self._tests = list(tests or [BridgeResult("pass", "1 tests passed", "fake")])
        self.state = state or EditorState("mcp", True, True, True)
        self.calls: list[tuple[str, str, dict | None]] = []

    @staticmethod
    def _next(q: list) -> BridgeResult:
        r = q.pop(0) if len(q) > 1 else q[0]
        return r if isinstance(r, BridgeResult) else BridgeResult(**r)

    async def editor_state(self, session: dict) -> EditorState:
        return self.state

    async def compile(self, session: dict, *, consent: dict[str, set[str]] | None = None) -> BridgeResult:
        self.calls.append(("compile", session["id"], consent))
        return self._next(self._compile)

    async def run_tests(self, session: dict, platform: str = "editmode", *, category: str | None = None,
                        test_filter: str | None = None, consent: dict[str, set[str]] | None = None) -> BridgeResult:
        self.calls.append(("tests", session["id"], consent))
        return self._next(self._tests)


__all__ = ["BridgeResult", "EditorState", "FakeUnityBridge", "UnityBridge", "editor_has_project", "get_bridge",
           "is_unity_project", "load_script", "parse_compile_output", "unwrap_untrusted", "UNITY_SERVER"]
