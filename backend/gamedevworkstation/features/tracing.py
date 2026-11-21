"""Record bounded metadata while keeping trace failures out of application outcomes."""
from __future__ import annotations

import asyncio
import json
import math
import random
import re
import secrets
import time
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import IntEnum
from threading import Lock
from typing import TYPE_CHECKING, get_args

from fastapi import APIRouter, FastAPI, HTTPException, Query

from ..config import _defaults
from ..core.types import EFFORT_LEVELS, StopReason
from .claude_cli import redact
from .skill_assistant import SECRET_VALUE, _looks_secret
from .trace_store import TraceRow, TraceStore

if TYPE_CHECKING:
    from ..app import AppState

MAX_ATTRIBUTES = 24
MAX_ATTRIBUTE_BYTES = 2 * 1024
_INT64_MAX = 2**63 - 1
_CURRENT_PARENT = object()
_SESSION_ID = re.compile(r"ses_[0-9a-f]{16}")
_RUN_ID = re.compile(
    r"(?:(?:main|compact|gate|hook|title):ses_|(?:sub|run|asst|gate|rr)_|campaign:cmp_|gallery:shot_)[0-9a-f]{16}"
    r"|pi:ses_[0-9a-f]{16}:msg_[0-9a-f]{16}"
    r"|(?:review-desk|triage|eval|eval-forge|eval-rubric)-[0-9a-f]{8}"
    r"|rr_eval[0-9a-f]{12}"
)
_JOB_ID = re.compile(r"job_[0-9a-f]{16}")
_TRACE_ID = re.compile(r"(?!0{32})[0-9a-f]{32}")
_SPAN_ID = re.compile(r"(?!0{16})[0-9a-f]{16}")
_CURSOR = re.compile(r"([0-9]{1,19}):([0-9a-f]{16})")
_CODE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}")
_CONVERSATION_ATTR = "gen_ai.conversation.id"
_RUN_ATTR = "gdw.run.id"
_ROLE = frozenset({"main", "orchestrator", "subagent", "assistant", "tool", "helper"})
_HARNESS = frozenset({"builtin", "claude_code", "agent_sdk", "codex_cli"})
_OPERATIONS = frozenset({"invoke_agent", "chat", "execute_tool"})
_MCP_METHODS = frozenset({"initialize", "tools/list", "tools/call"})
_CATEGORIES = frozenset({"turn", "session", "agent", "subagent", "model", "tool", "mcp", "harness"})
_NAMES = _CATEGORIES | _OPERATIONS | _MCP_METHODS | {"session_turn", "subagent_run", "model_attempt"}
_OK = frozenset({"ok", "success", "completed"})
_UNSET = frozenset({"unknown", "incomplete", "paused", "prompt_improver_pause"})
_ERROR = frozenset({"error", "failed", "cancelled", "timeout", "interrupted", "denied", "declined", "refusal",
                    "effort_declined", "gate_exhausted", "harness_failure", "budget_exceeded", "process_exit"})
_OUTCOMES = _OK | _UNSET | _ERROR
_OUTCOME_BYTES = len('"gdw.outcome":"",') + max(map(len, _OUTCOMES)) + 2
_MAX_CODE_LENGTH = 64
_FINISH_REASONS = frozenset(get_args(StopReason))

_ENUMS = {
    "gen_ai.operation.name": _OPERATIONS,
    "gen_ai.agent.name": _ROLE,
    "gen_ai.provider.name": frozenset({"anthropic", "openai"}),
    "mcp.method.name": _MCP_METHODS,
    "gdw.mcp.direction": frozenset({"inbound", "outbound"}),
    "gdw.mcp.transport": frozenset({"stdio", "sse", "streamable_http", "http"}),
    "gdw.harness": _HARNESS,
    "gdw.role": _ROLE,
    "gdw.effort": frozenset(EFFORT_LEVELS),
    "gdw.visibility": frozenset({"harness"}),
    "gdw.routing.job_type": frozenset({"extract", "mechanical_edit", "implement_feature", "other"}),
    "gdw.routing.reason": frozenset({"auto", "pinned", "cheapest", "standard", "transient_error", "context_overflow",
                                     "failed_check", "routing_disabled"}),
    "error.type": _ERROR | {"auth", "rate_limit", "context_overflow", "provider_error", "tool_error", "rpc_error",
                            "unavailable", "invalid_request", "missing_key", "policy_denied", "other"},
}
_COUNTERS = (
    "gen_ai.request.max_tokens", "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
    "gen_ai.usage.cache_read.input_tokens", "gen_ai.usage.cache_creation.input_tokens",
    "gen_ai.usage.reasoning.output_tokens", "gdw.routing.escalation",
)
_IDS = {_CONVERSATION_ATTR: _SESSION_ID, _RUN_ATTR: _RUN_ID, "gdw.job.id": _JOB_ID,
        "gdw.routing.policy_revision": re.compile(r"[0-9]{1,9}")}
