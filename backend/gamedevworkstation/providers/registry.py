"""Provider instances per (provider, profile)."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..config import Config
from ..core.types import Usage
from .base import ChatProvider, ProviderError

if TYPE_CHECKING:
    from ..features.tracing import Span, TraceRecorder


class ProviderRegistry:
    def __init__(self, config: Config):
        self.config = config
        self.tracing: TraceRecorder | None = None
        self._chat: dict[tuple[str, str], ChatProvider] = {}
        self._overrides: dict[tuple[str, str], ChatProvider] = {}

    def override(self, provider: str, profile: str, instance: ChatProvider) -> None:
        """Tests and fakes: install a provider instance."""
        self._overrides[(provider, profile)] = instance

    def chat(self, provider: str, profile: str = "default") -> ChatProvider:
        key = (provider, profile)
        if key in self._overrides:
            return self._overrides[key]
        if key not in self._chat:
            if provider == "anthropic":
                from .anthropic_provider import AnthropicProvider

                self._chat[key] = AnthropicProvider(profile, self.config, tracing=self.tracing)
            elif provider == "openai":
                from .openai_provider import OpenAIProvider

                self._chat[key] = OpenAIProvider(profile, self.config, tracing=self.tracing)
            else:
                raise ValueError(f"no chat provider {provider!r}")
        return self._chat[key]

    def for_model(self, model: str, profile: str = "default") -> ChatProvider:
        return self.chat(self.config.model(model).provider, profile)

    def reset(self) -> None:
        """Drop cached clients (e.g. after a key change)."""
        self._chat.clear()


def attempt_failure(error: BaseException) -> tuple[Usage, str]:
    usage = getattr(error, "usage", None)
    if isinstance(error, asyncio.CancelledError):
        kind = "cancelled"
    elif getattr(error, "rate_limited", False) or getattr(error, "status_code", None) in (429, 529):
        kind = "rate_limit"
    elif getattr(error, "auth", False) or getattr(error, "status_code", None) in (401, 403):
        kind = "auth"
    else:
        kind = "other"
    return usage if isinstance(usage, Usage) else Usage(), kind


@contextmanager
def chat_span(tracing: TraceRecorder | None, provider: str, model: str, max_tokens: int, effort: str | None,
              *, session_id: str | None = None, run_id: str | None = None):
    """Keep streamed spans detached so yielding a delta never changes the consumer's parent."""
    if tracing is None:
        yield None
        return
    from ..features.tracing import SpanKind

    span = tracing.start("chat", category="model", kind=SpanKind.CLIENT, session_id=session_id, run_id=run_id,
                         attrs={"gen_ai.operation.name": "chat", "gen_ai.provider.name": provider,
                                "gen_ai.request.model": model, "gen_ai.request.max_tokens": max_tokens,
                                **({"gdw.effort": effort} if effort is not None else {})})
    outcome = "ok"
    try:
        yield span
    except (asyncio.CancelledError, GeneratorExit) as exc:
        outcome = "cancelled"
        chat_result(span, usage=getattr(exc, "usage", None))
        raise
    except Exception as exc:
        outcome = "error"
        _chat_error(span, exc)
        raise
    finally:
        span.end(outcome)


def _chat_error(span: Span, error: Exception) -> None:
    _, kind = attempt_failure(error)
    if isinstance(error, ProviderError) and error.context_overflow:
        kind = "context_overflow"
    span.set_attributes({"error.type": kind if kind != "other" else "provider_error"})
    chat_result(span, usage=getattr(error, "usage", None))


def chat_result(span: Span | None, *, model: str | None = None, finish: str | None = None,
                usage: Usage | None = None) -> None:
    if span is None:
        return
    attrs = {}
    if model:
        attrs["gen_ai.response.model"] = model
    if finish:
        attrs["gen_ai.response.finish_reasons"] = [finish]
    if isinstance(usage, Usage):
        attrs.update({"gen_ai.usage.input_tokens": usage.total_input, "gen_ai.usage.output_tokens": usage.output_tokens})
        for key, value in (("gen_ai.usage.cache_read.input_tokens", usage.cache_read_tokens),
                           ("gen_ai.usage.cache_creation.input_tokens", usage.cache_write_tokens),
                           ("gen_ai.usage.reasoning.output_tokens", usage.reasoning_tokens)):
            if value:
                attrs[key] = value
    if finish in ("refusal", "error"):
        attrs["error.type"] = finish
    span.set_attributes(attrs)
    if finish in ("refusal", "error"):
        span.end(finish)
