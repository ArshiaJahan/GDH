import asyncio

import httpx
import pytest
import respx

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.features.elevenlabs_feature import ElevenLabsService, _register_tools
from gamedevworkstation.features.status import StatusChecker
from gamedevworkstation.providers.fake import FakeProvider

EL = "https://api.elevenlabs.io"
SUB = {"tier": "creator", "character_count": 1200, "character_limit": 100000, "next_character_count_reset_unix": 1795000000,
       "status": "active", "can_use_instant_voice_cloning": True, "can_use_professional_voice_cloning": False,
       "voice_slots_used": 1, "voice_limit": 30, "professional_voice_slots_used": 0, "professional_voice_limit": 1,
       "max_voice_add_edits": 0, "voice_add_edit_counter": 0, "can_extend_character_limit": True,
       "allowed_to_extend_character_limit": True, "can_extend_voice_limit": False, "currency": "usd",
       "billing_period": "monthly_period", "character_refresh_period": "monthly_period"}
VOICES = {"voices": [{"voice_id": "v_rachel", "name": "Rachel", "category": "premade", "labels": {"accent": "american"},
                      "preview_url": "https://example.com/r.mp3"}], "has_more": False, "total_count": 1,
          "next_page_token": None}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    a = AppState(db_path=tmp_path / "e.db")
    a.providers.override("anthropic", "default", FakeProvider("anthropic"))
    a.providers.override("openai", "default", FakeProvider("openai"))
    svc = ElevenLabsService(a)
    a.extensions["elevenlabs"] = svc
    _register_tools(a, svc)
    return a


@respx.mock
async def test_auth_check_and_quota(app):
    respx.get(f"{EL}/v1/user/subscription").mock(return_value=httpx.Response(200, json=SUB))
    respx.get(f"{EL}/v1/models").mock(return_value=httpx.Response(200, json=[
        {"model_id": "eleven_v4", "name": "v4", "can_do_text_to_speech": True,
         "model_rates": {"character_cost_multiplier": 1.0}}]))
    snap = await StatusChecker(app).check_all()
    el = next(p for p in snap if p["provider"] == "elevenlabs")
    assert el["status"] == "online" and el["extra"]["subscription"]["character_limit"] == 100000
    assert el["extra"]["features"]["music"] is True and "eleven_v4" in el["models"]

    respx.get(f"{EL}/v1/user/subscription").mock(return_value=httpx.Response(401, json={"detail": {"status": "invalid_api_key", "message": "Invalid API key"}}))
    app.extensions["elevenlabs"].clients.clear()
    snap = await StatusChecker(app).check_all()
    assert next(p for p in snap if p["provider"] == "elevenlabs")["status"] == "auth_failed"


@respx.mock
async def test_agent_tts_indexed_and_metered(app):
    route = respx.post(url__regex=rf"{EL}/v1/text-to-speech/v_rachel.*").mock(
        return_value=httpx.Response(200, content=b"ID3fakeaudio", headers={"character-cost": "11", "content-type": "audio/mpeg"}))
    respx.get(url__regex=rf"{EL}/v2/voices.*").mock(return_value=httpx.Response(200, json=VOICES))
    s = app.store.create()
    ctx = ToolContext(app=app, session=s, run_id="main:x")
    out = await app.tools.run(ctx, "tts", {"text": "Hello world", "voice_id": "v_rachel"})
    assert not out.is_error, out.text
    sent = route.calls[0].request
    assert b'"model_id":"eleven_v4"' in sent.content.replace(b" ", b"")
    it = app.items.list(session_id=s["id"], provider="elevenlabs")[0]
    assert it["kind"] == "media" and it["subtype"] == "audio" and it["extracted_text"] == "Hello world"
    assert it["meta"]["credits"] == 11 and it["meta"]["voice"] == "Rachel"
    u = app.db.one("SELECT * FROM usage_records WHERE provider='elevenlabs'")
    assert u["characters"] == 11 and u["credits"] == 11 and u["feature"] == "tts" and u["voice"] == "Rachel"