_MODEL_ATTRS = ("gen_ai.request.model", "gen_ai.response.model")
_KNOWN_ATTRS = (*_ENUMS, *_COUNTERS, *_IDS, *_MODEL_ATTRS, "gen_ai.tool.name", "gen_ai.response.finish_reasons",
                "gdw.queue_ms", "gdw.routing.selected_tier")


class SpanKind(IntEnum):
    UNSPECIFIED = 0
    INTERNAL = 1
    SERVER = 2
    CLIENT = 3
    PRODUCER = 4
    CONSUMER = 5


@dataclass(frozen=True, slots=True)
class SpanRef:
    """Carry parent identity across tasks, including a root's decision to skip sampling."""

    _owner: object
    trace_id: str | None
    span_id: str | None
    session_id: str | None
    run_id: str | None


_current_span: ContextVar[SpanRef | None] = ContextVar("gdw_trace_span", default=None)


def bind(span: "Span") -> None:
    """Make `span` the parent of spans started later in the current task. A task's own context, so no reset."""
    _current_span.set(span.ref)


def _match(pattern: re.Pattern, value: object) -> str | None:
    return value if type(value) is str and pattern.fullmatch(value) else None


def _safe_model_id(name: str) -> bool:
    """Catalog membership alone would admit a credential pasted in as a model ID."""
    if not _match(_CODE_NAME, name) or name.lower().startswith(("sk-", "sk_")) or _looks_secret(name):
        return False
    # Apply the CLI key pattern to the underscore spelling as well.
    sk_value = name.lower().replace("sk_", "sk-")
    if redact(sk_value) != sk_value:
        return False
    # Match at the start of each suffix so a model prefix cannot hide a known key format.
    return not any(SECRET_VALUE.match(name[i:]) for i in range(1, len(name)))


def _context_id(key: str, explicit: str | None, attrs: Mapping[str, object] | None,
                inherited: str | None) -> str | None:
    pattern = _IDS[key]
    if value := _match(pattern, explicit):
        return value
    if attrs is not None:
        try:
            if value := _match(pattern, attrs.get(key)):
                return value
        except Exception:
            pass  # Bad metadata must not stop the span from inheriting a valid ID.
    return _match(pattern, inherited)


def _known(value: object, choices: frozenset) -> bool:
    return type(value) is str and len(value) <= _MAX_CODE_LENGTH and value in choices


