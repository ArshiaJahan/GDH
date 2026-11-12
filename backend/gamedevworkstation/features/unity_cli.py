"""The official Unity CLI (`unity`, Unity Hub's CLI) as a Unity backend next to MCP for Unity.

Two halves of the CLI are used:
- **batch** (no package needed, the Editor must NOT have the project open): `unity test` (NUnit XML,
  exit 0 passed / 8 tests failed / 6 no verdict), `unity run` (batch mode + `-quit`, the Editor's
  exit code), `unity build` (verdict from the Editor log).
- **live** (the `com.unity.pipeline` package in the project, the Editor open): `unity status`,
  `unity recompile` (compile errors as JSON, exit 0/6/7), `unity command <name>` (built-in Editor
  commands: run_tests, eval, screenshot, editor_play, ...) and `unity job wait|cancel`.

Everything runs with argv lists (no shell), `--format json` (stdout holds the result envelope
{success, command, data, errors: [{code, message}], warnings}; the streamed Editor log goes to
stderr), `--project-path` / the project positional always given, and the non-interactive env.

UnityRunner runs one Unity job per project at a time, as a `jobs` row (kind "unity") whose stderr
streams to the Terminal drawer like an agent command; timeouts and cancels kill the CLI's process
group and sweep any `-batchmode` Unity it left behind for this project (never a GUI Editor).

Verified against the real CLI 1.0.0-beta.13 (2026-11-12): flag names of test/run/build/recompile/
status/command/job/close/pipeline install; `recompile` with no Editor → exit 7 COMMAND_FAILED;
`status` with no Editor → exit 6 STATUS_NO_INSTANCES; `command` with no Editor → exit 6;
reserved flags after `--` (-quit, -batchmode, ...) → exit 6 before any Editor starts; `build` has
`--timeout`; Pipeline 0.10 names its test command `test run` (args mode/filter/filter-type/timeout)
while the docs say `run_tests`, so the live test command is looked up in the Editor's catalog.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..app import AppState
    from .unity_bridge import BridgeResult

log = logging.getLogger(__name__)

CLI_ENV = {"UNITY_NON_INTERACTIVE": "1", "UNITY_NO_BANNER": "1", "UNITY_NO_PAGER": "1",
           "UNITY_NO_CONSENT_PROMPT": "1", "UNITY_NO_UPDATE_CHECK": "1", "NO_COLOR": "1",
           "UNITY_NO_CRASH_REPORT": "1", "TERM": "dumb"}
CLI_CANDIDATES = ["~/.unity/bin/unity", "/Applications/Unity Hub.app/Contents/Resources/unity"]
# Tests set GDW_UNITY_CLI_SEARCH=0: only [unity].cli_path is looked at (never the real CLI).
SEARCH_ENV = "GDW_UNITY_CLI_SEARCH"
EXIT = {"ok": 0, "general": 1, "bad_args": 2, "auth": 3, "precondition": 4, "failed": 6, "unreachable": 7,
        "tests_failed": 8, "sigint": 130, "sigterm": 143}
MIN_CLI_VERSION = "1.0.0-beta.11"
GLOBAL_EDITOR_LOG = Path("~/Library/Logs/Unity/Editor.log")
PIPELINE_PACKAGE = "com.unity.pipeline"
MCP_PACKAGES = ("com.coplaydev.unity-mcp", "com.justinpbarnett.unity-mcp")

# Editor flags the CLI manages itself (passing them after `--` fails with exit 6).
RUN_RESERVED = {"-batchmode", "-quit", "-projectpath", "-usehub", "-hubipc", "-enablecacheserver",
                "-cacheserverendpoint"}
TEST_RESERVED = RUN_RESERVED | {"-runtests", "-testplatform", "-testresults", "-testfilter", "-enablecodecoverage",
                                "-coverageresultspath", "-coverageoptions"}

DEFAULTS: dict[str, Any] = {
    "backend": "auto", "auto_live_order": ["mcp", "cli_live"], "cli_path": "", "prefer_official_cli": True,
    "min_cli_version": MIN_CLI_VERSION, "editor_root": "/Applications/Unity/Hub/Editor", "editor_path": "",
    "pipeline_version": "1.0.0", "live_timeout_s": 120, "live_test_timeout_s": 900, "live_wait_s": 20,
    "batch_timeout_s": 900, "test_timeout_s": 1800, "build_timeout_s": 3600, "nographics": True,
    "extra_editor_args": [], "clone_when_open": "ask", "eval": "ask", "harness_scripts": "ask",
    "harness_git_exclude": True, "mcp_server": "unity",
}
BACKENDS = ("auto", "mcp", "cli")


def unity_cfg(app: "AppState | Any") -> dict:
    """The effective [unity] settings (defaults + config.toml). [hooks].batchmode_timeout_s stays
    an alias of batch_timeout_s when [unity] doesn't set it."""
    cfg = getattr(app, "config", app)
    u = dict(getattr(cfg, "unity", None) or {})
    out = {**DEFAULTS, **{k: v for k, v in u.items() if v is not None}}
    hooks = getattr(cfg, "hooks", None) or {}
    if hooks.get("batchmode_timeout_s") and u.get("batch_timeout_s") in (None, DEFAULTS["batch_timeout_s"]):
        out["batch_timeout_s"] = hooks["batchmode_timeout_s"]  # the older key, when [unity] keeps the default
    if out.get("backend") not in BACKENDS:
        out["backend"] = "auto"
    return out


def cfg_int(cfg: dict, key: str, lo: int = 5, hi: int = 4 * 3600) -> int:
    try:
        v = int(cfg.get(key) or DEFAULTS[key])
    except (TypeError, ValueError):
        v = int(DEFAULTS[key])
    return min(max(v, lo), hi)


# ------------------------------------------------------------------ versions


def _vkey(v: str) -> tuple:
    """Sort key of a semver-ish version: 1.0.0-beta.13 < 1.0.0-beta.17 < 1.0.0."""
    m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?", v or "")
    if not m:
        return (-1,)
    pre = m.group(4)
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in (pre.split(".") if pre else ()))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if pre else 1, parts)


def version_at_least(v: str, minimum: str) -> bool:
    return _vkey(v) >= _vkey(minimum)


# ------------------------------------------------------------------ discovery


