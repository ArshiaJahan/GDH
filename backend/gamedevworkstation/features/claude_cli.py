"""The user's own `claude` CLI: where it is, the environment it runs in, and whether it's logged in.

GameDevWorkstation only ever launches the unmodified `claude` binary the user installed, and only
with the user's own Claude login (subscription or CLI-managed API key). It never reads, copies or stores anything
from ~/.claude or the Keychain: login happens when the user runs `claude auth login` in a terminal.

- `find_cli(config)`: [claude_code].cli_path, else PATH, ~/.local/bin, ~/.claude/local,
  /opt/homebrew/bin. GDW_CLAUDE_CLI_SEARCH=0 (tests) turns the search off: only cli_path.
- `child_env()`: an allowlist of shell, locale, proxy and desktop environment variables, plus
  MCP_TOOL_TIMEOUT. Provider credentials and arbitrary application secrets never reach the child.
- `probe(config)`: path, `claude --version` and the JSON of `claude auth status` (run with
  child_env(), so what it reports is what a session will use). Cached for CACHE_S.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

ENV_NAMES = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR", "TZ",
             "SSH_AUTH_SOCK", "__CF_USER_TEXT_ENCODING"}
PROXY_NAMES = {"http_proxy", "https_proxy", "no_proxy", "all_proxy"}
# A GDW tool call or approval card can wait on the user for a long time; the CLI's MCP tool timeout
# (MCP_TOOL_TIMEOUT, milliseconds [docs]) must not cut that short.
MCP_TOOL_TIMEOUT_MS = 24 * 3600 * 1000
CACHE_S = 60.0
SEARCH_DIRS = ("~/.local/bin", "~/.claude/local", "/opt/homebrew/bin")
LOGIN_HINT = "Run `claude auth login` in a terminal, then retry."
_SECRETISH = re.compile(r"token|secret|key|password|credential", re.I)
# Account details `claude auth status` reports when logged in [live]; GDW has no use for them.
PERSONAL = frozenset({"email", "orgId", "orgName", "organization", "accountUuid", "organizationUuid"})
_ERROR_SECRET = re.compile(r"Bearer\s+\S+|sk-[A-Za-z0-9_-]{10,}", re.I)


def redact(text: str, token: str = "") -> str:
    """Sanitize CLI diagnostics before they enter logs, storage or the UI."""
    if token:
        text = text.replace(token, "[REDACTED]")
    return _ERROR_SECRET.sub("[REDACTED]", text)


def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for every `claude` process GDW starts (sessions and probes)."""
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if k in ENV_NAMES or k.startswith(("LC_", "XDG_")) or k.lower() in PROXY_NAMES}
    env["MCP_TOOL_TIMEOUT"] = str(MCP_TOOL_TIMEOUT_MS)
    return env


def _cfg(config: Any) -> dict:
    return dict(getattr(config, "claude_code", None) or {})


def find_cli(config: Any) -> str | None:
    """The `claude` executable: [claude_code].cli_path, else the search list (unless turned off)."""
    want = str(_cfg(config).get("cli_path") or "").strip()
    if want:
        p = Path(want).expanduser()
        return str(p) if p.is_file() and os.access(p, os.X_OK) else None
    if os.environ.get("GDW_CLAUDE_CLI_SEARCH") == "0":
        return None
    if found := shutil.which("claude"):
        return found
    for d in SEARCH_DIRS:
        p = Path(d).expanduser() / "claude"
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def _scrub(d: Any) -> Any:
    """`claude auth status` output for the UI, minus anything that looks like a credential or names the account."""
    if isinstance(d, dict):
        return {k: _scrub(v) for k, v in d.items()
                if (not _SECRETISH.search(str(k)) or k in ("authMethod",)) and k not in PERSONAL}
    if isinstance(d, list):
        return [_scrub(x) for x in d]
    return redact(d) if isinstance(d, str) else d


async def _run(argv: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env=child_env(), start_new_session=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return -1, "", "timed out"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def logged_in(auth: dict | None) -> bool:
    """`claude auth status` JSON → logged in. Observed (2.1.308): {"loggedIn": false, "authMethod": "none", ...}
    and, logged in with a subscription, {"loggedIn": true, "authMethod": "claude.ai", "apiProvider":
    "firstParty", "subscriptionType": "max", "email": ..., "orgId": ..., "orgName": ...}. A few other
    spellings are still accepted in case a later CLI renames the field."""
    if not isinstance(auth, dict):
        return False
    for k in ("loggedIn", "logged_in", "authenticated"):
        if k in auth:
            return bool(auth[k])
    m = str(auth.get("authMethod") or "").lower()
    return bool(m) and m != "none"


def bills_api(auth: dict | None) -> bool:
    """True when the CLI says it would use an API key (not the subscription) even with GDW's clean env,
    e.g. an apiKeyHelper in managed settings. Observed values: "none" and "claude.ai" (subscription,
    so False); the API key spellings below weren't observed (no API key login was tried)."""
    m = str((auth or {}).get("authMethod") or "").lower().replace("-", "_").replace(" ", "_")
    return m in ("api_key", "apikey", "api_key_helper", "apikeyhelper", "console", "anthropic_api_key")


class CliProbe:
    """Cached `claude` status for the UI and the harness."""

    def __init__(self, config: Any):
        self.config = config
        self._cache: dict | None = None
        self._at = 0.0
        self._lock = asyncio.Lock()

    def cached(self) -> dict | None:
        return self._cache

    async def status(self, refresh: bool = False) -> dict:
        async with self._lock:
            if not refresh and self._cache and time.monotonic() - self._at < CACHE_S \
                    and self._cache.get("path") == find_cli(self.config):
                return self._cache
            self._cache = await self._probe()
            self._at = time.monotonic()
            return self._cache

    def forget(self) -> None:
        self._cache = None

    async def _probe(self) -> dict:
        path = find_cli(self.config)
        out: dict[str, Any] = {"installed": bool(path), "path": path, "version": None, "logged_in": False,
                               "auth_method": None, "auth": None, "bills_api": False, "error": None,
                               "checked_at": time.time(), "login_hint": LOGIN_HINT}
        if not path:
            want = str(_cfg(self.config).get("cli_path") or "").strip()
            out["error"] = (f"[claude_code].cli_path {want} isn't an executable file." if want else
                            "The claude CLI wasn't found (PATH, ~/.local/bin, ~/.claude/local, /opt/homebrew/bin).")
            return out
        try:
            code, so, se = await _run([path, "--version"])
            out["version"] = (so.strip().splitlines() or [""])[0] or None if code == 0 else None
            code, so, se = await _run([path, "auth", "status"])
            try:
                auth = json.loads(so)
            except json.JSONDecodeError:
                auth = None
            if isinstance(auth, dict):
                out["auth"] = _scrub(auth)
                out["logged_in"] = logged_in(auth)
                out["auth_method"] = auth.get("authMethod")
                out["bills_api"] = bills_api(auth)
            else:
                out["error"] = f"`claude auth status` gave no JSON (exit {code}): {redact((se or so).strip())[:300]}"
        except OSError as e:
            out["error"] = redact(f"Couldn't run {path}: {e}")
        return out


def version_tuple(v: str | None) -> tuple[int, ...]:
    m = re.match(r"(\d+(?:\.\d+)*)", (v or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()
