"""Provider-neutral types shared by every adapter, the agent loop and the API.

Adapters translate these to and from each provider's wire format. Everything is a
pydantic model so it serialises straight into the SQLite event log and the WebSocket.
"""
from __future__ import annotations

import base64
import mimetypes
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- effort

# Canonical effort levels, lowest to highest. "none" means the provider's
# lowest / no-thinking setting. Anything above "high" needs an approval token.
EFFORT_LEVELS: tuple[str, ...] = ("none", "low", "medium", "high", "xhigh", "max")
ABOVE_HIGH: frozenset[str] = frozenset({"xhigh", "max"})
Effort = Literal["none", "low", "medium", "high", "xhigh", "max"]


def effort_rank(level: str) -> int:
    return EFFORT_LEVELS.index(level)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


# ----------------------------------------------------------------- content blocks


class _Block(BaseModel):
    model_config = {"extra": "forbid"}


class TextBlock(_Block):
    type: Literal["text"] = "text"
    text: str
    citations: list[dict[str, Any]] | None = None


class _MediaBlock(_Block):
    """Media is carried either inline (base64) or by path; adapters load as needed."""

    media_type: str
    data: str | None = None  # base64
    path: str | None = None
    name: str | None = None
    item_id: str | None = None  # row in the item index, when known

    def load_b64(self) -> str:
        if self.data is not None:
            return self.data
        if self.path is None:
            raise ValueError(f"{self.type} block has neither data nor path")
        return base64.b64encode(Path(self.path).read_bytes()).decode()

    def load_bytes(self) -> bytes:
        return base64.b64decode(self.load_b64())

    @classmethod
    def from_path(cls, path: str | Path, **kw: Any):
        p = Path(path)
        mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return cls(media_type=mt, path=str(p), name=p.name, **kw)


class ImageBlock(_MediaBlock):
    type: Literal["image"] = "image"


class AudioBlock(_MediaBlock):
    type: Literal["audio"] = "audio"
    transcript: str | None = None


class FileBlock(_MediaBlock):
    type: Literal["file"] = "file"
    text: str | None = None  # extracted text, if any


class ToolUseBlock(_Block):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(_Block):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: list["ResultContent"] = Field(default_factory=list)
    is_error: bool = False

    @classmethod
    def text(cls, tool_use_id: str, text: str, is_error: bool = False) -> "ToolResultBlock":
        return cls(tool_use_id=tool_use_id, content=[TextBlock(text=text)], is_error=is_error)

    def as_text(self) -> str:
        parts = []
        for c in self.content:
            parts.append(c.text if isinstance(c, TextBlock) else f"[{c.type}: {getattr(c, 'name', '') or ''}]")
        return "\n".join(parts)


class ThinkingBlock(_Block):
    """Reasoning output. `signature` / `opaque` must be round-tripped unchanged to the
    provider that produced them; other providers drop the block."""

    type: Literal["thinking"] = "thinking"
    thinking: str = ""
    signature: str | None = None
    redacted: bool = False
    opaque: str | None = None  # anthropic redacted data / openai encrypted_content
    provider: str | None = None
    item_ref: str | None = None  # openai reasoning item id


ResultContent = Annotated[Union[TextBlock, ImageBlock, FileBlock, AudioBlock], Field(discriminator="type")]
ContentBlock = Annotated[
    Union[TextBlock, ImageBlock, AudioBlock, FileBlock, ToolUseBlock, ToolResultBlock, ThinkingBlock],
    Field(discriminator="type"),
]
ToolResultBlock.model_rebuild()


# ----------------------------------------------------------------------- messages

Role = Literal["user", "assistant"]


class Message(BaseModel):
    role: Role
    content: list[ContentBlock]
    id: str = Field(default_factory=lambda: new_id("msg_"))
    meta: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def user(cls, *parts: str | Any) -> "Message":
        return cls(role="user", content=[TextBlock(text=p) if isinstance(p, str) else p for p in parts])

    @classmethod
    def assistant(cls, *parts: str | Any) -> "Message":
        return cls(role="assistant", content=[TextBlock(text=p) if isinstance(p, str) else p for p in parts])

    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_calls(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]


class ToolSpec(BaseModel):
    """A tool offered to a model. `input_schema` is JSON Schema."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    read_only: bool = False


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]


class ToolResult(BaseModel):
    tool_use_id: str
    output: str
    is_error: bool = False
    items: list[str] = Field(default_factory=list)  # item ids produced


# -------------------------------------------------------------------------- usage


class Usage(BaseModel):
    input_tokens: int = 0  # uncached input
    output_tokens: int = 0  # includes reasoning
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    characters: int = 0  # ElevenLabs
    credits: float = 0.0  # ElevenLabs
    cost_usd: float = 0.0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(**{k: getattr(self, k) + getattr(other, k) for k in Usage.model_fields})


class RateLimits(BaseModel):
    requests_limit: int | None = None
    requests_remaining: int | None = None
    tokens_limit: int | None = None
    tokens_remaining: int | None = None
    input_tokens_remaining: int | None = None
    output_tokens_remaining: int | None = None
    reset: str | None = None


# context_window: the model ran out of context window while writing (Anthropic's model_context_window_exceeded).
StopReason = Literal["end_turn", "tool_use", "max_tokens", "context_window", "stop_sequence", "refusal", "pause_turn",
                     "error", "other"]


class Response(BaseModel):
    id: str
    provider: str
    model: str
    content: list[ContentBlock]
    stop_reason: StopReason = "end_turn"
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
    rate_limits: RateLimits | None = None
    raw_stop_reason: str | None = None

    def message(self) -> Message:
        return Message(role="assistant", content=list(self.content), meta={"model": self.model, "provider": self.provider})

    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))


StreamEventType = Literal[
    "text_delta",
    "thinking_delta",
    "tool_use_start",
    "tool_input_delta",
    "block_stop",
    "usage",
    "done",  # carries the final Response in `response`
    "error",
]


class StreamEvent(BaseModel):
    type: StreamEventType
    index: int = 0
    text: str = ""
    tool_use: ToolUseBlock | None = None
    usage: Usage | None = None
    response: Response | None = None
    error: str | None = None


class ChatRequest(BaseModel):
    """Everything an adapter needs for one model call."""

    model: str
    messages: list[Message]
    system: str | list[str] = ""  # list = separately cacheable segments, stable first
    tools: list[ToolSpec] = Field(default_factory=list)
    effort: Effort | None = None
    max_tokens: int = 16000
    temperature: float | None = None
    show_thinking: bool = True
    cache: bool = True
    tool_choice: Literal["auto", "any", "none"] | None = None
    approval_token: str | None = None  # required for effort above "high"
    metadata: dict[str, Any] = Field(default_factory=dict)
