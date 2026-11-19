"""Prompt improver: frozen data contracts (pure Pydantic, no I/O). See docs/plans/prompt-improver-contracts.md."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

SCHEMA_VERSION = 1
TEMPLATE_VERSION = "pi-eval-1"
COLLECTOR_VERSION = "pi-facts-1"
MAX_QUESTIONS = 3
UNKNOWN = "unknown"

Topic = Literal["target", "platform_input", "acceptance", "feel", "assets", "performance", "multiplayer", "bug_replay"]
TOPICS: tuple[str, ...] = ("target", "platform_input", "acceptance", "feel", "assets", "performance", "multiplayer", "bug_replay")
Decision = Literal["PROCEED", "ASK"]
Status = Literal["proceeded", "asked", "bypassed", "unavailable", "paused"]
VerifyType = Literal["compile", "editmode_test", "playmode_test", "play_signal", "screenshot", "replay", "manual"]
Ladder = Literal["L1", "L2", "L3", "L4", "manual"]

# Text passed through verbatim: the user's own words keep their leading and trailing spaces.
RawStr = Annotated[str, StringConstraints(strip_whitespace=False)]

_ID = r"^[a-z0-9][a-z0-9_\-]{0,39}$"


class PiFormatError(ValueError):
    """The evaluator's output is not the contracted schema (never partially accepted)."""


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Fact(_M):
    """One project fact. `source` is a project-relative path (or `console`, `task:<code>`, `campaign:<file>`) or `unknown`."""
    value: str = Field(max_length=400)
    source: str = Field(default=UNKNOWN, max_length=300)
    collected_at: str = Field(default_factory=utc_now)  # ISO-8601 UTC; per-turn facts are refreshed every turn

    @model_validator(mode="after")
    def _unknown_source(self) -> "Fact":
        if self.value == UNKNOWN:
            self.source = UNKNOWN
        elif self.source != UNKNOWN and (self.source.startswith("/") or ".." in self.source.split("/")):
            raise ValueError("source must be project-relative")
        return self


class ProjectFacts(_M):
    """Bounded read-only research result. Any fact not found is `Fact(value="unknown")`, never guessed."""
    schema_version: Literal[1] = 1
    collector_version: str = COLLECTOR_VERSION
    project: str = Field(max_length=500)  # canonical project/worktree path
    fingerprint: str = Field(default="", max_length=64)  # sha256 over static sources; changes on edit/deletion
    unity_version: Fact = Field(default_factory=lambda: Fact(value=UNKNOWN))
    packages: dict[str, Fact] = Field(default_factory=dict, max_length=60)  # package id -> version fact
    render_pipeline: Fact = Field(default_factory=lambda: Fact(value=UNKNOWN))  # ACTIVE pipeline, not just installed
    input_handler: Fact = Field(default_factory=lambda: Fact(value=UNKNOWN))  # old|new|both|unknown (mixed detected)
    build_scenes: list[Fact] = Field(default_factory=list, max_length=40)
    candidates: list[Fact] = Field(default_factory=list, max_length=20)  # scene/prefab/script/asmdef candidates
    git: list[Fact] = Field(default_factory=list, max_length=10)
    docs: list[Fact] = Field(default_factory=list, max_length=12)  # GDD/PROJECT/TASTE/POSTMORTEMS excerpts
    task: list[Fact] = Field(default_factory=list, max_length=8)  # attached task/story/AC/BACKLOG (per turn)
    campaign: list[Fact] = Field(default_factory=list, max_length=8)  # decisions/discoveries/next action (per turn)
    console: list[Fact] = Field(default_factory=list, max_length=8)  # cached Editor errors, timestamped (per turn)
    truncated: bool = False


class Option(_M):
    id: str = Field(pattern=_ID)  # stable within the question, e.g. "o1".."o4" or a slug
    label: str = Field(min_length=1, max_length=80)
    detail: str = Field(default="", max_length=240)
    cited_fact: str | None = Field(default=None, max_length=300)  # path/source backing the option


class Question(_M):
    id: str = Field(pattern=_ID)
    topic: Topic
    text: str = Field(min_length=1, max_length=300)
    options: list[Option] = Field(min_length=2, max_length=4)
    recommended: str  # an Option.id
    rationale: str = Field(min_length=1, max_length=300)  # the tradeoff
    allow_free_text: bool = True

    @model_validator(mode="after")
    def _check(self) -> "Question":
        ids = [o.id for o in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate option ids")
        if self.recommended not in ids:
            raise ValueError("recommended must be an option id")
        return self


class Answer(_M):
    question_id: str
    option_id: str | None = None  # None: free text only, or skipped
    free_text: str = Field(default="", max_length=1000)
    skipped: bool = False  # optional skip becomes an explicit assumption
    answered_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _check(self) -> "Answer":
        if self.skipped and (self.option_id or self.free_text):
            raise ValueError("a skipped answer carries no choice")
        if not self.skipped and not (self.option_id or self.free_text.strip()):
            raise ValueError("answer needs an option or text")
        return self


class AcceptanceCriterion(_M):
    id: str = Field(pattern=r"^AC\d{1,2}$")
    expected: str = Field(min_length=1, max_length=300)  # observable result
    verification: VerifyType
    reference: str = Field(default="", max_length=300)  # test name / signal / project-relative path
    target: float | None = None
    unit: str = Field(default="", max_length=20)


class Budget(_M):
    usd_estimate: float | None = Field(default=None, ge=0)
    usd_cap: float | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, ge=1)
    max_calls: int | None = Field(default=None, ge=1)
    billing_basis: Literal["api", "subscription", "unknown"] = "unknown"
    uncertainty: str = Field(default="", max_length=200)


