"""Load and evaluate tool access rules without coupling policy to dispatch."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SAFE_WHEN_BROKEN = frozenset({"read_file", "list_dir", "search", "get_item", "list_items", "read_output", "read_skill"})


# Claude Code's own read-only built-ins: the only ones its gate lets through while the policy is malformed.
CC_SAFE_WHEN_BROKEN = frozenset({"Read", "Glob", "Grep", "LS", "NotebookRead"})


class PolicyError(ValueError):
    """Raised when a policy contains an unsupported or invalid value."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


def default_policy_path() -> Path:
    return Path(__file__).with_name("default_tool_policy.toml")


def user_policy_path() -> Path:
    from .config import data_dir

    return data_dir() / "tool_policy.toml"


def _table(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise PolicyError(f"{name} must be a table")
    return value


def _keys(table: dict, allowed: set[str], name: str) -> None:
    extra = set(table) - allowed
    if extra:
        raise PolicyError(f"unknown key in {name}: {sorted(extra)[0]}")


def _patterns(table: dict, key: str, name: str) -> None:
    if key not in table:
        return
    value = table[key]
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise PolicyError(f"{name}.{key} must be a list of non-empty strings")


def validate(data: dict) -> dict:
    if not isinstance(data, dict):
        raise PolicyError("policy must be a table")
    if data.get("version") != 1 or isinstance(data.get("version"), bool):
        raise PolicyError("version must be 1")
    _keys(data, {"version", "defaults", "agents", "mcp", "egress"}, "top-level table")
    if "defaults" in data:
        defaults = _table(data["defaults"], "defaults")
        _keys(defaults, {"unlisted"}, "defaults")
        if "unlisted" in defaults and (
            not isinstance(defaults["unlisted"], str) or defaults["unlisted"] not in {"allow", "deny"}
        ):
            raise PolicyError("defaults.unlisted must be 'allow' or 'deny'")
    if "agents" in data:
        agents = _table(data["agents"], "agents")
        _keys(agents, {"main", "claude_code", "subagent"}, "agents")
        for agent, raw in agents.items():
            table = _table(raw, f"agents.{agent}")
            keys = {"allow", "deny", "builtin_deny"} | ({"job_types"} if agent == "subagent" else set())
            _keys(table, keys, f"agents.{agent}")
            for key in ("allow", "deny", "builtin_deny"):
                _patterns(table, key, f"agents.{agent}")
            if "job_types" in table:
                jobs = _table(table["job_types"], "agents.subagent.job_types")
                for job, raw_job in jobs.items():
                    job_table = _table(raw_job, f"agents.subagent.job_types.{job}")
                    _keys(job_table, {"allow", "deny"}, f"agents.subagent.job_types.{job}")
                    for key in ("allow", "deny"):
                        _patterns(job_table, key, f"agents.subagent.job_types.{job}")
    if "mcp" in data:
        mcp = _table(data["mcp"], "mcp")
        _keys(mcp, {"servers"}, "mcp")
        if "servers" in mcp:
            servers = _table(mcp["servers"], "mcp.servers")
            for server, raw in servers.items():
                table = _table(raw, f"mcp.servers.{server}")
                _keys(table, {"trust_read_only_hint", "scan_args"}, f"mcp.servers.{server}")
                for key, value in table.items():
                    if not isinstance(value, bool):
                        raise PolicyError(f"mcp.servers.{server}.{key} must be a bool")
    if "egress" in data:
        egress = _table(data["egress"], "egress")
        _keys(egress, {"scan_web_fetch", "extra_patterns"}, "egress")
        if "scan_web_fetch" in egress and not isinstance(egress["scan_web_fetch"], bool):
            raise PolicyError("egress.scan_web_fetch must be a bool")
        if "extra_patterns" in egress:
            patterns = egress["extra_patterns"]
            if not isinstance(patterns, list) or any(not isinstance(x, str) for x in patterns):
                raise PolicyError("egress.extra_patterns must be a list of strings")
            try:
                for pattern in patterns:
                    re.compile(pattern)
            except re.error as exc:
                raise PolicyError(f"egress.extra_patterns contains invalid regex: {exc}") from exc
    return data


def merge(default: dict, user: dict) -> dict:
    result = dict(default)
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


class ToolPolicy:
    def __init__(self, data: dict | None, *, path: Path | None = None, broken: str | None = None):
        self.data = data
        self.path = path or user_policy_path()
        self.broken = broken

    def decide(self, agent: str, tool: str, *, job_type: str | None = None) -> Decision:
        if self.broken:
            if tool in SAFE_WHEN_BROKEN:
                return Decision(True)
            return Decision(False, f"tool policy is malformed: {self.broken}; fix or delete {self.path}")
        if agent == "hook":
            agent = "main"
        if agent not in {"main", "claude_code", "subagent"}:
            return Decision(False, f"unknown agent {agent}")
        data = self.data or {}
        rules = data.get("agents", {}).get(agent, {})
        allow, deny = rules.get("allow", []), list(rules.get("deny", []))
        job_allow = None
        if agent == "subagent" and job_type is not None:
            job = rules.get("job_types", {}).get(job_type)  # an unknown job type is the agent level only
            if job is not None:
                # A job type only narrows the agent-level rules: denies are the union, allows the intersection.
                job_allow = job.get("allow", [])
                deny += job.get("deny", [])
        for pattern in deny:
            if fnmatch.fnmatchcase(tool, pattern):
                return Decision(False, f"denied by policy rule '{pattern}'")
        if any(fnmatch.fnmatchcase(tool, pattern) for pattern in allow):
            if job_allow is not None and not any(fnmatch.fnmatchcase(tool, pattern) for pattern in job_allow):
                return Decision(False, f"not in the allow list for {job_type} units")
            return Decision(True)
        if data.get("defaults", {}).get("unlisted", "deny") == "allow":
            if job_allow is not None and not any(fnmatch.fnmatchcase(tool, pattern) for pattern in job_allow):
                return Decision(False, f"not in the allow list for {job_type} units")
            return Decision(True)
        return Decision(False, f"not in the allow list for {agent}")

    def filter_names(self, agent: str, names: Iterable[str], *, job_type: str | None = None) -> list[str]:
        return [name for name in names if self.decide(agent, name, job_type=job_type).allowed]

    def cc_broken_refusal(self, claude_code_tool: str) -> str | None:
        """Why a Claude Code built-in is refused while the policy is malformed (fail closed), else None."""
        if self.broken and claude_code_tool not in CC_SAFE_WHEN_BROKEN:
            return f"{claude_code_tool} is not allowed: tool policy is malformed: {self.broken}; fix or delete {self.path}"
        return None

    def builtin_denied(self, claude_code_tool: str) -> bool:
        return any(fnmatch.fnmatchcase(claude_code_tool, pat) for pat in (self.data or {}).get("agents", {}).get("claude_code", {}).get("builtin_deny", []))

    def _mcp_setting(self, server: str, key: str, default: bool) -> bool:
        servers = (self.data or {}).get("mcp", {}).get("servers", {})
        return servers.get(server, servers.get("default", {})).get(key, default)

    def mcp_trust_read_only(self, server: str, builtin: bool = False) -> bool:
        """A server's readOnlyHint is believed only for GDH's own built-in server (`builtin`, decided by how
        GDH registers it, never by the name) or when tool_policy.toml opts that server in."""
        return builtin or self._mcp_setting(server, "trust_read_only_hint", False)

    def mcp_scan_args(self, server: str) -> bool:
        return self._mcp_setting(server, "scan_args", True)

    def egress_scan_web_fetch(self) -> bool:
        return (self.data or {}).get("egress", {}).get("scan_web_fetch", True)

    def egress_extra_patterns(self) -> list[re.Pattern]:
        return [re.compile(pattern) for pattern in (self.data or {}).get("egress", {}).get("extra_patterns", [])]

    def fingerprint(self) -> str:
        if self.broken:
            return "broken:" + self.broken
        payload = json.dumps(self.data, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_policy(user_path: Path | None = None, *, default_path: Path | None = None) -> ToolPolicy:
    packaged = default_path or default_policy_path()
    try:
        with packaged.open("rb") as handle:
            base = validate(tomllib.load(handle))
    except Exception as exc:
        return ToolPolicy(None, path=packaged, broken=f"{packaged}: {exc}")
    if user_path is None:
        return ToolPolicy(base)
    try:
        if user_path.exists():
            with user_path.open("rb") as handle:
                override = validate(tomllib.load(handle))
            return ToolPolicy(validate(merge(base, override)), path=user_path)
        return ToolPolicy(base, path=user_path)
    except Exception as exc:
        return ToolPolicy(None, path=user_path, broken=f"{user_path}: {exc}")


class PolicyHolder:
    def __init__(self, user_path: Path | None, default_path: Path | None = None):
        self.user_path = user_path
        self.default_path = default_path
        self._signature = object()
        self._policy = None

    def current(self) -> ToolPolicy:
        try:
            stat = self.user_path.stat() if self.user_path is not None else None
            signature = (stat.st_mtime_ns, stat.st_size) if stat else None
        except OSError:
            signature = ("unreadable",)
        if signature != self._signature:
            self._policy = load_policy(self.user_path, default_path=self.default_path)
            self._signature = signature
        return self._policy
