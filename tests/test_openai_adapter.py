import base64
import json

import pytest

from gamedevworkstation.core.effort import APPROVALS, EffortApprovalRequired
from gamedevworkstation.core.types import (
    AudioBlock, ChatRequest, FileBlock, ImageBlock, Message, ThinkingBlock, ToolResultBlock, ToolSpec, ToolUseBlock,
)
from gamedevworkstation.providers.openai_provider import OpenAIProvider, build_params, reasoning_params

from .conftest import FIXTURES
from .mockhttp import MockAPI, connect_error, jresp, sse

API = "https://api.openai.com/v1"


def provider(cfg, api: MockAPI):
    import openai

    return OpenAIProvider(config=cfg, client=openai.AsyncOpenAI(api_key="sk-test", base_url=API, max_retries=0,
                                                               http_client=api.client()))


def fixture(name):
    return json.loads((FIXTURES / "openai" / name).read_text())


def test_effort_mapping(cfg):
    sol, terra = cfg.model("gpt-6.1-sol"), cfg.model("gpt-6.1-terra")
    assert reasoning_params(sol, "none", False) == {"effort": "low"}  # Sol rejects "none"
    assert reasoning_params(terra, "none", False) == {"effort": "none"}
    assert reasoning_params(sol, "high", True) == {"effort": "high", "summary": "auto"}
    assert reasoning_params(sol, None, False) == {}


def test_request_translation(cfg, tmp_path):
    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    msgs = [
        Message.user("fix it", ImageBlock(media_type="image/png", data=base64.b64encode(b"img").decode()),
                     FileBlock.from_path(pdf), AudioBlock(media_type="audio/wav", data="AA==", name="a.wav")),
        Message.assistant(ThinkingBlock(thinking="plan", opaque="ENC", item_ref="rs_9", provider="openai"),
                          ThinkingBlock(thinking="claude's", signature="S", provider="anthropic"),
                          ToolUseBlock(id="call_1", name="run_command", input={"command": "ls"})),
        Message(role="user", content=[ToolResultBlock.text("call_1", "a.py b.py")]),
    ]
    req = ChatRequest(model="gpt-6.1-sol", system=["one", "two"], messages=msgs, effort="medium",
                      tools=[ToolSpec(name="run_command", input_schema={"type": "object"})],
                      metadata={"run_id": "sub_7"})
    p = build_params(req, cfg.model("gpt-6.1-sol"))
    assert p["instructions"] == "one\n\ntwo" and p["store"] is False
    assert p["reasoning"]["effort"] == "medium" and p["prompt_cache_key"] == "sub_7"
    assert p["tools"][0] == {"type": "function", "name": "run_command", "description": "",
                             "parameters": {"type": "object"}, "strict": False}
    u = p["input"][0]["content"]
    assert u[1]["type"] == "input_image" and u[1]["image_url"].startswith("data:image/png;base64,")
    assert u[2]["type"] == "input_file" and u[2]["filename"] == "spec.pdf"
    assert "transcribe" in u[3]["text"]
    assert p["input"][1] == {"type": "reasoning", "encrypted_content": "ENC", "id": "rs_9",
                             "summary": [{"type": "summary_text", "text": "plan"}]}
    assert p["input"][2] == {"type": "function_call", "call_id": "call_1", "name": "run_command",
                             "arguments": '{"command": "ls"}'}  # Claude thinking dropped
    assert p["input"][3] == {"type": "function_call_output", "call_id": "call_1", "output": "a.py b.py"}


async def test_complete(cfg):
    api = MockAPI().add("POST", "/v1/responses", jresp(200, fixture("response_tool_call.json"), {
        "x-ratelimit-remaining-requests": "499", "x-ratelimit-remaining-tokens": "199000",
        "x-ratelimit-reset-tokens": "6ms"}))
    r = await provider(cfg, api).complete(ChatRequest(model="gpt-6.1-sol", messages=[Message.user("go")],
                                                      effort="medium"))
    assert [b.type for b in r.content] == ["thinking", "text", "tool_use"]
    assert r.content[0].opaque == "ENC_abc" and r.content[0].thinking == "Need to run tests."
    assert r.content[1].citations == [{"url": "https://docs.pytest.org", "title": "pytest"}]
    assert r.content[2].id == "call_abc" and r.content[2].input == {"command": "pytest -q"}
    assert r.stop_reason == "tool_use"
    u = r.usage
    assert (u.input_tokens, u.cache_read_tokens, u.cache_write_tokens, u.output_tokens, u.reasoning_tokens) == (
        500, 4000, 500, 800, 600)
    # Sol: 500*2 + 4000*0.10 + 500*2.5 + 800*10 per MTok
    assert u.cost_usd == pytest.approx((1000 + 400 + 1250 + 8000) / 1e6)
    assert r.rate_limits.requests_remaining == 499
    assert api.json_body()["reasoning"] == {"effort": "medium", "summary": "auto"}


async def test_stream(cfg):
    api = MockAPI().add("POST", "/v1/responses", sse((FIXTURES / "openai/stream_text.sse").read_text()))
    evs = [e async for e in provider(cfg, api).stream(ChatRequest(model="gpt-6.1-terra",
                                                                  messages=[Message.user("hi")], effort="low"))]
    assert "".join(e.text for e in evs if e.type == "text_delta") == "Hello world"
    assert [e.text for e in evs if e.type == "thinking_delta"] == ["Greeting."]
    final = evs[-1].response
    assert final.text() == "Hello world" and final.usage.output_tokens == 20 and final.stop_reason == "end_turn"


async def test_above_high_rejected_without_token(cfg):
    api = MockAPI().add("POST", "/v1/responses", jresp(200, fixture("response_tool_call.json")))
    p = provider(cfg, api)
    with pytest.raises(EffortApprovalRequired):
        await p.complete(ChatRequest(model="gpt-6.1-sol", messages=[Message.user("x")], effort="xhigh"))
    assert not api.calls
    tok = APPROVALS.issue("apr_oa", "max")
    await p.complete(ChatRequest(model="gpt-6.1-sol", messages=[Message.user("x")], effort="max",
                                 approval_token=tok, metadata={"run_id": "r1"}))
    assert api.json_body()["reasoning"]["effort"] == "max"


async def test_auth(cfg):
    ok = MockAPI().add("GET", "/v1/models", jresp(200, fixture("models_list.json")))
    st = await provider(cfg, ok).check_auth()
    assert st.status == "online" and "gpt-6.1-sol" in st.models
    bad = MockAPI().add("GET", "/v1/models", jresp(401, {"error": {"message": "Incorrect API key", "type": "invalid_request_error"}}))
    st = await provider(cfg, bad).check_auth()
    assert st.status == "auth_failed" and not st.models
    down = MockAPI().add("GET", "/v1/models", connect_error())
    assert (await provider(cfg, down).check_auth()).status == "unreachable"