@respx.mock
async def test_large_agent_generation_needs_approval(app):
    respx.post(url__regex=rf"{EL}/v1/text-to-speech/.*").mock(return_value=httpx.Response(200, content=b"x"))
    app.config.elevenlabs["confirm_over_characters"] = 10
    s = app.store.create()
    ctx = ToolContext(app=app, session=s, run_id="main:x")
    task = asyncio.create_task(app.tools.run(ctx, "tts", {"text": "This is long enough to ask.", "voice_id": "v1"}))
    for _ in range(100):
        pend = app.approvals.pending(s["id"])
        if pend:
            break
        await asyncio.sleep(0.01)
    assert pend[0]["kind"] == "elevenlabs" and pend[0]["payload"]["characters"] == 27
    app.approvals.resolve(pend[0]["id"], "deny")
    out = await task
    assert out.is_error and "declined" in out.text and not app.items.list(provider="elevenlabs")


@respx.mock
async def test_transcribe_with_speakers(app, tmp_path):
    respx.post(f"{EL}/v1/speech-to-text").mock(return_value=httpx.Response(200, json={
        "language_code": "en", "language_probability": 0.99, "text": "Hi there. Hello.", "audio_duration_secs": 3.2,
        "words": [{"text": "Hi", "start": 0.0, "end": 0.3, "type": "word", "speaker_id": "speaker_0", "logprob": 0},
                  {"text": " ", "start": 0.3, "end": 0.35, "type": "spacing", "speaker_id": "speaker_0", "logprob": 0},
                  {"text": "there.", "start": 0.35, "end": 0.8, "type": "word", "speaker_id": "speaker_0", "logprob": 0},
                  {"text": "Hello.", "start": 1.5, "end": 2.0, "type": "word", "speaker_id": "speaker_1", "logprob": 0}]}))
    folder = tmp_path / "f"
    folder.mkdir()
    (folder / "memo.m4a").write_bytes(b"audio")
    s = app.store.create(folder=str(folder))
    out = await app.tools.run(ToolContext(app=app, session=s, run_id="main:x"), "transcribe", {"source": "memo.m4a"})
    assert "speaker_0: Hi there.\nspeaker_1: Hello." in out.text
    it = app.items.list(session_id=s["id"], subtype="transcript")[0]
    assert it["provider"] == "elevenlabs" and "speaker_1" in it["extracted_text"]
    # Searchable via the item index.
    assert app.items.search("Hello", session_id=s["id"])[0]["items"][0]["id"] == it["id"]


STT_JSON = {"language_code": "en", "language_probability": 0.99, "text": "Hi.", "audio_duration_secs": 90.0,
            "words": [{"text": "Hi.", "start": 0.0, "end": 0.4, "type": "word", "speaker_id": "speaker_0", "logprob": 0}]}


@respx.mock
async def test_transcribe_records_credits_from_duration_or_header(app, tmp_path):
    route = respx.post(f"{EL}/v1/speech-to-text").mock(return_value=httpx.Response(200, json=STT_JSON))
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"audio")
    svc = app.extensions["elevenlabs"]
    r = await svc.transcribe(audio, session_id=None, source="user")
    # No cost header: 1.5 minutes × 330 credits per minute, marked as an estimate.
    assert r["credits"] == pytest.approx(495) and r["credits_estimated"] is True
    u = app.db.one("SELECT * FROM usage_records WHERE feature='stt'")
    assert u["credits"] == pytest.approx(495)
    assert app.items.get(r["item_id"])["meta"]["credits_estimated"] is True

    route.mock(return_value=httpx.Response(200, json=STT_JSON, headers={"character-cost": "480"}))
    r = await svc.transcribe(audio, session_id=None, source="user")
    assert r["credits"] == 480 and r["credits_estimated"] is False


@respx.mock
async def test_quota_refreshed_after_generations_debounced(app, monkeypatch):
    from gamedevworkstation.features import elevenlabs_feature as ef

    monkeypatch.setattr(ef, "QUOTA_REFRESH_DELAY_S", 0.01)
    app.db.insert("auth_status", {"provider": "elevenlabs", "profile": "default", "status": "online",
                                  "models": "[]", "extra": '{"subscription": {"character_count": 1}}',
                                  "checked_at": 1.0}, replace=True)
    sub_route = respx.get(f"{EL}/v1/user/subscription").mock(return_value=httpx.Response(200, json=SUB))
    respx.post(url__regex=rf"{EL}/v1/text-to-speech/.*").mock(
        return_value=httpx.Response(200, content=b"x", headers={"character-cost": "5"}))
    respx.get(url__regex=rf"{EL}/v2/voices.*").mock(return_value=httpx.Response(200, json=VOICES))
    svc = app.extensions["elevenlabs"]
    await asyncio.gather(*(svc.tts("Hello", session_id=None, source="user", voice_id="v_rachel") for _ in range(3)))
    await svc._quota_task
    assert sub_route.call_count == 1  # three generations, one subscription read
    el = app.db.one("SELECT extra FROM auth_status WHERE provider='elevenlabs'")
    import json as _json

    extra = _json.loads(el["extra"])
    assert extra["subscription"]["character_count"] == 1200 and extra["subscription_checked_at"] > 1.0
    from gamedevworkstation.features.usage_routes import UsageQueries

    q = UsageQueries(app).elevenlabs({})
    assert q["quota_checked_at"] == extra["subscription_checked_at"]
    assert q["series"][0]["characters"] == 15


