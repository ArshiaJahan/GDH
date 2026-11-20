"""Backend pieces the trailer maker uses: ElevenLabs music from a composition plan (exact section lengths) and
media files announced by a command (`TRAILER_OUTPUT:` / `ARTIFACT:` lines) indexed as items."""
import asyncio
import json
import os
import time

import httpx
import pytest
import respx

from gamedevworkstation.agent.tools import ToolContext, ToolOutput
from gamedevworkstation.app import AppState
from gamedevworkstation.features import media_out
from gamedevworkstation.features.elevenlabs_feature import ElevenLabsService, _register_tools, composition_plan_checked
from gamedevworkstation.features.hookbus import HookEvent
from gamedevworkstation.providers.elevenlabs_client import ElevenLabsClient, ElevenLabsError
from gamedevworkstation.providers.fake import FakeProvider

EL = "https://api.elevenlabs.io"
PLAN = {"chunks": [
    {"text": "[Cold open] driving drums", "duration_ms": 7000, "positive_styles": ["synthwave", "driving drums"],
     "negative_styles": ["vocals"]},
    {"text": "[Build] rising", "duration_ms": 25000, "positive_styles": ["rising"]},
    {"text": "[Button] final hit", "duration_ms": 5000, "positive_styles": ["final hit"]}]}


