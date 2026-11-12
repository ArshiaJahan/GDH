import base64
import json

import pytest

from gamedevworkstation.core.effort import APPROVALS, EffortApprovalRequired
from gamedevworkstation.core.types import (
    AudioBlock, ChatRequest, FileBlock, ImageBlock, Message, TextBlock, ThinkingBlock,
    ToolResultBlock, ToolSpec, ToolUseBlock,
)
from gamedevworkstation.providers.anthropic_provider import AnthropicProvider, build_params, effort_params

from .conftest import FIXTURES
from .mockhttp import MockAPI, connect_error, jresp, sse

API = "https://api.anthropic.com"
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


def provider(cfg, api: MockAPI):
    import anthropic

    return AnthropicProvider(config=cfg, client=anthropic.AsyncAnthropic(
        api_key="sk-test", max_retries=0, base_url=API, http_client=api.client()))


# ------------------------------------------------------------- request translation


def test_effort_mapping_per_model(cfg):
    opus, sonnet, haiku = (cfg.model(m) for m in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"))
    # "none" → each model's lowest setting
    assert effort_params(haiku, "none", True) == {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}
    assert effort_params(sonnet, "none", True)["thinking"] == {"type": "between_tools"}
    assert effort_params(opus, "none", True)["thinking"]["type"] == "adaptive"  # Opus 5.5 can't disable
    assert effort_params(opus, "medium", False) == {
        "thinking": {"type": "adaptive", "display": "omitted"}, "output_config": {"effort": "medium"}}
    assert "output_config" not in effort_params(opus, None, True)


def test_tools_system_and_caching(cfg):
    req = ChatRequest(model="claude-sonnet-5-5", system=["stable rules", "session part"],
                      messages=[Message.user("hi")],
                      tools=[ToolSpec(name="tts", description="speak", input_schema={"type": "object"})],
                      effort="low")
    p = build_params(req, cfg.model(req.model))
    assert p["tools"] == [{"name": "tts", "description": "speak", "input_schema": {"type": "object"}}]
    assert [s["text"] for s in p["system"]] == ["stable rules", "session part"]
    assert "cache_control" not in p["system"][0] and p["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert p["cache_control"] == {"type": "ephemeral"}
    assert p["output_config"] == {"effort": "low"}


def test_media_and_history_translation(cfg, tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    code = tmp_path / "x.py"
    code.write_text("print(1)")
    msgs = [
        Message.user("look", ImageBlock(media_type="image/png", data=PNG), FileBlock.from_path(pdf),
                     FileBlock.from_path(code), AudioBlock(media_type="audio/mpeg", data="AA==", name="memo.mp3")),
        Message.assistant(ThinkingBlock(thinking="t", signature="S1", provider="anthropic"),
                          ThinkingBlock(thinking="foreign", provider="openai", opaque="enc"),
                          ToolUseBlock(id="tu1", name="f", input={"a": 1})),
        Message(role="user", content=[ToolResultBlock.text("tu1", "result!")]),
        Message.user("and then?"),  # consecutive user turns get merged
    ]
    p = build_params(ChatRequest(model="claude-opus-5-5", messages=msgs), cfg.model("claude-opus-5-5"))
    u0 = p["messages"][0]["content"]
    assert u0[1]["type"] == "image" and u0[1]["source"]["data"] == PNG
    assert u0[2]["type"] == "document" and u0[2]["source"]["media_type"] == "application/pdf"
    assert u0[3]["source"] == {"type": "text", "media_type": "text/plain", "data": "print(1)"}
    assert u0[4]["type"] == "text" and "transcribe" in u0[4]["text"]  # Claude can't take audio
    a = p["messages"][1]["content"]
    assert a[0] == {"type": "thinking", "thinking": "t", "signature": "S1"}
    assert len(a) == 2  # OpenAI reasoning dropped
    assert len(p["messages"]) == 3
    assert p["messages"][2]["content"][0]["type"] == "tool_result"
    assert p["messages"][2]["content"][1] == {"type": "text", "text": "and then?"}


# -------------------------------------------------------------- response handling


async def test_complete_parses_tool_use_usage_cost_and_rate_limits(cfg):
    body = json.loads((FIXTURES / "anthropic/message_tool_use.json").read_text())
    api = MockAPI().add("POST", "/v1/messages", jresp(200, body, {
        "anthropic-ratelimit-requests-limit": "4000", "anthropic-ratelimit-requests-remaining": "3999",
        "anthropic-ratelimit-tokens-remaining": "1990000", "anthropic-ratelimit-tokens-reset": "2026-11-05T22:40:00Z"}))
    r = await provider(cfg, api).complete(ChatRequest(model="claude-sonnet-5-5", messages=[Message.user("weather?")],
                                                 effort="medium"))
    sent = api.json_body(0)
    assert sent["output_config"] == {"effort": "medium"}
    assert [b.type for b in r.content] == ["thinking", "text", "tool_use"]
    assert r.content[0].signature == "SIG_abc123"
    assert r.stop_reason == "tool_use"
    assert r.message().tool_calls()[0].input == {"city": "San Jose"}
    u = r.usage
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens, u.reasoning_tokens) == (
        120, 300, 2000, 500, 180)
    # sonnet-5-5: 120*2 + 300*10 + 500*2.5 + 2000*0.10 per MTok
    assert u.cost_usd == pytest.approx((240 + 3000 + 1250 + 200) / 1e6)
    assert r.rate_limits.requests_remaining == 3999 and r.rate_limits.reset == "2026-11-05T22:40:00Z"


async def test_stream_events(cfg):
    text = (FIXTURES / "anthropic/stream_text.sse").read_text()
    api = MockAPI().add("POST", "/v1/messages", sse(text))
    events = [e async for e in provider(cfg, api).stream(ChatRequest(model="claude-haiku-5-5",
                                                                messages=[Message.user("hi")], effort="low"))]
    kinds = [e.type for e in events]
    assert "".join(e.text for e in events if e.type == "text_delta") == "Hello there!"
    assert [e.text for e in events if e.type == "thinking_delta"] == ["Simple greeting."]
    assert kinds.count("tool_use_start") == 1 and kinds[-1] == "done"
    final = events[-1].response
    assert final.content[0].signature == "SIG_stream"
    assert final.content[2].input == {"text": "hi"}
    assert final.usage.output_tokens == 42 and final.usage.reasoning_tokens == 10
    assert final.usage.cost_usd > 0


def test_long_context_pricing(cfg):
    from gamedevworkstation.core.types import Usage
    from gamedevworkstation.providers.base import compute_cost

    haiku = cfg.model("claude-haiku-5-5")
    assert compute_cost(haiku, Usage(input_tokens=1_000_000)) == pytest.approx(0.50)  # >100k → long-context rate
    assert compute_cost(haiku, Usage(input_tokens=50_000)) == pytest.approx(0.005)


# ------------------------------------------------------------------- effort gate


async def test_above_high_effort_rejected_without_approval(cfg):
    api = MockAPI().add("POST", "/v1/messages", jresp(500, {}))
    p = provider(cfg, api)
    for level in ("xhigh", "max"):
        with pytest.raises(EffortApprovalRequired):
            await p.complete(ChatRequest(model="claude-opus-5-5", messages=[Message.user("x")], effort=level))
        with pytest.raises(EffortApprovalRequired):
            await p.complete(ChatRequest(model="claude-opus-5-5", messages=[Message.user("x")], effort=level,
                                         approval_token="apv_forged_0000"))
    assert not api.calls  # rejected before any network call


async def test_above_high_effort_with_approval_token(cfg):
    body = json.loads((FIXTURES / "anthropic/message_tool_use.json").read_text())
    api = MockAPI().add("POST", "/v1/messages", lambda r: jresp(200, body))
    token = APPROVALS.issue("apr_test1", "xhigh")
    p = provider(cfg, api)
    req = ChatRequest(model="claude-opus-5-5", messages=[Message.user("x")], effort="xhigh",
                      approval_token=token, metadata={"run_id": "sub_1"})
    await p.complete(req)
    await p.complete(req)  # same run may keep calling at the approved level
    assert api.json_body(0)["output_config"] == {"effort": "xhigh"}
    with pytest.raises(EffortApprovalRequired):  # another run can't reuse it
        await p.complete(req.model_copy(update={"metadata": {"run_id": "sub_2"}}))
    with pytest.raises(EffortApprovalRequired):  # an xhigh approval doesn't cover max
        await p.complete(req.model_copy(update={"effort": "max"}))


# -------------------------------------------------------------------- auth check


async def test_auth_check_states(cfg):
    body = json.loads((FIXTURES / "anthropic/models_list.json").read_text())
    st = await provider(cfg, MockAPI().add("GET", "/v1/models", jresp(200, body))).check_auth()
    assert st.status == "online" and "claude-haiku-5-5" in st.models

    bad = jresp(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
    st = await provider(cfg, MockAPI().add("GET", "/v1/models", bad)).check_auth()
    assert st.status == "auth_failed" and st.models == [] and "invalid" in st.error

    down = MockAPI().add("GET", "/v1/models", connect_error())
    assert (await provider(cfg, down).check_auth()).status == "unreachable"


async def test_no_key(cfg):
    st = await AnthropicProvider(config=cfg).check_auth()
    assert st.status == "no_key"