def _hex_id(size: int) -> str:
    while True:
        value = secrets.token_hex(size)
        if value != "0" * (size * 2):
            return value


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class Span:
    def __init__(self, recorder: TraceRecorder, ref: SpanRef, parent_span_id: str | None = None,
                 name: str = "span", category: str = "other", kind: int = SpanKind.INTERNAL):
        self._ref = ref
        self._recorder = recorder
        self._parent_id = parent_span_id
        self._name = name
        self._category = category
        self._kind = int(kind)
        self._start_ns = time.time_ns() if ref.span_id else 0
        self._start_mono = time.monotonic_ns() if ref.span_id else 0
        self._lock = Lock()
        self._attrs: dict = {}
        self._sizes: dict[str, int] = {}
        self._dropped = 0
        self._ended = False

    @property
    def ref(self) -> SpanRef:
        return self._ref

    def _set(self, key: str, value: object) -> bool:
        value = self._recorder._attribute(key, value)
        if value is None:
            return False
        if ((key == _CONVERSATION_ATTR and value != self.ref.session_id)
                or (key == _RUN_ATTR and value != self.ref.run_id)):
            return False
        size = len(_json({key: value}).encode("utf-8")) - 1
        # Reserve room for the final outcome even if metadata fills the span first.
        if key not in self._attrs and len(self._attrs) >= MAX_ATTRIBUTES - 1:
            return False
        if sum(self._sizes.values()) - self._sizes.get(key, 0) + size + _OUTCOME_BYTES > MAX_ATTRIBUTE_BYTES:
            return False
        self._attrs[key] = value
        self._sizes[key] = size
        return True

    def set_attribute(self, key: str, value: object) -> None:
        if self.ref.span_id:
            with self._lock:
                if not self._ended:
                    if type(key) is not str or len(key) > _MAX_CODE_LENGTH or not self._set(key, value):
                        self._dropped += 1

    def set_attributes(self, attrs: Mapping[str, object]) -> None:
        if self.ref.span_id:
            with self._lock:
                if self._ended:
                    return
                # Inspect only the fixed keys even when a caller supplies a large mapping.
                try:
                    self._dropped += len(attrs)
                    for key in _KNOWN_ATTRS:
                        if key in attrs and self._set(key, attrs[key]):
                            self._dropped -= 1
                except Exception:
                    pass  # A malformed metadata mapping must not affect its operation.

    def end(self, outcome: str = "ok") -> None:
        if not self.ref.span_id:
            return
        try:
            with self._lock:
                if self._ended:
                    return
                self._ended = True
                outcome = outcome if _known(outcome, _OUTCOMES) else "unknown"
                status = 1 if outcome in _OK else 2 if outcome in _ERROR else 0
                self._attrs["gdw.outcome"] = outcome
                end_ns = self._start_ns + max(0, time.monotonic_ns() - self._start_mono)
                row = TraceRow(self.ref.trace_id, self.ref.span_id, self._parent_id, self.ref.session_id, self.ref.run_id,
                               self._name, self._category, self._kind, self._start_ns, end_ns, status,
                               _json(self._attrs), min(self._dropped, 2**32 - 1))
            self._recorder._store.enqueue(row)
        except Exception:
            self._recorder._store.count("dropped_spans")


class TraceRecorder:
    def __init__(self, settings: dict, *, tool_names: Iterable[str] = (), model_names: Iterable[str] = ()):
        self._store = TraceStore(settings)
        rate = settings.get("sample_rate", 1.0)
        self._sample_rate = rate if type(rate) in (float, int) and 0 <= rate <= 1 else 1.0
        self._owner = object()
        self._skipped = Span(self, SpanRef(self._owner, None, None, None, None))
        self._registered_tools = tool_names
        self._registered_models = model_names
        self._tools: frozenset[str] = frozenset()
        self._models: frozenset[str] = frozenset()
        self._tiers: frozenset[str] = frozenset()

    @property
    def available(self) -> bool:
        return self._store.available

    async def astart(self) -> None:
        if self._store.enabled:
            self._tools = frozenset(name for name in self._registered_tools if _match(_CODE_NAME, name))
            self._models = frozenset(name for name in self._registered_models if _safe_model_id(name))
            try:
                self._tiers = frozenset(name for name in _defaults().get("tiers", {}) if _match(_CODE_NAME, name))
            except (OSError, ValueError):
                pass  # Unknown tiers are redacted even without the packaged defaults.
        await self._store.astart()

    async def aclose(self) -> None:
        await self._store.aclose()

    def health(self) -> dict:
        return self._store.health()

    def capture(self) -> SpanRef | None:
        ref = _current_span.get()
        return ref if ref is not None and ref._owner is self._owner else None

    def start(self, name: str, *, category: str = "other", kind: int = SpanKind.INTERNAL,
              session_id: str | None = None, run_id: str | None = None, attrs: Mapping[str, object] | None = None,
              parent: SpanRef | None | object = _CURRENT_PARENT) -> Span:
        """Open a handle without binding it to a task. Pass parent=None to force a new root.

        Resolve session and run IDs from valid arguments, creation attributes, or the parent, in that order.
        """
        try:
            if not self._store.accepting:
                return self._skipped
            if parent is _CURRENT_PARENT:
                parent = self.capture()
            if not isinstance(parent, SpanRef) or parent._owner is not self._owner:
                parent = None
            parent_span_id = None
            if parent is not None:
                if parent.trace_id is None and parent.span_id is None:
                    return self._skipped
                trace_id = _match(_TRACE_ID, parent.trace_id)
                parent_span_id = _match(_SPAN_ID, parent.span_id)
                if trace_id is None or parent_span_id is None:
                    self._store.count("dropped_spans")
                    return self._skipped
            elif self._sample_rate < 1 and random.random() >= self._sample_rate:
                self._store.count("sampled_out")
                return self._skipped
            else:
                trace_id = _hex_id(16)
            ref = SpanRef(self._owner, trace_id, _hex_id(8),
                          _context_id(_CONVERSATION_ATTR, session_id, attrs, parent.session_id if parent else None),
                          _context_id(_RUN_ATTR, run_id, attrs, parent.run_id if parent else None))
            category = category if _known(category, _CATEGORIES) else "other"
            if not (_known(name, _NAMES) or (category == "tool" and _known(name, self._tools))):
                name = category if category != "other" else "span"
            if not (type(kind) is int or isinstance(kind, SpanKind)) or not 0 <= kind <= 5:
                kind = SpanKind.INTERNAL
            span = Span(self, ref, parent_span_id, name, category, kind)
            if ref.session_id is not None:
                span.set_attribute(_CONVERSATION_ATTR, ref.session_id)
            if ref.run_id is not None:
                span.set_attribute(_RUN_ATTR, ref.run_id)
            if attrs is not None:
                span.set_attributes(attrs)
            return span
        except Exception:
            self._store.count("dropped_spans")
            return self._skipped

    @contextmanager
    def span(self, name: str, **kwargs):
        """Bind the span's parent reference for nested calls and task creation."""
        span = self.start(name, **kwargs)
        token = _current_span.set(span.ref)
        outcome = "ok"
        try:
            yield span
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except BaseException:
            outcome = "error"
            raise
        finally:
            _current_span.reset(token)
            span.end(outcome)

    def _attribute(self, key: str, value: object):
        if key in _ENUMS:
            return value if _known(value, _ENUMS[key]) else None
        if key in _COUNTERS:
            return value if type(value) is int and 0 <= value <= _INT64_MAX else None
        if key in _IDS:
            return _match(_IDS[key], value)
        if key in _MODEL_ATTRS:
            if type(value) is str:
                return value if _known(value, self._models) else "unknown"
        if key == "gen_ai.tool.name" and type(value) is str:
            return value if _known(value, self._tools) else "external"
        if key == "gen_ai.response.finish_reasons" and type(value) in (list, tuple) and 0 < len(value) <= 8:
            reasons = tuple(value[:8])
            if reasons and all(_known(item, _FINISH_REASONS) for item in reasons):
                return reasons
        if key == "gdw.queue_ms" and type(value) in (int, float) and 0 <= value <= _INT64_MAX and math.isfinite(value):
            return value
        if key == "gdw.routing.selected_tier" and type(value) is str:
            return value if _known(value, self._tiers) else "other"
        return None