@dataclass(frozen=True)
class UnityCliInfo:
    path: Path
    version: str
    options: dict = field(default_factory=dict, compare=False, hash=False)  # "test" -> ["--mode", ...]

    def at_least(self, v: str) -> bool:
        return version_at_least(self.version, v)

    def has(self, command: str, flag: str) -> bool:
        """Whether `unity <command>` lists `flag` (unknown catalog: assume yes)."""
        opts = self.options.get(command)
        return True if opts is None else flag in opts


@dataclass
class CliStatus:
    info: UnityCliInfo | None
    ok: bool
    reason: str = ""
    update_available: str | None = None

    def to_dict(self) -> dict:
        if not self.info:
            return {"ok": False, "reason": self.reason}
        return {"path": str(self.info.path), "version": self.info.version, "ok": self.ok, "reason": self.reason,
                "update_available": self.update_available}


_PROBE_CACHE: dict[tuple[str, float], UnityCliInfo | None] = {}


def cli_env(extra: dict | None = None) -> dict:
    env = {**os.environ, **CLI_ENV, **(extra or {})}
    for k in ("UNITY_PROJECT_PATH", "UNITY_FORMAT", "UNITY_QUIET"):
        env.pop(k, None)
    return env


def _walk_catalog(cmds: list, prefix: str, out: dict) -> None:
    for c in cmds or []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        name = f"{prefix} {c['name']}".strip()
        out[name] = [o.get("long") for o in c.get("options") or [] if isinstance(o, dict) and o.get("long")]
        _walk_catalog(c.get("subcommands") or c.get("commands") or [], name, out)


def probe_cli(path: Path) -> UnityCliInfo | None:
    """`--version` must print a version and `commands --format json` must list `recompile`
    (rejects unrelated programs named `unity`). Cached per (path, mtime)."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    info = None
    try:
        out = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=5,
                             stdin=subprocess.DEVNULL, env=cli_env())
        m = re.search(r"\b(\d+\.\d+\.\d+(?:-[0-9A-Za-z.\-]+)?)\b", out.stdout or "")
        if out.returncode == 0 and m:
            cat = subprocess.run([str(path), "commands", "--format", "json"], capture_output=True, text=True,
                                 timeout=20, stdin=subprocess.DEVNULL, env=cli_env())
            env = parse_envelope(cat.stdout)
            opts: dict[str, list] = {}
            cmds = ((env or {}).get("data") or {}).get("commands") if isinstance((env or {}).get("data"), dict) else None
            _walk_catalog(cmds or [], "", opts)
            if "recompile" in opts:
                info = UnityCliInfo(path, m.group(1), opts)
    except (OSError, subprocess.SubprocessError, ValueError):
        info = None
    if info is not None:  # a failure (e.g. one slow `commands` call) is retried next time
        _PROBE_CACHE[key] = info
    return info


def cli_candidates(cfg: dict) -> list[Path]:
    out: list[Path] = []
    if cfg.get("cli_path"):
        out.append(Path(str(cfg["cli_path"])).expanduser())
    if os.environ.get(SEARCH_ENV, "1") != "0":
        if p := shutil.which("unity"):
            out.append(Path(p))
        out += [Path(c).expanduser() for c in CLI_CANDIDATES]
    seen, uniq = set(), []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def find_unity_cli(cfg: dict) -> CliStatus:
    """[unity].cli_path → `unity` on PATH → CLI_CANDIDATES. A configured path that doesn't work is
    reported, not silently replaced. Too old (min_cli_version) → found but not ok."""
    explicit = bool(cfg.get("cli_path"))
    for p in cli_candidates(cfg):
        if not (p.is_file() and os.access(p, os.X_OK)):
            if explicit and p == Path(str(cfg["cli_path"])).expanduser():
                return CliStatus(None, False, f"[unity].cli_path {p} isn't an executable file")
            continue
        info = probe_cli(p)
        if info is None:
            if explicit and p == Path(str(cfg["cli_path"])).expanduser():
                return CliStatus(None, False, f"{p} doesn't answer like the Unity CLI (`--version`, `commands`)")
            continue
        minimum = str(cfg.get("min_cli_version") or MIN_CLI_VERSION)
        if not info.at_least(minimum):
            return CliStatus(info, False, f"Unity CLI {info.version} is older than {minimum}: update it "
                                          "(Settings → Unity → Update, or `unity self-update`)")
        return CliStatus(info, True)
    return CliStatus(None, False, "the Unity CLI (`unity`) isn't installed (Unity Hub installs it; or "
                                  "`curl -fsSL https://unity.com/install.sh | bash`)")


# ------------------------------------------------------------------ projects / editors


def project_editor_version(project: Path) -> str | None:
    try:
        text = (project / "ProjectSettings" / "ProjectVersion.txt").read_text(errors="replace")
    except OSError:
        return None
    m = re.search(r"^m_EditorVersion:\s*(\S+)", text, re.M)
    return m.group(1) if m else None


def _manifest(project: Path) -> dict:
    try:
        d = json.loads((project / "Packages" / "manifest.json").read_text(errors="replace"))
        return d.get("dependencies") or {} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def pipeline_in_manifest(project: Path) -> str | None:
    v = _manifest(project).get(PIPELINE_PACKAGE)
    return str(v) if v else None


def mcp_in_manifest(project: Path) -> bool:
    deps = _manifest(project)
    return any(k in deps for k in MCP_PACKAGES) or any("unity-mcp" in k or "mcpforunity" in k.lower() for k in deps)


def _editor_binary(app_path: Path) -> Path:
    return app_path / "Contents" / "MacOS" / "Unity" if app_path.suffix == ".app" else app_path


def find_editor_binary(project: Path, cfg: dict, installed: list[dict] | None = None) -> tuple[Path | None, str]:
    """[unity].editor_path → <editor_root>/<ver>/Unity.app → `unity editors --installed` location of
    exactly the project's version. Never another version. (path, reason when None)."""
    if cfg.get("editor_path"):
        p = _editor_binary(Path(str(cfg["editor_path"])).expanduser())
        return (p, "") if p.exists() else (None, f"[unity].editor_path {p} doesn't exist")
    ver = project_editor_version(project)
    if not ver:
        return None, "ProjectSettings/ProjectVersion.txt has no m_EditorVersion"
    p = Path(str(cfg.get("editor_root") or DEFAULTS["editor_root"])).expanduser() / ver / "Unity.app"
    if p.exists():
        return _editor_binary(p), ""
    for e in installed or []:
        if str(e.get("version")) == ver and e.get("location"):
            return _editor_binary(Path(str(e["location"]))), ""
    have = ", ".join(sorted({str(e.get("version")) for e in installed or [] if e.get("version")})) or "none found"
    return None, f"Unity {ver} (this project's version) isn't installed (installed: {have})"


