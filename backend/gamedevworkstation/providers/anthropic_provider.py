"""Anthropic Messages API adapter: tools, prompt caching, adaptive thinking, effort.

Checked against platform.claude.com docs on 2026-11-05:
- effort: `output_config.effort` in low|medium|high|xhigh|max
- thinking: adaptive (`{"type":"adaptive","display":"summarized"|"omitted"}`), or the
  model's lowest setting `{"type":"disabled"}` / `{"type":"between_tools"}` (only at
  high or below; Opus 5.5 can't turn thinking off at all)
- caching: top-level automatic `cache_control` plus explicit breakpoint on the system
- usage: input_tokens (uncached), cache_read_input_tokens, cache_creation_input_tokens,
  output_tokens (incl. thinking), output_tokens_details.thinking_tokens
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator

import anthropic

from ..config import Config, ModelConfig, get_config, get_key
from ..core.effort import check_effort
from ..core.media import cap_media, image_payload
from ..core.types import (
    AudioBlock,
    ChatRequest,
    ContentBlock,
    FileBlock,
    ImageBlock,
    Message,
    RateLimits,
    Response,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from .base import AuthStatus, Capabilities, ChatProvider, ProviderError, compute_cost, retry_after_from

TEXTLIKE = ("text/", "application/json", "application/xml", "application/x-yaml", "application/toml",
            "application/javascript", "application/x-sh", "application/sql")
STOP_MAP = {"end_turn": "end_turn", "tool_use": "tool_use", "max_tokens": "max_tokens",
            "stop_sequence": "stop_sequence", "refusal": "refusal", "pause_turn": "pause_turn",
            "model_context_window_exceeded": "context_window"}


# --------------------------------------------------------------- translation (out)


def effort_params(model: ModelConfig, effort: str | None, show_thinking: bool) -> dict[str, Any]:
    """Map a canonical effort level onto `thinking` + `output_config` for this model."""
    display = "summarized" if show_thinking else "omitted"
    adaptive = {"type": "adaptive", "display": display}
    if effort is None:
        return {"thinking": adaptive}
    if effort == "none":
        if model.no_thinking in ("disabled", "between_tools"):
            return {"thinking": {"type": model.no_thinking}, "output_config": {"effort": "low"}}
        return {"thinking": adaptive, "output_config": {"effort": "low"}}
    level = effort
    if model.efforts and level not in model.efforts:
        # Clamp to the highest supported level not above the request.
        order = ["low", "medium", "high", "xhigh", "max"]
        allowed = [lv for lv in order[: order.index(level) + 1] if lv in model.efforts]
        level = allowed[-1] if allowed else model.efforts[0]
    return {"thinking": adaptive, "output_config": {"effort": level}}


def _media_text_fallback(b: AudioBlock | FileBlock) -> dict[str, Any]:
    ref = f" (item {b.item_id})" if b.item_id else ""
    if isinstance(b, AudioBlock):
        if b.transcript:
            return {"type": "text", "text": f"[Transcript of audio '{b.name or 'audio'}'{ref}]\n{b.transcript}"}
        return {"type": "text", "text": f"[Audio attachment '{b.name or 'audio'}'{ref}: this model can't hear audio; "
                                         "use the transcribe tool to get a transcript]"}
    if b.text:
        return {"type": "text", "text": f"[File '{b.name}'{ref}]\n{b.text}"}
    return {"type": "text", "text": f"[File '{b.name}'{ref}, {b.media_type}: binary, not shown]"}


def block_to_wire(b: ContentBlock, role: str) -> dict[str, Any] | None:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ImageBlock):
        img = image_payload(b.media_type, b.data, b.path, b.name)
        if isinstance(img, str):  # missing, too big or an odd format: a note instead of a failed request
            return {"type": "text", "text": img}
        return {"type": "image", "source": {"type": "base64", "media_type": img[0], "data": img[1]}}
    if isinstance(b, FileBlock):
        try:
            return _file_to_wire(b)
        except (OSError, ValueError):  # gone, moved or never stored
            return {"type": "text", "text": f"[File '{b.name}' is no longer available (deleted or moved); not shown]"}
    if isinstance(b, AudioBlock):
        return _media_text_fallback(b)
    if isinstance(b, ToolUseBlock):
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    if isinstance(b, ToolResultBlock):
        inner = [w for c in b.content if (w := block_to_wire(c, "user")) is not None]
        return {"type": "tool_result", "tool_use_id": b.tool_use_id, "content": inner or "",
                "is_error": b.is_error}
    if isinstance(b, ThinkingBlock):
        # Only Anthropic-signed thinking can be sent back, and only unchanged.
        if role != "assistant" or b.provider not in (None, "anthropic"):
            return None
        if b.redacted:
            return {"type": "redacted_thinking", "data": b.opaque}
        if b.signature is None:
            return None
        return {"type": "thinking", "thinking": b.thinking, "signature": b.signature}
    raise TypeError(f"unsupported block {type(b)}")


def _file_to_wire(b: FileBlock) -> dict[str, Any]:
    if b.media_type == "application/pdf":
        return {"type": "document", "title": b.name,
                "source": {"type": "base64", "media_type": "application/pdf", "data": b.load_b64()}}
    if b.media_type.startswith(TEXTLIKE) or b.text is not None:
        text = b.text if b.text is not None else b.load_bytes().decode("utf-8", "replace")
        return {"type": "document", "title": b.name,
                "source": {"type": "text", "media_type": "text/plain", "data": text}}
    return _media_text_fallback(b)


def messages_to_wire(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        content = [w for b in m.content if (w := block_to_wire(b, m.role)) is not None]
        if not content:
            continue
        if out and out[-1]["role"] == m.role:  # API requires alternation
            out[-1]["content"].extend(content)
            if m.role == "user":  # tool results must lead the user turn (e.g. repaired after a new message)
                out[-1]["content"].sort(key=lambda w: w.get("type") != "tool_result")
        else:
            out.append({"role": m.role, "content": content})
    return cap_media(out)


def build_params(req: ChatRequest, model: ModelConfig) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": req.model,
        "max_tokens": min(req.max_tokens, model.max_output or req.max_tokens),
        "messages": messages_to_wire(req.messages),
    }
    segments = [req.system] if isinstance(req.system, str) else list(req.system)
    segments = [s for s in segments if s]
    if segments:
        sys_blocks: list[dict[str, Any]] = [{"type": "text", "text": s} for s in segments]
        if req.cache:
            sys_blocks[-1]["cache_control"] = {"type": "ephemeral"}
        params["system"] = sys_blocks
    if req.tools:
        params["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
                           for t in req.tools]
        if req.tool_choice and req.tool_choice != "auto":
            params["tool_choice"] = {"type": req.tool_choice}
    if req.cache:
        params["cache_control"] = {"type": "ephemeral"}  # automatic: moves with the conversation
    if req.temperature is not None:
        params["temperature"] = req.temperature
    params.update(effort_params(model, req.effort, req.show_thinking))
    return params


# ---------------------------------------------------------------- translation (in)


def block_from_wire(b: Any) -> ContentBlock | None:
    t = b.type
    if t == "text":
        cites = [c.model_dump() for c in b.citations] if getattr(b, "citations", None) else None
        return TextBlock(text=b.text, citations=cites)
    if t == "thinking":
        return ThinkingBlock(thinking=b.thinking or "", signature=b.signature, provider="anthropic")
    if t == "redacted_thinking":
        return ThinkingBlock(redacted=True, opaque=b.data, provider="anthropic")
    if t == "tool_use":
        return ToolUseBlock(id=b.id, name=b.name, input=dict(b.input or {}))
    return None  # server tool blocks etc. are not used here


def usage_from_wire(u: Any) -> Usage:
    details = getattr(u, "output_tokens_details", None)
    return Usage(
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        reasoning_tokens=(getattr(details, "thinking_tokens", 0) or 0) if details else 0,
    )


def rate_limits_from_headers(h: Any) -> RateLimits | None:
    if h is None:
        return None

    def _i(name: str) -> int | None:
        v = h.get(f"anthropic-ratelimit-{name}")
        try:
            return int(v) if v is not None else None
        except ValueError:
            return None

    rl = RateLimits(
        requests_limit=_i("requests-limit"),
        requests_remaining=_i("requests-remaining"),
        tokens_limit=_i("tokens-limit"),
        tokens_remaining=_i("tokens-remaining"),
        input_tokens_remaining=_i("input-tokens-remaining"),
        output_tokens_remaining=_i("output-tokens-remaining"),
        reset=h.get("anthropic-ratelimit-tokens-reset") or h.get("anthropic-ratelimit-requests-reset"),
    )
    return rl if any(v is not None for v in rl.model_dump().values()) else None


def response_from_wire(msg: Any, model: ModelConfig, latency_ms: int, headers: Any = None) -> Response:
    usage = usage_from_wire(msg.usage)
    usage.cost_usd = compute_cost(model, usage)
    return Response(
        id=msg.id,
        provider="anthropic",
        model=msg.model,
        content=[c for b in msg.content if (c := block_from_wire(b)) is not None],
        stop_reason=STOP_MAP.get(msg.stop_reason or "", "other"),
        raw_stop_reason=msg.stop_reason,
        usage=usage,
        latency_ms=latency_ms,
        rate_limits=rate_limits_from_headers(headers),
    )


def _wrap_error(e: Exception) -> ProviderError:
    if isinstance(e, ProviderError):  # ours already (e.g. no key): keep its flags
        return e
    if isinstance(e, anthropic.RateLimitError):
        return ProviderError(str(e), status=429, rate_limited=True, retry_after=retry_after_from(e))
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ProviderError(str(e), status=getattr(e, "status_code", 401), auth=True)
    if isinstance(e, anthropic.APIStatusError):
        return ProviderError(str(e), status=e.status_code, rate_limited=e.status_code in (429, 529),
                             retry_after=retry_after_from(e))
    if isinstance(e, anthropic.APIConnectionError):
        return ProviderError(f"unreachable: {e}")
    return ProviderError(str(e))


# ------------------------------------------------------------------------ adapter


class AnthropicProvider(ChatProvider):
    name = "anthropic"

    def __init__(self, profile: str = "default", config: Config | None = None,
                 client: anthropic.AsyncAnthropic | None = None):
        self.profile = profile
        self.config = config or get_config()
        self._client = client

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            key = get_key("anthropic", self.profile)
            if not key:
                raise ProviderError(f"No Anthropic API key yet (profile '{self.profile}'). Add one in Settings → Accounts.",
                                    auth=True, no_key="anthropic")
            self._client = anthropic.AsyncAnthropic(api_key=key, max_retries=2)
        return self._client

    def capabilities(self, model: str) -> Capabilities:
        m = self.config.model(model)
        return Capabilities(vision=m.vision, audio=False, files=True, tools=True,
                            effort_levels=["none", *m.efforts], context_window=m.context_window)

    def _prepare(self, req: ChatRequest) -> tuple[dict[str, Any], ModelConfig]:
        check_effort(req.effort, req.approval_token, req.metadata.get("run_id", ""))
        m = self.config.model(req.model)
        return build_params(req, m), m

    async def complete(self, req: ChatRequest) -> Response:
        params, m = self._prepare(req)
        t0 = time.monotonic()
        try:
            raw = await self.client.messages.with_raw_response.create(**params)
            msg = await raw.parse()
        except Exception as e:  # noqa: BLE001
            raise _wrap_error(e) from e
        return response_from_wire(msg, m, int((time.monotonic() - t0) * 1000), raw.headers)

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        params, m = self._prepare(req)
        t0 = time.monotonic()
        try:
            async with self.client.messages.stream(**params) as s:
                async for ev in s:
                    et = ev.type
                    if et == "content_block_start" and ev.content_block.type == "tool_use":
                        cb = ev.content_block
                        yield StreamEvent(type="tool_use_start", index=ev.index,
                                          tool_use=ToolUseBlock(id=cb.id, name=cb.name))
                    elif et == "content_block_delta":
                        d = ev.delta
                        if d.type == "text_delta":
                            yield StreamEvent(type="text_delta", index=ev.index, text=d.text)
                        elif d.type == "thinking_delta" and d.thinking:
                            yield StreamEvent(type="thinking_delta", index=ev.index, text=d.thinking)
                        elif d.type == "input_json_delta":
                            yield StreamEvent(type="tool_input_delta", index=ev.index, text=d.partial_json)
                    elif et == "content_block_stop":
                        yield StreamEvent(type="block_stop", index=ev.index)
                final = await s.get_final_message()
                headers = getattr(getattr(s, "response", None), "headers", None)
        except Exception as e:  # noqa: BLE001
            err = _wrap_error(e)
            yield StreamEvent(type="error", error=str(err))
            raise err from e
        resp = response_from_wire(final, m, int((time.monotonic() - t0) * 1000), headers)
        yield StreamEvent(type="usage", usage=resp.usage)
        yield StreamEvent(type="done", response=resp)

    async def check_auth(self) -> AuthStatus:
        st = AuthStatus(provider="anthropic", profile=self.profile, status="online", checked_at=time.time())
        if self._client is None and not get_key("anthropic", self.profile):
            st.status, st.error = "no_key", "No key in Keychain or environment"
            return st
        try:
            page = await self.client.models.list(limit=1000)
            st.models = [m.id for m in page.data]
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            st.status, st.error = "auth_failed", _short(e)
        except anthropic.APIConnectionError as e:
            st.status, st.error = "unreachable", _short(e)
        except anthropic.APIStatusError as e:
            st.status, st.error = ("auth_failed" if e.status_code in (401, 403) else "unreachable"), _short(e)
        return st


def _short(e: Exception) -> str:
    msg = getattr(e, "message", None) or str(e)
    return msg[:300]
