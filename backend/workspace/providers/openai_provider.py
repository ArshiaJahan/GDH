"""OpenAI Responses API adapter (the "codex.*" tiers).

Checked against developers.openai.com on 2026-11-05:
- `*-codex` API models are retired; Codex runs on the GPT-6 family (gpt-6.1-sol etc.)
- reasoning.effort: none|minimal|low|medium|high|xhigh|max, model-dependent
  (Sol/Astra reject "none"); reasoning.summary for readable summaries
- flat function tools; function_call / function_call_output items; arguments are a JSON string
- stateless use: store=False and replay reasoning items with encrypted_content
- usage: input_tokens (incl. cached + cache writes), input_tokens_details.cached_tokens /
  cache_write_tokens, output_tokens (incl. reasoning), output_tokens_details.reasoning_tokens
- rate limits: x-ratelimit-{limit,remaining,reset}-{requests,tokens}
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

import openai

from ..config import Config, ModelConfig, get_config, get_key
from ..core.effort import check_effort
from ..core.types import (
    AudioBlock, ChatRequest, ContentBlock, FileBlock, ImageBlock, Message, RateLimits, Response, StreamEvent,
    TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock, Usage,
)
from ..core.media import cap_media, image_payload
from .anthropic_provider import TEXTLIKE, _media_text_fallback
from .base import AuthStatus, Capabilities, ChatProvider, ProviderError, compute_cost, retry_after_from

ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]


# --------------------------------------------------------------- translation (out)


def reasoning_params(model: ModelConfig, effort: str | None, show_thinking: bool) -> dict[str, Any]:
    r: dict[str, Any] = {}
    if effort is not None:
        level = (model.no_thinking or "low") if effort == "none" else effort
        allowed = set(model.efforts) | ({model.no_thinking} if model.no_thinking else set())
        if allowed and level not in allowed:
            lower = [lv for lv in ORDER[: ORDER.index(level) + 1] if lv in allowed]
            level = lower[-1] if lower else sorted(allowed, key=ORDER.index)[0]
        r["effort"] = level
    if show_thinking:
        r["summary"] = "auto"
    return r


def _data_url(b: ImageBlock | FileBlock) -> str:
    return f"data:{b.media_type};base64,{b.load_b64()}"


def user_part(b: ContentBlock) -> dict[str, Any] | None:
    if isinstance(b, TextBlock):
        return {"type": "input_text", "text": b.text}
    if isinstance(b, ImageBlock):
        img = image_payload(b.media_type, b.data, b.path, b.name)
        if isinstance(img, str):  # missing, too big or an odd format: a note instead of a failed request
            return {"type": "input_text", "text": img}
        return {"type": "input_image", "image_url": f"data:{img[0]};base64,{img[1]}", "detail": "auto"}
    if isinstance(b, FileBlock):
        try:
            return _file_part(b)
        except (OSError, ValueError):  # gone, moved or never stored
            return {"type": "input_text", "text": f"[File '{b.name}' is no longer available (deleted or moved); not shown]"}
    if isinstance(b, AudioBlock):
        return {"type": "input_text", "text": _media_text_fallback(b)["text"]}
    return None


def _file_part(b: FileBlock) -> dict[str, Any]:
    if b.media_type == "application/pdf" or (b.text is None and not b.media_type.startswith(TEXTLIKE)
                                             and b.media_type != "application/octet-stream"):
        return {"type": "input_file", "filename": b.name or "file", "file_data": _data_url(b)}
    text = b.text if b.text is not None else b.load_bytes().decode("utf-8", "replace")
    return {"type": "input_text", "text": f"[File '{b.name}']\n{text}"}


def messages_to_input(messages: list[Message]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "user":
            parts: list[dict[str, Any]] = []
            extra_images: list[dict[str, Any]] = []
            for b in m.content:
                if isinstance(b, ToolResultBlock):
                    items.append({"type": "function_call_output", "call_id": b.tool_use_id,
                                  "output": ("ERROR: " if b.is_error else "") + b.as_text()})
                    for c in b.content:
                        if isinstance(c, ImageBlock):
                            extra_images.append(user_part(c))  # type: ignore[arg-type]
                elif (p := user_part(b)) is not None:
                    parts.append(p)
            if extra_images:
                parts = [{"type": "input_text", "text": "Images returned by the tool calls above:"}, *extra_images, *parts]
            if parts:
                items.append({"role": "user", "content": parts})
        else:
            for b in m.content:
                if isinstance(b, TextBlock) and b.text:
                    items.append({"role": "assistant", "content": [{"type": "output_text", "text": b.text}]})
                elif isinstance(b, ToolUseBlock):
                    items.append({"type": "function_call", "call_id": b.id, "name": b.name,
                                  "arguments": json.dumps(b.input)})
                elif isinstance(b, ThinkingBlock) and b.provider == "openai" and b.opaque:
                    item: dict[str, Any] = {"type": "reasoning", "encrypted_content": b.opaque,
                                            "summary": [{"type": "summary_text", "text": b.thinking}] if b.thinking else []}
                    if b.item_ref:
                        item["id"] = b.item_ref
                    items.append(item)
    return items


def build_params(req: ChatRequest, model: ModelConfig) -> dict[str, Any]:
    system = req.system if isinstance(req.system, str) else "\n\n".join(s for s in req.system if s)
    params: dict[str, Any] = {
        "model": req.model,
        "input": cap_media(messages_to_input(req.messages)),
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "max_output_tokens": min(req.max_tokens, model.max_output or req.max_tokens),
    }
    if system:
        params["instructions"] = system
    if req.tools:
        params["tools"] = [{"type": "function", "name": t.name, "description": t.description,
                            "parameters": t.input_schema, "strict": False} for t in req.tools]
        params["parallel_tool_calls"] = True
        if req.tool_choice:
            params["tool_choice"] = {"any": "required"}.get(req.tool_choice, req.tool_choice)
    if r := reasoning_params(model, req.effort, req.show_thinking):
        params["reasoning"] = r
    if req.cache and (key := req.metadata.get("cache_key") or req.metadata.get("run_id")):
        params["prompt_cache_key"] = str(key)[:64]
    if req.temperature is not None and params.get("reasoning", {}).get("effort") == "none":
        params["temperature"] = req.temperature  # only accepted with effort "none"
    return params


# ---------------------------------------------------------------- translation (in)


def _get(o: Any, k: str, default: Any = None) -> Any:
    return o.get(k, default) if isinstance(o, dict) else getattr(o, k, default)


def output_to_blocks(output: list[Any]) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    for it in output or []:
        t = _get(it, "type")
        if t == "reasoning":
            summary = "\n\n".join(_get(s, "text", "") for s in (_get(it, "summary") or []))
            blocks.append(ThinkingBlock(thinking=summary, opaque=_get(it, "encrypted_content"),
                                        item_ref=_get(it, "id"), provider="openai"))
        elif t == "message":
            for c in _get(it, "content") or []:
                ct = _get(c, "type")
                if ct == "output_text":
                    cites = [{"url": _get(a, "url"), "title": _get(a, "title")}
                             for a in (_get(c, "annotations") or []) if _get(a, "type") == "url_citation"]
                    blocks.append(TextBlock(text=_get(c, "text", ""), citations=cites or None))
                elif ct == "refusal":
                    blocks.append(TextBlock(text=_get(c, "refusal", "")))
        elif t == "function_call":
            raw = _get(it, "arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {"_raw": raw}
            blocks.append(ToolUseBlock(id=_get(it, "call_id"), name=_get(it, "name"), input=args))
    return blocks


def usage_from(u: Any) -> Usage:
    if u is None:
        return Usage()
    inp = _get(u, "input_tokens", 0) or 0
    idet = _get(u, "input_tokens_details") or {}
    cached = _get(idet, "cached_tokens", 0) or 0
    cw = _get(idet, "cache_write_tokens", 0) or 0
    odet = _get(u, "output_tokens_details") or {}
    return Usage(input_tokens=max(inp - cached - cw, 0), cache_read_tokens=cached, cache_write_tokens=cw,
                 output_tokens=_get(u, "output_tokens", 0) or 0,
                 reasoning_tokens=_get(odet, "reasoning_tokens", 0) or 0)


def rate_limits_from_headers(h: Any) -> RateLimits | None:
    if h is None:
        return None

    def _i(n: str) -> int | None:
        v = h.get(f"x-ratelimit-{n}")
        try:
            return int(v) if v is not None else None
        except ValueError:
            return None

    rl = RateLimits(requests_limit=_i("limit-requests"), requests_remaining=_i("remaining-requests"),
                    tokens_limit=_i("limit-tokens"), tokens_remaining=_i("remaining-tokens"),
                    reset=h.get("x-ratelimit-reset-tokens") or h.get("x-ratelimit-reset-requests"))
    return rl if any(v is not None for v in rl.model_dump().values()) else None


def response_from(resp: Any, model: ModelConfig, latency_ms: int, headers: Any = None) -> Response:
    blocks = output_to_blocks(_get(resp, "output") or [])
    usage = usage_from(_get(resp, "usage"))
    usage.cost_usd = compute_cost(model, usage)
    status = _get(resp, "status")
    reason = _get(_get(resp, "incomplete_details") or {}, "reason")
    if any(isinstance(b, ToolUseBlock) for b in blocks):
        stop = "tool_use"
    elif status == "incomplete":
        stop = "max_tokens" if reason == "max_output_tokens" else "other"
    else:
        stop = "end_turn"
    return Response(id=_get(resp, "id") or "", provider="openai", model=_get(resp, "model") or model.id,
                    content=blocks, stop_reason=stop, raw_stop_reason=reason or status, usage=usage,
                    latency_ms=latency_ms, rate_limits=rate_limits_from_headers(headers))


def _wrap(e: Exception) -> ProviderError:
    if isinstance(e, ProviderError):  # ours already (e.g. no key): keep its flags
        return e
    if isinstance(e, openai.RateLimitError):
        return ProviderError(str(e), status=429, rate_limited=True, retry_after=retry_after_from(e))
    if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ProviderError(str(e), status=getattr(e, "status_code", 401), auth=True)
    if isinstance(e, openai.APIStatusError):
        return ProviderError(str(e), status=e.status_code)
    if isinstance(e, openai.APIConnectionError):
        return ProviderError(f"unreachable: {e}")
    return ProviderError(str(e))


# ------------------------------------------------------------------------ adapter


class OpenAIProvider(ChatProvider):
    name = "openai"

    def __init__(self, profile: str = "default", config: Config | None = None,
                 client: openai.AsyncOpenAI | None = None):
        self.profile = profile
        self.config = config or get_config()
        self._client = client

    @property
    def client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            key = get_key("openai", self.profile)
            if not key:
                raise ProviderError(f"No OpenAI API key yet (profile '{self.profile}'). Add one in Settings → Accounts.",
                                    auth=True, no_key="openai")
            self._client = openai.AsyncOpenAI(api_key=key, max_retries=2)
        return self._client

    def capabilities(self, model: str) -> Capabilities:
        m = self.config.model(model)
        levels = ["none", *m.efforts]
        return Capabilities(vision=m.vision, audio=False, files=True, tools=True, effort_levels=levels,
                            context_window=m.context_window)

    def _prepare(self, req: ChatRequest) -> tuple[dict[str, Any], ModelConfig]:
        check_effort(req.effort, req.approval_token, req.metadata.get("run_id", ""))
        m = self.config.model(req.model)
        return build_params(req, m), m

    async def complete(self, req: ChatRequest) -> Response:
        params, m = self._prepare(req)
        t0 = time.monotonic()
        try:
            raw = await self.client.responses.with_raw_response.create(**params)
            resp = raw.parse()
            if hasattr(resp, "__await__"):
                resp = await resp
        except Exception as e:  # noqa: BLE001
            raise _wrap(e) from e
        return response_from(resp, m, int((time.monotonic() - t0) * 1000), raw.headers)

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        params, m = self._prepare(req)
        t0 = time.monotonic()
        final = None
        headers = None
        try:
            stream = await self.client.responses.create(**params, stream=True)
            headers = getattr(getattr(stream, "response", None), "headers", None)
            async for ev in stream:
                t = ev.type
                if t == "response.output_text.delta":
                    yield StreamEvent(type="text_delta", index=ev.output_index, text=ev.delta)
                elif t == "response.reasoning_summary_text.delta":
                    yield StreamEvent(type="thinking_delta", index=ev.output_index, text=ev.delta)
                elif t == "response.output_item.added" and _get(ev.item, "type") == "function_call":
                    yield StreamEvent(type="tool_use_start", index=ev.output_index,
                                      tool_use=ToolUseBlock(id=_get(ev.item, "call_id"), name=_get(ev.item, "name")))
                elif t == "response.function_call_arguments.delta":
                    yield StreamEvent(type="tool_input_delta", index=ev.output_index, text=ev.delta)
                elif t == "response.output_item.done":
                    yield StreamEvent(type="block_stop", index=ev.output_index)
                elif t in ("response.completed", "response.incomplete"):
                    final = ev.response
                elif t == "response.failed":
                    err = _get(_get(ev.response, "error") or {}, "message") or "response failed"
                    raise ProviderError(err)
                elif t == "error":
                    raise ProviderError(getattr(ev, "message", "stream error"),
                                        rate_limited=getattr(ev, "code", "") in ("rate_limit_exceeded", "slow_down"))
        except ProviderError as e:
            yield StreamEvent(type="error", error=str(e))
            raise
        except Exception as e:  # noqa: BLE001
            err = _wrap(e)
            yield StreamEvent(type="error", error=str(err))
            raise err from e
        if final is None:
            raise ProviderError("stream ended without a final response")
        resp = response_from(final, m, int((time.monotonic() - t0) * 1000), headers)
        yield StreamEvent(type="usage", usage=resp.usage)
        yield StreamEvent(type="done", response=resp)

    async def check_auth(self) -> AuthStatus:
        st = AuthStatus(provider="openai", profile=self.profile, status="online", checked_at=time.time())
        if self._client is None and not get_key("openai", self.profile):
            st.status, st.error = "no_key", "No key in Keychain or environment"
            return st
        try:
            page = await self.client.models.list()
            st.models = [m.id for m in page.data]
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            st.status, st.error = "auth_failed", (getattr(e, "message", None) or str(e))[:300]
        except openai.APIConnectionError as e:
            st.status, st.error = "unreachable", str(e)[:300]
        except openai.APIStatusError as e:
            st.status = "auth_failed" if e.status_code in (401, 403) else "unreachable"
            st.error = str(e)[:300]
        return st