# ------------------------------------------------------------------ argv builders


def _p(project: Path) -> str:
    return str(Path(project))


def _check_reserved(args: list[str], reserved: set[str]) -> None:
    for a in args:
        if a.split("=", 1)[0].lower().lstrip("-") in {r.lstrip("-") for r in reserved}:
            raise ValueError(f"{a} is managed by the Unity CLI and can't be passed after `--`")


def argv_status(cli: UnityCliInfo, project: Path, until_ready_s: int | None = None) -> list[str]:
    a = [str(cli.path), "status", "--project-path", _p(project)]
    if until_ready_s:
        a += ["--until-ready", "--timeout", str(int(until_ready_s))]
    return a + ["--format", "json"]


def argv_pipeline_list(cli: UnityCliInfo) -> list[str]:
    return [str(cli.path), "pipeline", "list", "--format", "json"]


def argv_editors(cli: UnityCliInfo) -> list[str]:
    return [str(cli.path), "editors", "--installed", "--format", "json"]


def argv_recompile(cli: UnityCliInfo, project: Path, timeout_s: int, strict: bool = False) -> list[str]:
    a = [str(cli.path), "recompile", "--project-path", _p(project), "--timeout", str(int(timeout_s))]
    if strict:
        a.append("--strict")
    return a + ["--format", "json"]


def argv_run_batch(cli: UnityCliInfo, project: Path, log: Path, timeout_s: int, editor_args: list[str], *,
                   editor_path: Path | None = None) -> list[str]:
    """`unity run P --timeout T --log-file LOG [-e ED] --format json -- <editor args>` (the CLI adds
    -batchmode -quit -projectPath itself)."""
    _check_reserved(editor_args, RUN_RESERVED)
    a = [str(cli.path), "run", _p(project), "--timeout", str(int(timeout_s)), "--log-file", str(log)]
    if editor_path:
        a += ["--editor-path", str(editor_path)]
    a += ["--format", "json"]
    return a + (["--", *editor_args] if editor_args else [])


TEST_MODES = {"editmode": "EditMode", "edit": "EditMode", "playmode": "PlayMode", "play": "PlayMode"}


def argv_test_batch(cli: UnityCliInfo, project: Path, platform: str, out_xml: Path, timeout_s: int, *,
                    test_filter: str | None = None, category: str | None = None, assemblies: str | None = None,
                    nographics: bool = True, editor_path: Path | None = None,
                    extra: list[str] | None = None) -> list[str]:
    """`unity test P --mode M --output XML --timeout T [--filter F] --format json [-- -testCategory C
    -assemblyNames A -nographics]`. There's no --category flag: categories and assemblies are
    forwarded to the Editor after `--`; PlayMode never gets -nographics."""
    mode = TEST_MODES.get((platform or "editmode").lower(), "EditMode")
    a = [str(cli.path), "test", _p(project), "--mode", mode, "--output", str(out_xml), "--timeout", str(int(timeout_s))]
    if test_filter:
        a += ["--filter", test_filter]
    if editor_path:
        a += ["--editor-path", str(editor_path)]
    a += ["--format", "json"]
    fwd: list[str] = []
    if category:
        fwd += ["-testCategory", category]
    if assemblies:
        fwd += ["-assemblyNames", assemblies]
    if nographics and mode == "EditMode":
        fwd.append("-nographics")
    fwd += list(extra or [])
    _check_reserved(fwd, TEST_RESERVED)
    return a + (["--", *fwd] if fwd else [])


def argv_build(cli: UnityCliInfo, project: Path, *, profile: str | None, target: str | None, out: Path, log: Path,
               timeout_s: int | None = None, execute_method: str | None = None,
               editor_path: Path | None = None) -> list[str]:
    if not profile and not target:
        raise ValueError("a build needs a profile or a target")
    a = [str(cli.path), "build", _p(project)]
    a += ["--profile", profile] if profile else ["--target", str(target)]
    if execute_method:
        a += ["--execute-method", execute_method]
    a += ["--output-path", str(out), "--log-file", str(log)]
    if timeout_s and cli.has("build", "--timeout"):
        a += ["--timeout", str(int(timeout_s))]
    if editor_path:
        a += ["--editor-path", str(editor_path)]
    return a + ["--format", "json"]


def _param_args(params: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for k, v in (params or {}).items():
        if v is None:
            continue
        k = str(k).lstrip("-")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]*", k):
            raise ValueError(f"bad parameter name {k!r}")
        val = ("true" if v else "false") if isinstance(v, bool) else json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        out += [f"--{k}", val]
    return out


def argv_command(cli: UnityCliInfo, project: Path, name: str, params: dict[str, Any] | None = None, *,
                 timeout_s: int = 30, detach: bool = False) -> list[str]:
    """`unity command NAME --project-path P --timeout T --format json [--detach] -- --k v …`: params
    after the `--` fence, so an Editor param named `timeout` isn't eaten by the CLI's own flag.
    NAME may be a group command ("test run")."""
    words = str(name).split()
    if not words or not all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-.]*", w) for w in words):
        raise ValueError(f"bad command name {name!r}")
    a = [str(cli.path), "command", *words, "--project-path", _p(project), "--timeout", str(int(timeout_s)),
         "--format", "json"]
    if detach:
        a.append("--detach")
    rest = _param_args(params or {})
    return a + (["--", *rest] if rest else [])


def argv_command_list(cli: UnityCliInfo, project: Path, query: str | None = None) -> list[str]:
    a = [str(cli.path), "command", "--project-path", _p(project), "--detail", "full"]
    if query:
        a += ["--query", query]
    return a + ["--format", "json"]


def argv_job(cli: UnityCliInfo, project: Path, action: Literal["wait", "status", "cancel"], job_id: str,
             timeout_s: int = 0) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9_\-.:]+", str(job_id)):
        raise ValueError(f"bad job id {job_id!r}")
    a = [str(cli.path), "job", action, str(job_id), "--project-path", _p(project)]
    if action == "wait":
        a += ["--timeout", str(int(timeout_s))]
    return a + ["--format", "json"]


