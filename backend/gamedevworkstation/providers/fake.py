"""A scripted provider for tests and offline demos. Each call pops the next scripted
response; when the script runs out it echoes the last user text."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Callable

from ..core.effort import check_effort
from ..core.types import ChatRequest, Response, StreamEvent, TextBlock, ToolUseBlock, Usage, new_id
from .base import AuthStatus, Capabilities, ChatProvider

Script = Callable[[ChatRequest], Response] | Response


class FakeProvider(ChatProvider):
    def __init__(self, name: str = "anthropic", script: list[Script] | None = None, delay: float = 0.0):
        self.name = name
        self.script = list(script or [])
        self.calls: list[ChatRequest] = []
        self.delay = delay
        self.auth_status = "online"
        self.models = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]

    def capabilities(self, model: str) -> Capabilities:
        return Capabilities(vision=True, tools=True, effort_levels=["none", "low", "medium", "high", "xhigh", "max"],
                            context_window=200000)

    def _next(self, req: ChatRequest) -> Response:
        if self.script:
            s = self.script.pop(0)
            r = s(req) if callable(s) else s
            return r.model_copy(update={"model": req.model})
        last = req.messages[-1].text() if req.messages else ""
        return text_response(f"echo: {last}", model=req.model)

    async def complete(self, req: ChatRequest) -> Response:
        check_effort(req.effort, req.approval_token, req.metadata.get("run_id", ""))
        self.calls.append(req)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self._next(req)

    async def stream(self, req: ChatRequest) -> AsyncIterator[StreamEvent]:
        r = await self.complete(req)
        for i, b in enumerate(r.content):
            if isinstance(b, TextBlock):
                for chunk in _chunks(b.text):
                    yield StreamEvent(type="text_delta", index=i, text=chunk)
            elif isinstance(b, ToolUseBlock):
                yield StreamEvent(type="tool_use_start", index=i, tool_use=b)
        yield StreamEvent(type="done", response=r)

    async def check_auth(self) -> AuthStatus:
        return AuthStatus(provider=self.name, profile="default", status=self.auth_status,
                          models=self.models if self.auth_status == "online" else [])


def _chunks(s: str, n: int = 8) -> list[str]:
    return [s[i:i + n] for i in range(0, len(s), n)] or [""]


def text_response(text: str, model: str = "claude-haiku-5-5", usage: Usage | None = None) -> Response:
    return Response(id=new_id("msg_"), provider="anthropic", model=model, content=[TextBlock(text=text)],
                    stop_reason="end_turn", usage=usage or Usage(input_tokens=10, output_tokens=5, cost_usd=0.0001))


def tool_response(name: str, args: dict, text: str = "", model: str = "claude-haiku-5-5") -> Response:
    content: list = ([TextBlock(text=text)] if text else []) + [ToolUseBlock(id=new_id("toolu_"), name=name, input=args)]
    return Response(id=new_id("msg_"), provider="anthropic", model=model, content=content, stop_reason="tool_use",
                    usage=Usage(input_tokens=10, output_tokens=5, cost_usd=0.0001))