def _decode_cursor(value: str | None) -> tuple[int, str] | None:
    if value is None:
        return None
    match = _CURSOR.fullmatch(value)
    if match and (start_ns := int(match[1])) <= _INT64_MAX:
        return start_ns, match[2]
    raise HTTPException(422, "Invalid trace cursor")


def _page(store: TraceStore, limit: int, cursor: str | None, *,
          session_id: str | None = None, trace_id: str | None = None) -> tuple[list[dict], str | None]:
    rows = store.page(session_id=session_id, trace_id=trace_id, cursor=_decode_cursor(cursor), limit=limit)
    next_cursor = None
    if len(rows) > limit:
        rows.pop()
        last = rows[-1]
        next_cursor = f"{last['start_ns']}:{last['span_id']}"
    return rows, next_cursor


def register(app: FastAPI, api: APIRouter, S: AppState) -> None:
    @api.get("/traces")
    def traces(session_id: str | None = None, limit: int = Query(50, ge=1, le=200),
               cursor: str | None = None) -> dict:
        rows, next_cursor = _page(S.tracing._store, limit, cursor, session_id=session_id)
        return {"traces": rows, "next_cursor": next_cursor, "health": S.tracing.health()}

    @api.get("/traces/{trace_id}")
    def trace(trace_id: str, limit: int = Query(50, ge=1, le=200), cursor: str | None = None) -> dict:
        if not _TRACE_ID.fullmatch(trace_id):
            raise HTTPException(422, "Invalid trace ID")
        rows, next_cursor = _page(S.tracing._store, limit, cursor, trace_id=trace_id)
        if not rows and cursor is None:
            raise HTTPException(404, "Trace not found")
        return {"trace_id": trace_id, "spans": rows, "next_cursor": next_cursor,
                "missing_parent": any(row["missing_parent"] for row in rows)}