class Routing(_M):
    """Recommendation only: never spends, never switches harness by itself."""
    skills: list[str] = Field(default_factory=list, max_length=3)  # via unity-router
    unity_route: Literal["mcp", "cli", "none", "unknown"] = "unknown"
    harness: Literal["builtin", "claude_code", "unchanged"] = "unchanged"
    reasons: list[str] = Field(default_factory=list, max_length=4)


class TaskCard(_M):
    """Exactly the plan's table: Identity, Intent, Acceptance, Quality, Resources, Decisions, Route."""
    schema_version: Literal[1] = 1
    # Identity (filled by the service; the evaluator may leave them empty)
    session_id: str = ""
    message_id: str = ""
    run_id: str = ""
    task_code: str | None = None
    task_link: str | None = None
    facts_fingerprint: str = Field(default="", max_length=64)
    citations: list[str] = Field(default_factory=list, max_length=20)
    # Intent
    goal: str = Field(min_length=1, max_length=500)
    scope: list[str] = Field(default_factory=list, max_length=20)  # project-relative assets/systems
    out_of_scope: list[str] = Field(default_factory=list, max_length=10)
    # Acceptance
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list, max_length=8)
    # Quality
    quality_ladder_level: Ladder = "L2"
    quality_rationale: str = Field(default="", max_length=300)
    backlog_story: str | None = Field(default=None, max_length=40)  # existing BACKLOG story/AC mapping
    # Resources
    effort: Literal["none", "low", "medium", "high"] = "low"  # never above high
    budget: Budget = Field(default_factory=Budget)
    # Decisions
    answers: list[Answer] = Field(default_factory=list, max_length=MAX_QUESTIONS)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=8)
    blockers: list[str] = Field(default_factory=list, max_length=5)
    # Route
    route: Routing = Field(default_factory=Routing)


class EvalResult(_M):
    """The evaluator's whole output. PROCEED has no questions; ASK has 1..3."""
    decision: Decision
    cited_facts: list[str] = Field(default_factory=list, max_length=20)  # Fact sources
    questions: list[Question] = Field(default_factory=list, max_length=MAX_QUESTIONS)
    task_card: TaskCard
    routing: Routing = Field(default_factory=Routing)
    assumptions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _check(self) -> "EvalResult":
        if self.decision == "PROCEED" and self.questions:
            raise ValueError("PROCEED must not carry questions")
        if self.decision == "ASK" and not self.questions:
            raise ValueError("ASK needs at least one question")
        ids = [q.id for q in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate question ids")
        return self


class ImproverOutcome(_M):
    """What the coordinator returns to a harness."""
    status: Status
    reason: str = ""  # bypass reason code, or failure kind for unavailable/paused
    context_text: RawStr = Field(default="", max_length=6000)  # appended to THIS turn's request only ("" if none)
    execution_text: RawStr = ""  # the user's text for execution (leading `*` stripped); "" = use the stored text
    message_id: str = ""
    run_id: str = ""
    item_ids: list[str] = Field(default_factory=list)  # evaluation, answers, card, failure items
    task_code: str | None = None  # the auto-created Backlog task (answered question only) else None
    failure_item_id: str | None = None  # the failure diagnostics item (unavailable/paused), else None
    questions_asked: int = 0
    calls: int = 0
    estimated_tokens: int = 0


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def parse_eval(text: str) -> EvalResult:
    """Parse the evaluator's reply (one JSON object, optional code fence) or raise PiFormatError."""
    if not isinstance(text, str) or not text.strip():
        raise PiFormatError("empty evaluator output")
    body = _FENCE.sub("", text.strip())
    try:
        data: Any = json.loads(body)
    except json.JSONDecodeError as e:
        raise PiFormatError(f"not JSON: {e.msg}") from e
    if not isinstance(data, dict):
        raise PiFormatError("expected a JSON object")
    try:
        return EvalResult.model_validate(data)
    except ValidationError as e:
        raise PiFormatError(f"schema: {e.errors()[0].get('loc')}: {e.errors()[0].get('msg')}") from e