def el_app(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    a = AppState(db_path=tmp_path / "e.db")
    a.providers.override("anthropic", "default", FakeProvider("anthropic"))
    svc = ElevenLabsService(a)
    a.extensions["elevenlabs"] = svc
    _register_tools(a, svc)
    return a


@respx.mock
async def test_music_with_composition_plan(tmp_path, monkeypatch):
    app = el_app(tmp_path, monkeypatch)
    route = respx.post(url__regex=rf"{EL}/v1/music.*").mock(
        return_value=httpx.Response(200, content=b"ID3music", headers={"content-type": "audio/mpeg"}))
    s = app.store.create()
    ctx = ToolContext(app=app, session=s, run_id="main:x")
    out = await app.tools.run(ctx, "music", {"composition_plan": PLAN, "seed": 7})
    assert not out.is_error, out.text
    body = json.loads(route.calls[0].request.content)
    assert body["composition_plan"]["chunks"][1] == {"text": "[Build] rising", "duration_ms": 25000,
                                                     "positive_styles": ["rising"]}
    assert body["model_id"] == "music_v2_5" and body["seed"] == 7
    assert "prompt" not in body and "music_length_ms" not in body and "force_instrumental" not in body
    it = app.items.list(session_id=s["id"], provider="elevenlabs")[0]
    assert it["meta"]["duration_s"] == 37 and it["meta"]["seed"] == 7
    assert it["meta"]["composition_plan"]["chunks"][0]["negative_styles"] == ["vocals"]
    assert [x["duration_ms"] for x in it["meta"]["sections"]] == [7000, 25000, 5000]
    assert it["title"].startswith("Music: [Cold open]") and "[Build] rising" in it["extracted_text"]


@respx.mock
async def test_music_prompt_path_unchanged(tmp_path, monkeypatch):
    app = el_app(tmp_path, monkeypatch)
    route = respx.post(url__regex=rf"{EL}/v1/music.*").mock(return_value=httpx.Response(200, content=b"x"))
    ctx = ToolContext(app=app, session=app.store.create(), run_id="main:x")
    out = await app.tools.run(ctx, "music", {"prompt": "lofi", "duration_s": 12, "seed": 3})
    assert not out.is_error, out.text
    body = json.loads(route.calls[0].request.content)
    assert body["prompt"] == "lofi" and body["music_length_ms"] == 12000 and "composition_plan" not in body
    assert "seed" not in body  # the API refuses a seed with a prompt
    out = await app.tools.run(ctx, "music", {})
    assert out.is_error and "prompt or a composition_plan" in out.text


async def test_composition_plan_confirm_card_uses_summed_durations(tmp_path, monkeypatch):
    app = el_app(tmp_path, monkeypatch)
    app.config.elevenlabs["confirm_over_characters"] = 10
    s = app.store.create()
    ctx = ToolContext(app=app, session=s, run_id="main:x")
    task = asyncio.create_task(app.tools.run(ctx, "music", {"composition_plan": PLAN}))
    for _ in range(200):
        pend = app.approvals.pending(s["id"])
        if pend:
            break
        await asyncio.sleep(0.01)
    assert pend[0]["kind"] == "elevenlabs" and pend[0]["payload"]["feature"] == "music"
    assert pend[0]["payload"]["est_credits"] == round(37000 / 60000 * 1500)
    assert "[Cold open]" in pend[0]["payload"]["preview"]
    app.approvals.resolve(pend[0]["id"], "deny")
    out = await task
    assert out.is_error and "declined" in out.text


async def test_invalid_composition_plans_are_refused(tmp_path, monkeypatch):
    app = el_app(tmp_path, monkeypatch)
    ctx = ToolContext(app=app, session=app.store.create(), run_id="main:x")
    bad = {"chunks": [{"text": "", "duration_ms": 1000, "positive_styles": "loud"}]}
    out = await app.tools.run(ctx, "music", {"composition_plan": bad})
    assert out.is_error and "duration_ms must be 3000-120000" in out.text and "needs text" in out.text
    assert "positive_styles must be a list" in out.text
    assert composition_plan_checked(json.dumps(PLAN))["chunks"][2]["duration_ms"] == 5000  # JSON text accepted
    long_ = {"chunks": [{"text": "x", "duration_ms": 120000, "positive_styles": []}] * 6}
    out = await app.tools.run(ctx, "music", {"composition_plan": long_})
    assert out.is_error and "more than 10 minutes" in out.text


@respx.mock
async def test_instrumental_composition_plan_keeps_vocals_out(tmp_path, monkeypatch):
    app = el_app(tmp_path, monkeypatch)
    route = respx.post(url__regex=rf"{EL}/v1/music.*").mock(return_value=httpx.Response(200, content=b"ID3"))
    s = app.store.create()
    ctx = ToolContext(app=app, session=s, run_id="main:x")
    out = await app.tools.run(ctx, "music", {"composition_plan": PLAN, "instrumental": True, "seed": 4})
    assert not out.is_error, out.text
    body = json.loads(route.calls[0].request.content)
    negs = [c.get("negative_styles") for c in body["composition_plan"]["chunks"]]
    assert negs == [["vocals"], ["vocals"], ["vocals"]]  # added once each, not duplicated in chunk 1
    assert "force_instrumental" not in body
    meta = app.items.list(session_id=s["id"], provider="elevenlabs")[0]["meta"]
    assert meta["instrumental"] is True and meta["instrumental_via"] == "negative_styles"
    assert [c["negative_styles"] for c in meta["composition_plan"]["chunks"]] == negs  # what was sent
    # not instrumental: the plan goes out as written and the item says so
    await app.tools.run(ctx, "music", {"composition_plan": PLAN})
    body = json.loads(route.calls[1].request.content)
    assert [c.get("negative_styles") for c in body["composition_plan"]["chunks"]] == [["vocals"], None, None]
    meta = app.items.list(session_id=s["id"], provider="elevenlabs")[0]["meta"]
    assert meta["instrumental"] is False and "instrumental_via" not in meta


async def test_music_seed_must_be_a_whole_number(tmp_path, monkeypatch):
    app = el_app(tmp_path, monkeypatch)
    ctx = ToolContext(app=app, session=app.store.create(), run_id="main:x")
    for bad in ("abc", 1.5, -1, True):
        out = await app.tools.run(ctx, "music", {"composition_plan": PLAN, "seed": bad})
        assert out.is_error and "seed must be a whole number" in out.text, (bad, out.text)
    with pytest.raises(ElevenLabsError, match="seed must be a whole number"):  # the client: never a bare ValueError
        await ElevenLabsClient("default").music("p", 3000, composition_plan=PLAN, seed="x")


def test_music_variations_get_consecutive_seeds(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from gamedevworkstation.server import create_app

    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    s = AppState(db_path=tmp_path / "v.db")
    s.providers.override("anthropic", "default", FakeProvider())
    seeds = []

    async def fake_music(prompt, **kw):
        seeds.append(kw["seed"])
        return {"seed": kw["seed"]}

    with TestClient(create_app("t", s)) as c:
        monkeypatch.setattr(s.extensions["elevenlabs"], "music", fake_music)
        h = {"Authorization": "Bearer t"}
        r = c.post("/api/elevenlabs/music", json={"composition_plan": PLAN, "seed": 10, "variations": 3}, headers=h)
        assert r.status_code == 200, r.text
        assert sorted(seeds) == [10, 11, 12]
        seeds.clear()
        r = c.post("/api/elevenlabs/music", json={"prompt": "lofi", "variations": 2}, headers=h)
        assert r.status_code == 200 and seeds == [None, None]
        r = c.post("/api/elevenlabs/music", json={"composition_plan": PLAN, "seed": "x"}, headers=h)
        assert r.status_code == 400 and "seed must be a whole number" in r.json()["detail"]


def test_composition_plan_line_limits():
    ok_text = "\n".join(["[Build] line"] * 30)
    assert composition_plan_checked({"chunks": [{"text": ok_text, "duration_ms": 5000}]})
    for text, needle in (("\n".join(["x"] * 31), "31 lines (ElevenLabs allows at most 30)"),
                         ("[Build] " + "a" * 200, "line 1 is 208 characters (ElevenLabs allows at most 200")):
        with pytest.raises(ElevenLabsError) as ei:
            composition_plan_checked({"chunks": [{"text": text, "duration_ms": 5000}]})
        assert needle in str(ei.value), str(ei.value)


# ------------------------------------------------------------------ media outputs as items


def mo_app(tmp_path):
    a = AppState(db_path=tmp_path / "m.db")
    a.providers.override("anthropic", "default", FakeProvider())
    a.mo = media_out.install(a)
    return a


async def observe(app, s, text, tool="run_command"):
    ctx = ToolContext(app=app, session=s, run_id=f"main:{s['id']}")
    return await app.mo.observe(HookEvent("post_tool", ctx, tool=tool, args={"command": "python3 x.py"},
                                          output=ToolOutput(text)))


async def test_trailer_outputs_become_items(tmp_path):
    app = mo_app(tmp_path)
    proj = tmp_path / "game"
    (proj / "Trailer/t/exports").mkdir(parents=True)
    (proj / "Trailer/t/review").mkdir(parents=True)
    (proj / "Trailer/t/exports/t-steam.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (proj / "Trailer/t/review/first5.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (proj / "notes.txt").write_text("hi")
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"x")
    s = app.store.create(folder=str(proj))
    text = ("exit code 0\nrender ...\n"
            f"TRAILER_OUTPUT: {proj / 'Trailer/t/exports/t-steam.mp4'}\n"
            "ARTIFACT: Trailer/t/review/first5.png\n"
            f"TRAILER_OUTPUT: {outside}\n"
            "TRAILER_OUTPUT: notes.txt\n"
            "TRAILER_OUTPUT: Trailer/t/exports/missing.mp4\n"
            "RESULT: OK exported steam")
    res = await observe(app, s, text)
    assert res.action == "note" and "t-steam.mp4" in res.note and "first5.png" in res.note
    items = {i["filename"]: i for i in app.items.list(session_id=s["id"])}
    assert set(items) == {"t-steam.mp4", "first5.png"}
    assert items["t-steam.mp4"]["mime"] == "video/mp4" and items["t-steam.mp4"]["kind"] == "media"
    assert items["t-steam.mp4"]["subtype"] == "video" and items["first5.png"]["subtype"] == "image"
    # the same unchanged file isn't indexed twice; a re-render is
    assert await observe(app, s, text) is None
    p = proj / "Trailer/t/exports/t-steam.mp4"
    old_id = items["t-steam.mp4"]["id"]
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42 re-rendered")
    t = time.time() + 5
    os.utime(p, (t, t))
    res = await observe(app, s, text)
    assert res and "t-steam.mp4" in res.note and "first5.png" not in res.note
    # a re-render of the same path updates its item in place: no duplicate row
    after = app.items.list(session_id=s["id"])
    assert len(after) == 2
    steam = next(i for i in after if i["filename"] == "t-steam.mp4")
    assert steam["id"] == old_id and steam["size"] == p.stat().st_size
    assert steam["meta"]["stamp"] == f"{p.stat().st_size}:{int(t)}"
    assert await observe(app, s, text) is None  # and the updated item counts as current


async def test_media_observer_ignores_failed_or_foreign_output(tmp_path):
    app = mo_app(tmp_path)
    proj = tmp_path / "game"
    proj.mkdir()
    (proj / "a.mp4").write_bytes(b"x")
    s = app.store.create(folder=str(proj))
    assert await observe(app, s, "Command declined\nTRAILER_OUTPUT: a.mp4") is None  # never ran
    assert await observe(app, s, "exit code 0\nnothing announced") is None
    chat = app.store.create()  # no folder: nothing to resolve against
    assert await observe(app, chat, "exit code 0\nTRAILER_OUTPUT: a.mp4") is None
    many = "exit code 0\n" + "\n".join(f"ARTIFACT: f{k}.png" for k in range(30))
    for k in range(30):
        (proj / f"f{k}.png").write_bytes(b"\x89PNG")
    await observe(app, s, many)
    assert len(app.items.list(session_id=s["id"])) == media_out.MAX_PER_CALL
    assert media_out.media_paths("exit code 0\n  TRAILER_OUTPUT: 'a b.mp4'  \nARTIFACT: x.wav\nARTIFACT: x.wav") == \
        ["a b.mp4", "x.wav"]


def test_media_observer_is_registered_with_the_app(tmp_path):
    from fastapi.testclient import TestClient

    from gamedevworkstation.server import create_app

    s = AppState(db_path=tmp_path / "s.db")
    s.providers.override("anthropic", "default", FakeProvider())
    with TestClient(create_app("t", s)):
        assert isinstance(s.extensions.get("media_out"), media_out.MediaOutputs)
        assert s.hooks.has("post_tool")