def argv_pipeline_install(cli: UnityCliInfo, project: Path, version: str) -> list[str]:
    return [str(cli.path), "pipeline", "install", "--project-path", _p(project), "--package-version", str(version),
            "--format", "json"]


def argv_close(cli: UnityCliInfo, project: Path, timeout_s: int = 30) -> list[str]:
    return [str(cli.path), "close", _p(project), "--timeout", str(int(timeout_s)), "--format", "json"]  # never --force


def argv_open(cli: UnityCliInfo, project: Path) -> list[str]:
    return [str(cli.path), "open", _p(project), "--format", "json"]


def argv_self_update(cli: UnityCliInfo) -> list[str]:
    return [str(cli.path), "self-update", "--format", "json"]


# ------------------------------------------------------------------ envelopes / runs


def parse_envelope(text: str | None) -> dict | None:
    """The CLI's JSON result document (the last top-level JSON object on stdout)."""
    s = (text or "").strip()
    if not s:
        return None
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    for m in reversed(list(re.finditer(r"^\{", s, re.M))):
        try:
            v = json.loads(s[m.start():])
            return v if isinstance(v, dict) else None
        except ValueError:
            continue
    return None


@dataclass
class CliRun:
    exit_code: int | None          # None: didn't start
    envelope: dict | None          # parsed stdout JSON envelope
    stderr_tail: str = ""          # last ~64 KB of the streamed log
    log_path: Path | None = None
    started_at: float = 0.0        # wall clock at spawn (ladder ts uses this)
    duration_s: float = 0.0
    timed_out: bool = False
    cancelled: bool = False
    job_id: str | None = None
    argv: list[str] = field(default_factory=list)
    error: str = ""                # why it didn't start

    def error_code(self) -> str:
        errs = (self.envelope or {}).get("errors") or []
        return str(errs[0].get("code") or "") if errs and isinstance(errs[0], dict) else ""

    def error_message(self) -> str:
        errs = (self.envelope or {}).get("errors") or []
        return str(errs[0].get("message") or "") if errs and isinstance(errs[0], dict) else ""

    @property
    def data(self) -> Any:
        return (self.envelope or {}).get("data")

    @property
    def cmd(self) -> str:
        return shlex.join(self.argv) if self.argv else ""

    def log_text(self, cap: int = 2_000_000) -> str:
        """The Editor log the CLI wrote (--log-file), else the streamed stderr."""
        if self.log_path:
            try:
                if self.log_path.is_file() and self.log_path.stat().st_size <= cap:
                    return self.log_path.read_text(errors="replace")
                if self.log_path.is_file():
                    with self.log_path.open("rb") as f:
                        f.seek(-cap, 2)
                        return f.read().decode(errors="replace")
            except OSError:
                pass
        return self.stderr_tail


