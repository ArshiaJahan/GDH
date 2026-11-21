"""Model routing policy: a pure function of [model_routing], the model table and a unit's request.

`tier = "auto"` picks the cheapest eligible priced candidate of the job type's rule, inside one provider family
(the session profile, data policy and provider-specific history stay valid). Anything unrecognised falls back to
the family's standard tier. The rest of the candidates, in the rule's capability order, are the escalation chain.
No I/O and no provider clients here; features/subagents.py applies the result.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..config import Config
from ..core.types import Usage
from ..providers.base import ProviderError, compute_cost

JOB_TYPES = ("extract", "mechanical_edit", "implement_feature")  # the closed vocabulary rules may cover
CHECKS = ("json_object", "non_empty")
PINNED_TIERS = ("codex.cli",)  # run outside the API loop, never an automatic candidate
STANDARD = {"anthropic": "claude.standard", "openai": "codex.standard"}
FAMILY = {"claude": "anthropic", "codex": "openai"}
DEFAULT_FAMILY = "anthropic"
OVERHEAD_TOKENS = 3000  # system prompt and tool specs the instructions don't include
EST_OUTPUT_TOKENS = 4000  # shared by every candidate so the comparison depends only on prices


@dataclass(frozen=True)
class Route:
    tier: str
    model: str
    provider: str
    reason: str  # cheapest | standard | routing_disabled
    job_type: str = "other"
    check: str = ""  # json_object | non_empty | "" (none)
    chain: tuple[str, ...] = ()  # stronger eligible tiers after `tier`, weakest first
    revision: str = ""
    max_escalations: int = 0


def estimate_tokens(text: str, history_chars: int = 0) -> tuple[int, int]:
    """(input, output) token estimate for one unit: about four characters per token."""
    return OVERHEAD_TOKENS + (len(text) + history_chars) // 4, EST_OUTPUT_TOKENS


def _settings(cfg: Config) -> dict[str, Any]:
    s = cfg.model_routing
    return s if isinstance(s, dict) else {}


def _max_escalations(cfg: Config) -> int:
    v = _settings(cfg).get("max_escalations", 1)
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 1


def _rule(cfg: Config, job_type: str) -> dict[str, Any]:
    rules = _settings(cfg).get("rules")
    rule = rules.get(job_type) if isinstance(rules, dict) else None
    return rule if isinstance(rule, dict) else {}


def family_of(cfg: Config, tier: str) -> str | None:
    model = cfg.resolve(tier)
    m = cfg.models.get(model)
    return m.provider if m else None


def eligible(cfg: Config, tier: str, effort: str | None, tokens_in: int, tokens_out: int,
             *, min_context: int = 0, priced: bool = True) -> bool:
    """Can this tier take the unit: configured, API-routable, supports the effort, and fits the bounds?"""
    if not isinstance(tier, str) or tier in PINNED_TIERS:
        return False
    m = cfg.models.get(cfg.resolve(tier))
    if m is None:
        return False
    if priced and not (m.input > 0 and m.output > 0):
        return False
    if effort is not None and effort not in m.efforts:
        return False
    return m.context_window > min_context and m.context_window >= tokens_in + min(tokens_out, m.max_output)


def estimated_cost(cfg: Config, tier: str, tokens_in: int, tokens_out: int) -> float:
    return compute_cost(cfg.model(cfg.resolve(tier)), Usage(input_tokens=tokens_in, output_tokens=tokens_out))


def standard_route(cfg: Config, family: str, job_type: str, reason: str) -> Route:
    tier = STANDARD.get(family, STANDARD[DEFAULT_FAMILY])
    model = cfg.resolve(tier)
    if model not in cfg.models:
        raise ValueError(f"Automatic routing has no usable model: tier {tier} is not configured. "
                         "Name a tier explicitly or fix [tiers] in the config.")
    return Route(tier=tier, model=model, provider=cfg.models[model].provider, reason=reason, job_type=job_type,
                 revision=str(_settings(cfg).get("revision", "")), max_escalations=0)


def select(cfg: Config, *, job_type: str, effort: str | None, instructions: str, provider: str | None = None) -> Route:
    """The route for a `tier = "auto"` unit. `provider` is the caller's family request (anthropic | openai)."""
    family = FAMILY.get(provider or "", provider) if provider else None
    if not _settings(cfg).get("enabled", False):
        return standard_route(cfg, family or DEFAULT_FAMILY, job_type, "routing_disabled")
    rule = _rule(cfg, job_type) if job_type in JOB_TYPES else {}
    names = [c for c in rule.get("candidates") or [] if isinstance(c, str)]
    family = family or next((f for c in names if (f := family_of(cfg, c))), DEFAULT_FAMILY)
    tin, tout = estimate_tokens(instructions)
    fits = [c for c in dict.fromkeys(names)
            if family_of(cfg, c) == family and eligible(cfg, c, effort, tin, tout)]
    if not fits:
        return standard_route(cfg, family, job_type, "standard")
    best = min(fits, key=lambda c: (estimated_cost(cfg, c, tin, tout), fits.index(c)))
    check = rule.get("check")
    model = cfg.resolve(best)
    return Route(tier=best, model=model, provider=family, reason="cheapest", job_type=job_type,
                 check=check if check in CHECKS else "", chain=tuple(fits[fits.index(best) + 1:]),
                 revision=str(_settings(cfg).get("revision", "")), max_escalations=_max_escalations(cfg))


def next_tier(cfg: Config, route: Route, current: str, *, effort: str | None, tokens_in: int,
              bigger_context: bool = False) -> str | None:
    """The next stronger candidate after `current` that still fits the (grown) request, or None."""
    chain = list(route.chain)
    if current in chain:
        chain = chain[chain.index(current) + 1:]
    have = cfg.model(cfg.resolve(current)).context_window
    for tier in chain:
        if family_of(cfg, tier) != route.provider:
            continue
        if eligible(cfg, tier, effort, tokens_in, EST_OUTPUT_TOKENS, min_context=have if bigger_context else 0):
            return tier
    return None


def failure_reason(error: BaseException) -> str | None:
    """transient_error | context_overflow for a provider failure that may move to a stronger model, else None.
    Authentication, missing keys and 4xx request errors follow their normal path."""
    if not isinstance(error, ProviderError) or error.auth or error.no_key:
        return None
    if error.context_overflow:
        return "context_overflow"
    if error.rate_limited or error.status is None or error.status in (408, 409, 425, 429) or error.status >= 500:
        return "transient_error"
    return None


def run_check(check: str, text: str) -> bool:
    """The unit's deterministic check on its final reply."""
    if check == "non_empty":
        return bool(text.strip())
    if check == "json_object":
        body = text.strip()
        if body.startswith("```"):  # a fenced block is still an object the caller can parse
            body = body.strip("`").removeprefix("json").strip()
        try:
            return isinstance(json.loads(body), dict)
        except ValueError:
            return False
    return True


def repair_instruction(check: str) -> str:
    what = {"json_object": "reply with exactly one JSON object and nothing else",
            "non_empty": "reply with a non-empty answer"}.get(check, "follow the requested output format")
    return (f"Automatic check '{check}' failed on your previous reply. Redo the task from the work already done and "
            f"{what}. Do not repeat tool actions that already ran.")
