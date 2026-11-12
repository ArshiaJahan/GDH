"""Tiny router over httpx2.MockTransport for SDKs that use httpx2 (anthropic, openai)."""
from __future__ import annotations

import json
from typing import Any, Callable

import httpx2


class MockAPI:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Any] = {}
        self.calls: list[httpx2.Request] = []

    def add(self, method: str, path: str, response: Any) -> "MockAPI":
        """`response` is an httpx2.Response, an Exception to raise, or a callable(request)."""
        self.routes[(method.upper(), path)] = response
        return self

    def json_body(self, i: int = -1) -> dict:
        return json.loads(self.calls[i].content)

    def calls_to(self, path: str) -> list[httpx2.Request]:
        return [c for c in self.calls if c.url.path == path]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        r = self.routes.get((request.method, request.url.path))
        if r is None:
            return httpx2.Response(404, json={"error": f"no mock for {request.method} {request.url.path}"})
        if isinstance(r, Exception):
            raise r
        if callable(r) and not isinstance(r, httpx2.Response):
            return r(request)
        return r

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle))


def jresp(status: int, body: Any, headers: dict | None = None) -> httpx2.Response:
    return httpx2.Response(status, json=body, headers=headers or {})


def sse(text: str) -> httpx2.Response:
    return httpx2.Response(200, content=text.encode(), headers={"content-type": "text/event-stream"})


def connect_error(msg: str = "no route") -> Callable:
    def _raise(request: httpx2.Request):
        raise httpx2.ConnectError(msg, request=request)

    return _raise