def test_stt_credits_only_trusts_character_cost():
    from gamedevworkstation.features.elevenlabs_feature import stt_credits

    # x-character-count counts characters, not credits: a transcription falls back to its estimate.
    assert stt_credits({"x-character-count": "12"}, 60) == (pytest.approx(330), True)
    assert stt_credits({"character-cost": "480", "x-character-count": "12"}, 60) == (480, False)


async def test_refresh_quota_sets_only_subscription_keys(app, monkeypatch):
    import json as _json

    app.db.insert("auth_status", {"provider": "elevenlabs", "profile": "default", "status": "online", "models": "[]",
                                  "extra": '{"features": {"music": false}, "subscription": {"character_count": 1}}',
                                  "checked_at": 1.0}, replace=True)
    svc = app.extensions["elevenlabs"]

    async def sub_during_status_check():
        # The status checker rewrites the row while the subscription request is in flight.
        app.db.execute("UPDATE auth_status SET extra=? WHERE provider='elevenlabs' AND profile='default'",
                       ['{"features": {"music": true}, "subscription": {"character_count": 2}}'])
        return {"character_count": 1200, "character_limit": 100000}

    monkeypatch.setattr(svc.client_for("default"), "subscription", sub_during_status_check)
    assert (await svc.refresh_quota())["character_count"] == 1200
    extra = _json.loads(app.db.one("SELECT extra FROM auth_status WHERE provider='elevenlabs'")["extra"])
    assert extra["features"] == {"music": True}  # the checker's write survives
    assert extra["subscription"] == {"character_count": 1200, "character_limit": 100000}
    assert extra["subscription_checked_at"] > 1.0


def test_usage_quota_is_per_profile(app):
    from gamedevworkstation.features.usage_routes import UsageQueries

    app.config.accounts = {"elevenlabs": ["default", "second"]}
    for prof, used, at in (("default", 10, 100.0), ("second", 20, 200.0)):
        app.db.insert("auth_status", {"provider": "elevenlabs", "profile": prof, "status": "online", "models": "[]",
                                      "extra": f'{{"subscription": {{"character_count": {used}}}, '
                                               f'"subscription_checked_at": {at}}}', "checked_at": 1.0}, replace=True)
    q = UsageQueries(app)
    # The default (first) profile, even though "second" was checked more recently.
    d = q.elevenlabs({})
    assert d["profile"] == "default" and d["quota"]["character_count"] == 10 and d["quota_checked_at"] == 100.0
    s = q.elevenlabs({}, "second")
    assert s["profile"] == "second" and s["quota"]["character_count"] == 20 and s["quota_checked_at"] == 200.0
    assert [(x["profile"], x["quota"]["character_count"]) for x in d["quotas"]] == [("default", 10), ("second", 20)]
    assert q.elevenlabs({}, "gone")["profile"] == "default"


def test_routes_without_key_return_clean_400(tmp_path):
    """No key saved: the voice/model routes say so with a 400 (code no_key), not a 502."""
    from fastapi.testclient import TestClient

    from gamedevworkstation.server import create_app

    state = AppState(db_path=tmp_path / "nk.db")
    with TestClient(create_app("tok", state)) as c:
        h = {"Authorization": "Bearer tok"}
        assert c.get("/api/elevenlabs/status", headers=h).json()["has_key"] is False
        for path in ("/api/elevenlabs/voices", "/api/elevenlabs/voices?shared=true", "/api/elevenlabs/models"):
            r = c.get(path, headers=h)
            assert r.status_code == 400, (path, r.status_code, r.text)
            assert r.headers.get("X-GDW-Error") == "no_key"
            assert "No ElevenLabs key" in r.json()["detail"]