def _elapsed_s(etime: str) -> float | None:
    """ps etime `[[dd-]hh:]mm:ss` → seconds."""
    m = re.fullmatch(r"\s*(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)\s*", etime or "")
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def batch_editor_pids(project: Path) -> list[int]:
    """Batch-mode Unity processes for exactly this project (`-batchmode` and `-projectPath <P>`
    in their command line). A GUI Editor has no -batchmode and is never listed."""
    if not shutil.which("pgrep"):
        return []
    esc = re.escape(str(project))
    pat = rf"Unity\.app/Contents/MacOS/Unity.*-batchmode.*-projectPath[= ]+{esc}/?( |$)"
    try:
        out = subprocess.run(["pgrep", "-fi", pat], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    pids = [int(x) for x in out.stdout.split() if x.isdigit()]
    rx = re.compile(r"-batchmode")
    keep = []
    for pid in pids:
        if pid == os.getpid():
            continue
        try:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        # A GUI Editor's import workers are batch-mode Unity processes too: never touch them.
        if rx.search(cmd) and "Unity.app/Contents/MacOS/Unity" in cmd and "AssetImportWorker" not in cmd:
            keep.append(pid)
    return keep


def _started_after(pid: int, since: float) -> bool:
    try:
        et = subprocess.run(["ps", "-o", "etime=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    e = _elapsed_s(et)
    return e is not None and time.time() - e >= since - 2


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return False


class UnityRunner:
    """One Unity job per project at a time (asyncio.Lock per resolved project path, shared by gates,
    the agent tool and the API). Jobs are `jobs` rows (kind "unity") whose stderr streams to the
    Terminal drawer; a timeout (the CLI's own + grace) or a cancel kills the process tree."""

    KILL_WAIT_S = 10.0
    GRACE_S = 30.0

    def __init__(self, app: "AppState"):
        self.app = app
        self._locks: dict[str, asyncio.Lock] = {}
        self.busy: dict[str, dict] = {}  # project -> {"label", "job_id"}

    def lock(self, project: Path) -> asyncio.Lock:
        key = str(Path(project).expanduser().resolve())
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def quick(self, argv: list[str], *, cwd: Path | None = None, timeout_s: float = 20) -> CliRun:
        """A short read-only call (status, pipeline list, command listing): no job row, no lock."""
        t0 = time.time()
        try:
            p = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd) if cwd else None, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL,
                                                     env=cli_env(), start_new_session=True)
        except OSError as e:
            return CliRun(None, None, started_at=t0, argv=argv, error=str(e))
        try:
            out, err = await asyncio.wait_for(p.communicate(), timeout_s)
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            if isinstance(e, asyncio.CancelledError):
                raise
            await p.wait()
            return CliRun(None, None, started_at=t0, duration_s=time.time() - t0, timed_out=True, argv=argv)
        return CliRun(p.returncode, parse_envelope(out.decode(errors="replace")), err.decode(errors="replace")[-64_000:],
                      started_at=t0, duration_s=time.time() - t0, argv=argv)

    async def run(self, session: dict | None, argv: list[str], *, project: Path, label: str, timeout_s: float,
                  log_path: Path | None = None, cancel: asyncio.Event | None = None, locked: bool = True,
                  grace_s: float | None = None, sweep: bool = True, merge: bool = False) -> CliRun:
        """Run argv as a Unity job under the project lock (locked=False when the caller holds it).
        The watchdog is timeout_s + grace (the CLI's own --timeout fires first). sweep: after a
        timeout or cancel also end batch-mode Unity left for this project (batch routes only).
        merge: stdout and stderr are one stream (unity.sh); else stdout is the JSON envelope."""
        project = Path(project).expanduser().resolve()
        kw = dict(sweep=sweep, merge=merge)
        if locked:
            async with self.lock(project):
                return await self._run(session, argv, project, label, timeout_s, log_path, cancel, grace_s, **kw)
        return await self._run(session, argv, project, label, timeout_s, log_path, cancel, grace_s, **kw)

    async def _run(self, session: dict | None, argv: list[str], project: Path, label: str, timeout_s: float,
                   log_path: Path | None, cancel: asyncio.Event | None, grace_s: float | None, *,
                   sweep: bool = True, merge: bool = False) -> CliRun:
        app = self.app
        sid = (session or {}).get("id")
        jid = app.jobs.start(sid, "unity", label, {"project": str(project), "argv": argv, "cwd": str(project)})
        pg: dict[str, int] = {}
        started = time.time()
        watchdog = float(timeout_s) + (self.GRACE_S if grace_s is None else grace_s)
        self.busy[str(project)] = {"label": label, "job_id": jid}
        app.bus.publish("unity.job", {"project": str(project), "job_id": jid, "label": label, "running": True}, sid)
        code: int | None = None
        try:
            task = asyncio.ensure_future(app.commands.run_exec(
                jid, argv, project, watchdog, env=cli_env(), display=shlex.join(argv), capture_stdout=not merge,
                on_start=lambda p: pg.__setitem__("pgid", p.pid)))
            app.jobs.attach(jid, task)
            waiter = asyncio.ensure_future(cancel.wait()) if cancel is not None else None
            cancelled = False
            try:
                done, _ = await asyncio.wait({task, *([waiter] if waiter else [])}, return_when=asyncio.FIRST_COMPLETED)
                if task not in done:  # cancel requested
                    cancelled = True
                    await app.jobs.cancel(jid)
                    await asyncio.wait({task}, timeout=self.KILL_WAIT_S + 5)
            except asyncio.CancelledError:
                task.cancel()
                await asyncio.shield(self.kill_tree(pg.get("pgid"), project, started, sweep=sweep))
                if (app.jobs.get(jid) or {}).get("status") == "running":
                    app.jobs.finish(jid, "cancelled")
                raise
            finally:
                if waiter:
                    waiter.cancel()
            text, out = "", ""
            if task.cancelled():
                cancelled = True
            elif task.done() and task.exception() is None:
                code, text, out = task.result()
            elif task.done():
                err = task.exception()
                log.warning("unity job %s failed to run: %s", jid, err)
                if (app.jobs.get(jid) or {}).get("status") == "running":
                    app.jobs.finish(jid, "failed", error=str(err)[:300])
                return CliRun(None, None, started_at=started, argv=argv, job_id=jid, error=str(err))
            timed_out = code == 124
            if cancelled or timed_out or (code is not None and code < 0):
                await asyncio.shield(self.kill_tree(pg.get("pgid"), project, started, sweep=sweep))
            if cancelled:
                code = None
                j = app.jobs.get(jid) or {}
                if j.get("status") != "cancelled":
                    app.jobs.update(jid, status="cancelled")
            if log_path and not log_path.exists() and text:
                try:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text(text, encoding="utf-8")
                except OSError:
                    pass
            return CliRun(code, None if merge else parse_envelope(out), text[-64_000:], log_path, started,
                          time.time() - started, timed_out, cancelled, jid, argv)
        finally:
            self.busy.pop(str(project), None)
            app.bus.publish("unity.job", {"project": str(project), "job_id": jid, "label": label, "running": False,
                                          "exit_code": code}, sid)

    async def kill_tree(self, pgid: int | None, project: Path, started_at: float, *, sweep: bool = True) -> None:
        """killpg(SIGTERM) → wait → killpg(SIGKILL); then (sweep) end `-batchmode` Unity processes for
        this project started after the job (the CLI may start its Editor in another session; a
        GUI Editor and its import workers are never touched)."""
        if pgid:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except OSError:
                pass
            t_end = time.monotonic() + self.KILL_WAIT_S
            while _group_alive(pgid) and time.monotonic() < t_end:
                await asyncio.sleep(0.2)
            if _group_alive(pgid):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except OSError:
                    pass
        if not sweep:
            return
        pids = [p for p in await asyncio.to_thread(batch_editor_pids, project)
                if await asyncio.to_thread(_started_after, p, started_at)]
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        t_end = time.monotonic() + 5
        while any(_alive(p) for p in pids) and time.monotonic() < t_end:
            await asyncio.sleep(0.2)
        for pid in pids:
            if _alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass


def get_runner(app: "AppState") -> UnityRunner:
    r = app.extensions.get("unity_runner")
    if r is None:
        r = app.extensions["unity_runner"] = UnityRunner(app)
    return r  # type: ignore[return-value]


# ------------------------------------------------------------------ live state


@dataclass
class LiveState:
    state: str          # ready | starting | load_pending | safe_mode | absent | unreachable | no_cli | unknown
    pid: int | None = None
    port: int | None = None
    pipeline_version: str | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _lower_keys(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k).lower(): _lower_keys(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_lower_keys(v) for v in o]
    return o


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


_LIVE_CACHE: dict[str, tuple[float, LiveState]] = {}
LIVE_CACHE_S = 3.0


def invalidate_live(project: Path | None = None) -> None:
    if project is None:
        _LIVE_CACHE.clear()
    else:
        _LIVE_CACHE.pop(str(Path(project).expanduser().resolve()), None)


async def live_state(runner: UnityRunner, cli: UnityCliInfo | None, project: Path, *, editor_open: bool,
                     use_cache: bool = True) -> LiveState:
    """Whether the Editor that has `project` open serves the Pipeline API (`unity status`), and if not
    why (load pending, Safe Mode via `unity pipeline list`, package absent). Cached 3 s."""
    key = str(Path(project).expanduser().resolve())
    if use_cache and (hit := _LIVE_CACHE.get(key)) and time.monotonic() - hit[0] < LIVE_CACHE_S:
        return hit[1]
    st = await _live_state(runner, cli, Path(key), editor_open)
    _LIVE_CACHE[key] = (time.monotonic(), st)
    return st


async def _live_state(runner: UnityRunner, cli: UnityCliInfo | None, project: Path, editor_open: bool) -> LiveState:
    if cli is None:
        return LiveState("no_cli", reason="the Unity CLI isn't available")
    pkg = pipeline_in_manifest(project)
    run = await runner.quick(argv_status(cli, project), cwd=project, timeout_s=20)
    if run.exit_code is None:
        return LiveState("unknown", reason="`unity status` didn't answer" + (f" ({run.error})" if run.error else ""))
    code = run.error_code()
    data = _lower_keys(run.data or {})
    inst = [i for i in (data.get("instances") or []) if isinstance(i, dict)] if isinstance(data, dict) else []
    def path_of(i: dict) -> str:
        return str(i.get("projectpath") or i.get("project") or "").rstrip("/")

    # `status --project-path` already filters; only trust an unlabelled instance as ours.
    mine = next((i for i in inst if path_of(i) == str(project)),
                inst[0] if len(inst) == 1 and not path_of(inst[0]) else None)
    ver = str((mine or {}).get("pipelineversion") or (mine or {}).get("packageversion") or pkg or "") or None
    if run.exit_code == 0 and mine and str(mine.get("state") or "ready").lower() == "ready":
        return LiveState("ready", _int(mine.get("pid")), _int(mine.get("port")), ver)
    if code == "STATUS_NOT_READY" or (mine and str(mine.get("state") or "").lower() == "starting"):
        return LiveState("starting", _int((mine or {}).get("pid")), None, ver, "the Editor is still starting")
    if code == "STATUS_PIPELINE_LOAD_PENDING":
        return LiveState("load_pending", pipeline_version=pkg,
                         reason="Unity hasn't loaded the Pipeline package yet: switch to the Unity window once")
    if code == "STATUS_ALL_UNREACHABLE":
        return LiveState("unreachable", pipeline_version=pkg, reason="the Editor's Pipeline server doesn't answer")
    if editor_open:
        pl = await runner.quick(argv_pipeline_list(cli), cwd=project, timeout_s=20)
        pdata = _lower_keys(pl.data or {})
        summ = pdata.get("summary") or {} if isinstance(pdata, dict) else {}
        insts = [i for i in (pdata.get("instances") or []) if isinstance(i, dict)] if isinstance(pdata, dict) else []
        safe = [i for i in insts if (i.get("safemode") or {}).get("detected")]
        safe_mine = [i for i in safe if str(i.get("projectpath") or i.get("project") or "").rstrip("/") == str(project)]
        if safe_mine or (not insts and (_int(summ.get("instancesinsafemode")) or 0) > 0) or (safe and len(insts) == 1):
            return LiveState("safe_mode", _int((safe_mine or safe or [{}])[0].get("pid")), None, pkg,
                             "Unity opened this project in Safe Mode (compile errors at boot): the Pipeline "
                             "package isn't loaded")
        if not pkg:
            return LiveState("absent", reason=f"{PIPELINE_PACKAGE} isn't in Packages/manifest.json")
        return LiveState("unreachable", pipeline_version=pkg,
                         reason=f"{PIPELINE_PACKAGE} {pkg} is in the manifest but the open Editor doesn't serve it "
                                "(still importing, Safe Mode, or a modal dialog)")
    return LiveState("absent" if not pkg else "unreachable", pipeline_version=pkg,
                     reason="no Unity Editor has this project open")


def safe_mode_errors(project: Path, since: float | None = None) -> tuple[str, str]:
    """Compile errors behind a Safe Mode boot, from `<project>/Logs/Editor.log` (or the global
    Editor.log when it mentions this project): only `error CS` lines. (text, source path)."""
    cands = [project / "Logs" / "Editor.log", GLOBAL_EDITOR_LOG.expanduser()]
    for p in cands:
        try:
            if not p.is_file() or (since and p.stat().st_mtime < since):
                continue
            with p.open("rb") as f:
                size = p.stat().st_size
                f.seek(max(0, size - 4_000_000))
                text = f.read().decode(errors="replace")
        except OSError:
            continue
        if p != cands[0] and str(project) not in text:
            continue
        lines = [ln for ln in text.splitlines() if re.search(r"error CS\d{4}", ln)]
        if lines:
            return "\n".join(dict.fromkeys(lines)), str(p)
    return "", ""


# ------------------------------------------------------------------ parsers → BridgeResult


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _bridge():  # late import: unity_bridge imports this module
    from . import unity_bridge
    return unity_bridge


def _diagnostics(data: Any) -> tuple[list[dict], list[dict]]:
    d = _lower_keys(data) if isinstance(data, (dict, list)) else {}
    if not isinstance(d, dict):
        return [], []
    errs = [e for e in d.get("errors") or [] if isinstance(e, dict)]
    warns = [e for e in d.get("warnings") or [] if isinstance(e, dict)]
    return errs, warns


def _console_entry(e: dict) -> dict:
    f, ln, col = e.get("file") or e.get("path") or "", e.get("line"), e.get("column") or e.get("col")
    loc = f"{f}({ln},{col or 1})" if f and ln is not None else f
    code = e.get("code") or e.get("id") or ""
    return {"type": "error", "message": f"{loc}: error {code}: {e.get('message') or ''}".strip(": ")}


def result_from_recompile(run: CliRun) -> "BridgeResult":
    B = _bridge()
    ev: dict[str, Any] = {"route": "cli_live", "exit_code": run.exit_code, "cmd": run.cmd,
                          "error_code": run.error_code()}
    if run.timed_out or run.exit_code is None:
        return B.BridgeResult("skipped", "`unity recompile` didn't finish in time", "cli_live", evidence=ev)
    errs, warns = _diagnostics(run.data)
    ev["warnings"] = len(warns)
    if run.exit_code == 0:
        return B.BridgeResult("pass", "0 compile errors" + (f" ({_plural(len(warns), 'warning')})" if warns else ""),
                              "cli_live", evidence=ev)
    if run.exit_code == EXIT["unreachable"]:
        ev["unreachable"] = True
        return B.BridgeResult("skipped", f"no Unity Editor with the Pipeline package was reachable: "
                                         f"{run.error_message()[:300] or 'unity recompile exit 7'}", "cli_live", evidence=ev)
    if run.exit_code == EXIT["failed"] and errs:
        p = B.parse_compile_output("", console_json={"data": [_console_entry(e) for e in errs]})
        n = p["errors"] or len(errs)
        ev.update({"errors": n, "root_causes": p["root_causes"]})
        return B.BridgeResult("fail", f"{_plural(n, 'compile error')} ({_plural(p['root_causes'] or n, 'root cause')})",
                              "cli_live", report=p["report"] or "\n".join(_console_entry(e)["message"] for e in errs[:40]),
                              errors=n, evidence=ev)
    if run.exit_code == EXIT["failed"] and "AMBIGUOUS" in run.error_code():
        return B.BridgeResult("skipped", f"several Unity Editors match: {run.error_message()[:300]}", "cli_live",
                              evidence=ev)
    return B.BridgeResult("error", f"`unity recompile` failed (exit {run.exit_code}): "
                                   f"{run.error_message()[:300] or 'no details'}", "cli_live",
                          report=run.stderr_tail[-2000:], evidence=ev)


MULTI_INSTANCE = "Multiple Unity instances cannot open the same project"


def result_from_run_compile(run: CliRun, route: str = "cli_batch") -> "BridgeResult":
    B = _bridge()
    text = run.log_text()
    ev: dict[str, Any] = {"route": route, "exit_code": run.exit_code, "cmd": run.cmd,
                          "log": str(run.log_path) if run.log_path else None, "error_code": run.error_code()}
    if run.cancelled:
        return B.BridgeResult("skipped", "the compile was cancelled", route, evidence=ev)
    if run.timed_out or run.error_code() in ("RUN_TIMED_OUT", "TIMED_OUT") or "timed out" in run.error_message().lower():
        return B.BridgeResult("skipped", "the batch compile timed out (a partial run never counts)", route, evidence=ev)
    if run.exit_code is None:
        return B.BridgeResult("skipped", f"the batch compile didn't run: {run.error or 'unknown'}", route, evidence=ev)
    if MULTI_INSTANCE in text:
        return B.BridgeResult("skipped", "Unity opened this project meanwhile (batch mode can't share it)", route,
                              evidence=ev)
    p = B.parse_compile_output(text)
    if p["errors"] or "Scripts have compiler errors." in text:
        n = p["errors"] or 1
        ev.update({"errors": n, "root_causes": p["root_causes"]})
        return B.BridgeResult("fail", f"{_plural(n, 'compile error')} ({_plural(p['root_causes'] or 1, 'root cause')})",
                              route, report=p["report"] or text[-4000:], errors=n, evidence=ev)
    if run.exit_code == 0:
        return B.BridgeResult("pass", "0 compile errors (batch)", route, evidence=ev)
    return B.BridgeResult("error", f"Unity batch mode failed without compile errors (exit {run.exit_code}"
                                   + (f": {run.error_message()[:200]}" if run.error_message() else "") + ")",
                          route, report=text[-2000:], evidence=ev)


def result_from_test_batch(run: CliRun, xml: Path, platform: str, route: str = "cli_batch") -> "BridgeResult":
    B = _bridge()
    from .ladder import parse_nunit
    mode = TEST_MODES.get((platform or "editmode").lower(), "EditMode")
    ev: dict[str, Any] = {"route": route, "platform": mode, "exit_code": run.exit_code, "cmd": run.cmd,
                          "xml": str(xml), "error_code": run.error_code()}
    if run.cancelled:
        return B.BridgeResult("skipped", "the test run was cancelled", route, evidence=ev)
    if run.timed_out or run.error_code() == "TEST_TIMED_OUT":
        return B.BridgeResult("skipped", "the test run timed out (a partial run never counts)", route, evidence=ev)
    if run.exit_code is None:
        return B.BridgeResult("skipped", f"the test run didn't start: {run.error or 'unknown'}", route, evidence=ev)
    r = None
    if run.exit_code in (0, EXIT["tests_failed"]) and xml.is_file():
        try:
            r = parse_nunit(xml)
        except (ValueError, OSError, Exception):  # noqa: BLE001 — a broken report is no verdict
            r = None
    if r is not None:
        ev.update({"total": r["total"], "passed": r["passed_n"], "failed": r["failed_n"], "failed_names": r["failed"][:30]})
        if r["failed_n"] or run.exit_code == EXIT["tests_failed"]:
            n = r["failed_n"] or 1
            return B.BridgeResult("fail", f"{_plural(n, 'failing test')} of {r['total']}", route,
                                  report="\n".join(f"FAILED {x}" for x in r["failed"][:30]), errors=n, evidence=ev)
        if r["total"] == 0:
            return B.BridgeResult("skipped", "no tests ran (an empty run never counts as a pass)", route, evidence=ev)
        return B.BridgeResult("pass", f"{r['passed_n']} tests passed", route, evidence=ev)
    if run.exit_code in (0, EXIT["tests_failed"]):
        return B.BridgeResult("error", "the test run ended without a readable results file", route, evidence=ev)
    text = run.log_text()
    p = B.parse_compile_output(text)
    if p["errors"]:
        ev["errors"] = p["errors"]
        return B.BridgeResult("fail", f"tests can't run: {_plural(p['errors'], 'compile error')}", route,
                              report=p["report"], errors=p["errors"], evidence=ev)
    if MULTI_INSTANCE in text:
        return B.BridgeResult("skipped", "Unity opened this project meanwhile (batch mode can't share it)", route,
                              evidence=ev)
    return B.BridgeResult("error", f"no test verdict (exit {run.exit_code}): {run.error_message()[:300] or 'see the log'}",
                          route, report=text[-2000:], evidence=ev)


def result_from_build(run: CliRun, route: str = "cli_batch") -> "BridgeResult":
    B = _bridge()
    data = run.data if isinstance(run.data, dict) else {}
    ev: dict[str, Any] = {"route": route, "exit_code": run.exit_code, "cmd": run.cmd, "error_code": run.error_code(),
                          "output": data.get("outputPath"), "log": str(run.log_path) if run.log_path else None,
                          "provenance": data.get("provenance")}
    if run.cancelled or run.exit_code in (EXIT["sigint"], EXIT["sigterm"]):
        return B.BridgeResult("skipped", "the build was cancelled", route, evidence=ev)
    if run.timed_out:
        return B.BridgeResult("skipped", "the build timed out", route, evidence=ev)
    if run.exit_code is None:
        return B.BridgeResult("skipped", f"the build didn't start: {run.error or 'unknown'}", route, evidence=ev)
    if run.exit_code == 0:
        return B.BridgeResult("pass", f"build succeeded → {data.get('outputPath') or 'output'}", route, evidence=ev)
    errs = data.get("editorErrors") or []
    report = "\n".join(str(e.get("message") if isinstance(e, dict) else e) for e in errs[:40]) if isinstance(errs, list) else ""
    return B.BridgeResult("fail", f"build failed (exit {run.exit_code}): {run.error_message()[:300] or 'see the log'}",
                          route, report=report or run.log_text()[-4000:], errors=len(errs) if isinstance(errs, list) else 1,
                          evidence=ev)


def _result_obj(env_data: Any) -> Any:
    """The Editor's own result inside a `unity command` / `job wait` envelope."""
    d = env_data
    for _ in range(4):
        if isinstance(d, dict):
            low = {str(k).lower(): v for k, v in d.items()}
            if "summary" in low or "results" in low:
                return d
            nxt = low.get("result") if "result" in low else low.get("data")
            if nxt is None:
                return d
            d = nxt
    return d


def result_from_job(run: CliRun, platform: str, route: str = "cli_live") -> "BridgeResult":
    """Live run_tests (Pipeline TestExecutionResponse: Summary{Total,Passed,Failed}, Results[{FullName,
    Status, Message}]) → BridgeResult. Field case varies by Pipeline version."""
    B = _bridge()
    mode = TEST_MODES.get((platform or "editmode").lower(), "EditMode")
    ev: dict[str, Any] = {"route": route, "platform": mode, "exit_code": run.exit_code, "cmd": run.cmd,
                          "error_code": run.error_code()}
    if run.cancelled:
        return B.BridgeResult("skipped", "the test run was cancelled", route, evidence=ev)
    if run.timed_out or run.exit_code is None:
        return B.BridgeResult("skipped", "tests didn't finish in time (a partial run never counts)", route, evidence=ev)
    obj = _lower_keys(_result_obj(run.data))
    if not isinstance(obj, dict) or ("summary" not in obj and "results" not in obj):
        return B.BridgeResult("error" if run.exit_code else "skipped",
                              f"the live test run gave no usable result (exit {run.exit_code}): "
                              f"{run.error_message()[:300] or 'unknown result shape'}", route,
                              report=run.stderr_tail[-1500:], evidence=ev)
    summ = obj.get("summary") or {}
    results = [r for r in obj.get("results") or [] if isinstance(r, dict)]
    failed = [r for r in results if str(r.get("status") or "").lower() == "failed"]
    total = _int(summ.get("total"))
    total = total if total is not None else len(results)
    n_failed = max(_int(summ.get("failed")) or 0, len(failed))
    n_passed = _int(summ.get("passed"))
    n_passed = n_passed if n_passed is not None else sum(1 for r in results if str(r.get("status") or "").lower() == "passed")
    n_other = (_int(summ.get("skipped")) or 0) + (_int(summ.get("inconclusive")) or 0)
    state = str(obj.get("state") or obj.get("status") or "").lower()
    complete = (run.exit_code == 0 and (run.envelope or {}).get("success", True) is not False
                and state not in ("running", "pending", "queued", "started", "in_progress", "cancelled", "timeout")
                and obj.get("success", True) is not False and n_passed + n_failed + n_other >= total)
    passed_names = [str(r.get("fullname") or r.get("name")) for r in results if str(r.get("status") or "").lower() == "passed"]
    failed_names = [str(r.get("fullname") or r.get("name") or "?") for r in failed]
    ev.update({"total": total, "passed": n_passed, "failed": n_failed, "failed_names": failed_names[:30],
               "passed_names": passed_names[:500]})
    if obj.get("error") and not results:
        return B.BridgeResult("error", f"the live test run failed: {str(obj['error'])[:300]}", route, evidence=ev)
    ev["complete"] = complete
    if n_failed:
        msgs = [f"FAILED {str(r.get('fullname') or r.get('name') or '?')} :: {str(r.get('message') or '')[:300]}"
                for r in failed[:30]]
        return B.BridgeResult("fail", f"{_plural(n_failed, 'failing test')} of {total}", route, report="\n".join(msgs),
                              errors=n_failed, evidence=ev)
    if not complete:
        return B.BridgeResult("skipped", f"the live test run didn't complete (exit {run.exit_code}"
                                         f"{', ' + state if state else ''}): a partial run never counts", route,
                              report=run.stderr_tail[-1500:], evidence=ev)
    if not total:
        return B.BridgeResult("skipped", "no tests ran (an empty run never counts as a pass)", route, evidence=ev)
    return B.BridgeResult("pass", f"{n_passed or total} tests passed", route, evidence=ev)


def find_command(catalog: Any, *names: str) -> str | None:
    """The first of `names` the Editor's command listing offers (group commands as "group name")."""
    found: set[str] = set()

    def walk(o: Any, group: str = "") -> None:
        if isinstance(o, dict):
            low = {str(k).lower(): v for k, v in o.items()}
            n = low.get("name") or low.get("command")
            g = low.get("group") or group
            if isinstance(n, str):
                found.add(n)
                if isinstance(g, str) and g:
                    found.add(f"{g} {n}")
                    found.add(f"{g.replace('.', ' ')} {n}")
            for v in o.values():
                walk(v, g if isinstance(g, str) else group)
        elif isinstance(o, list):
            for v in o:
                walk(v, group)

    walk(catalog)
    return next((n for n in names if n in found), None)


__all__ = ["BACKENDS", "CLI_CANDIDATES", "CLI_ENV", "CliRun", "CliStatus", "DEFAULTS", "EXIT", "LiveState",
           "UnityCliInfo", "UnityRunner", "argv_build", "argv_close", "argv_command", "argv_command_list", "argv_job",
           "argv_open", "argv_pipeline_install", "argv_pipeline_list", "argv_recompile", "argv_run_batch",
           "argv_self_update", "argv_status", "argv_test_batch", "cli_env", "find_command", "find_editor_binary",
           "find_unity_cli", "get_runner", "live_state", "mcp_in_manifest", "parse_envelope", "pipeline_in_manifest",
           "project_editor_version", "result_from_build", "result_from_job", "result_from_recompile",
           "result_from_run_compile", "result_from_test_batch", "safe_mode_errors", "unity_cfg", "version_at_least"]
