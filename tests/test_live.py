"""Live smoke tests against real provider APIs. Skipped when the key is missing."""
import os

import pytest

from workspace.core.types import ChatRequest, Message

from .conftest import REAL_KEYS

pytestmark = pytest.mark.live


@pytest.mark.skipif(not REAL_KEYS["ANTHROPIC_API_KEY"], reason="ANTHROPIC_API_KEY not set")
async def test_anthropic_live(monkeypatch, cfg):
    monkeypatch.setenv("ANTHROPIC_API_KEY", REAL_KEYS["ANTHROPIC_API_KEY"])
    from workspace.providers.anthropic_provider import AnthropicProvider

    p = AnthropicProvider(config=cfg)
    assert (await p.check_auth()).status == "online"
    r = await p.complete(ChatRequest(model=cfg.resolve("claude.fast"), effort="low", max_tokens=200,
                                     messages=[Message.user("Reply with exactly: pong")]))
    assert "pong" in r.text().lower() and r.usage.output_tokens > 0


@pytest.mark.skipif(not REAL_KEYS["OPENAI_API_KEY"], reason="OPENAI_API_KEY not set")
async def test_openai_live(monkeypatch, cfg):
    monkeypatch.setenv("OPENAI_API_KEY", REAL_KEYS["OPENAI_API_KEY"])
    from workspace.providers.openai_provider import OpenAIProvider

    p = OpenAIProvider(config=cfg)
    st = await p.check_auth()
    assert st.status == "online"
    r = await p.complete(ChatRequest(model=cfg.resolve("codex.fast"), effort="low", max_tokens=200,
                                     messages=[Message.user("Reply with exactly: pong")]))
    assert "pong" in r.text().lower()


@pytest.mark.skipif(not REAL_KEYS["ELEVENLABS_API_KEY"], reason="ELEVENLABS_API_KEY not set")
async def test_elevenlabs_live_auth(monkeypatch):
    """Auth + quota only: no credits spent."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", REAL_KEYS["ELEVENLABS_API_KEY"])
    from workspace.providers.elevenlabs_client import ElevenLabsClient

    st = await ElevenLabsClient().check_auth()
    assert st.status == "online" and "character_limit" in st.extra["subscription"]
