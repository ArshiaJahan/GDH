"""Provider interface, capabilities and cost calculation."""
from __future__ import annotations

import abc
from typing import AsyncIterator

from pydantic import BaseModel, Field

from ..config import ModelConfig
from ..core.media import is_image_rejected
from ..core.types import ChatRequest, Response, StreamEvent, Usage


class Capabilities(BaseModel):
    vision: bool = False
    audio: bool = False
    files: bool = False  # PDFs / documents as native input
    tools: bool = True
    effort_levels: list[str] = Field(default_factory=list)
    context_window: int = 0
    features: list[str] = Field(default_factory=list)  # ElevenLabs: tts, stt, sfx, music, ...


class ProviderError(Exception):
    def __init__(self, message: str, *, status: int | None = None, rate_limited: bool = False, auth: bool = False,
                 retry_after: float | None = None, no_key: str | None = None,
                 context_overflow: bool | None = None):
        super().__init__(message)
        self.status = status
        self.rate_limited = rate_limited
        self.auth = auth
        self.no_key = no_key  # provider with no key saved for the profile (the chat shows a Settings button)
        self.retry_after = retry_after  # seconds, from the provider's retry-after header when it sent one
        # The request didn't fit the model's context window (the loop compacts and retries once).
        self.context_overflow = is_context_overflow(status, message) if context_overflow is None else context_overflow
        # An image in the request was too large (pixels or bytes): the loop leaves such images out and retries once.
        self.image_rejected = (not self.context_overflow and not rate_limited and not auth
                               and is_image_rejected(status, message))


# Wording both providers use when a request is longer than the model's context window.
_OVERFLOW_HINTS = ("prompt is too long", "context_length_exceeded", "context window", "maximum context length",
                   "too many tokens", "input is too long", "exceeds the context", "request too large",
                   "request_too_large")


def is_context_overflow(status: int | None, message: str) -> bool:
    m = (message or "").lower()
    return status in (400, 413, None) and any(h in m for h in _OVERFLOW_HINTS)


def retry_after_from(e: Exception) -> float | None:
    """Seconds from an SDK error's retry-after-ms / retry-after header (seconds or HTTP date)."""
    headers = getattr(getattr(e, "response", None), "headers", None)
    if not headers:
        return None
    try:
        if ms := headers.get("retry-after-ms"):
            return max(float(ms) / 1000, 0.0)
        if ra := headers.get("retry-after"):
            try:
                return max(float(ra), 0.0)
            except ValueError:
                import email.utils
                import time

                return max(email.utils.parsedate_to_datetime(ra).timestamp() - time.time(), 0.0)
    except (TypeError, ValueError):
        return None
    return None


# Rate-limit backoff shared by the main loop and subagents: exponential from 2 s, capped at 60 s,
# 5 retries; a retry-after from the provider wins (capped at 120 s).
BACKOFF_START_S = 2.0
BACKOFF_MAX_S = 60.0
RETRY_AFTER_MAX_S = 120.0
MAX_RATE_RETRIES = 5


def backoff_wait(e: "ProviderError", delay: float) -> float:
    """How long to wait before the next try: the provider's retry-after if it gave one, else delay."""
    if e.retry_after is not None:
        return min(max(e.retry_after, 0.0), RETRY_AFTER_MAX_S)
    return min(delay, BACKOFF_MAX_S)


class AuthStatus(BaseModel):
    provider: str
    profile: str
    status: str  # online | auth_failed | unreachable | no_key
    error: str | None = None
    models: list[str] = Field(default_factory=list)
    checked_at: float = 0.0
    extra: dict = Field(default_factory=dict)


class ChatProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    def capabilities(self, model: str) -> Capabilities: ...

    @abc.abstractmethod
    async def complete(self, req: ChatRequest) -> Response: ...

    @abc.abstractmethod
    def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]: ...

    @abc.abstractmethod
    async def check_auth(self) -> AuthStatus: ...


def compute_cost(model: ModelConfig, usage: Usage) -> float:
    """USD cost for one call. Prices are per million tokens."""
    total_in = usage.total_input
    p_in, p_out = model.input, model.output
    p_cw = model.cache_write if model.cache_write is not None else model.input * 1.25
    p_cr = model.cache_read if model.cache_read is not None else model.input * 0.1
    lc = model.long_context
    if lc and total_in > lc.threshold:
        p_in, p_out = lc.input, lc.output
        p_cw = lc.cache_write if lc.cache_write is not None else p_in * 1.25
        p_cr = lc.cache_read if lc.cache_read is not None else p_in * 0.1
    cost = (
        usage.input_tokens * p_in
        + usage.output_tokens * p_out
        + usage.cache_write_tokens * p_cw
        + usage.cache_read_tokens * p_cr
    ) / 1_000_000
    return round(cost, 6)
