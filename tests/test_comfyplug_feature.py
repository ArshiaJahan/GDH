"""ComfyPlug inside GDH: the `comfyplug` tool, /api/comfyplug and `gdw comfyplug` (no real ComfyUI)."""
import asyncio
import struct
import threading
import time
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import gamedevworkstation.comfyplug as cp
from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.comfyplug import client as cp_client
from gamedevworkstation.features import comfyplug_feature as F


def png(w=4, h=3) -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("COMFY_URL", raising=False)
    monkeypatch.delenv("COMFY_CLI", raising=False)
    monkeypatch.setitem(cp_client._settings, "url", None)
    monkeypatch.setitem(cp_client._settings, "cli", None)


@pytest.fixture
def app(tmp_path):
    from gamedevworkstation.app import AppState
    from gamedevworkstation.providers.fake import FakeProvider

    a = AppState(db_path=tmp_path / "c.db")
    a.providers.override("anthropic", "default", FakeProvider())
    F.install(a)
    return a


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "game"
    d.mkdir()
    return d


def ctx_for(app, folder):
    return ToolContext(app=app, session=app.store.create(folder=str(folder)), run_id="main:x")


@pytest.fixture
def fake_image(monkeypatch):
    calls = []

    def gen(prompt, out, **kw):
        calls.append({"prompt": prompt, "out": out, "url": cp_client.comfy_url(), **kw})
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(png())
        return out
    monkeypatch.setattr(cp, "generate_image", gen)
    return calls


async def test_tool_is_offered_unless_turned_off(app, proj):
    s = app.store.create(folder=str(proj))
    assert "comfyplug" in [t.name for t in app.tools.specs(session=s)]
    app.config.comfyplug = {"enabled": False}
    assert "comfyplug" not in [t.name for t in app.tools.specs(session=s)]
    with pytest.raises(F.ComfyPlugError, match="turned off"):
        await F.install(app).run({"action": "check"}, session=s, source="user")


async def test_check_reports_the_server_and_tools(app, proj, monkeypatch):
    monkeypatch.setattr(cp_client, "check_server", lambda timeout=5: {
        "system": {"comfyui_version": "0.9.1"}, "devices": [{"name": "cuda:0 RTX"}]})
    monkeypatch.setattr(cp_client, "find_comfy", lambda: "/bin/comfy")
    monkeypatch.setattr(cp_client, "find_ffmpeg", lambda: "/bin/ffmpeg")
    app.config.comfyplug = {"url": "http://10.0.0.9:8188/"}
    out = await app.tools.run(ctx_for(app, proj), "comfyplug", {"action": "check"})
    assert not out.is_error
    assert "ComfyUI at http://10.0.0.9:8188: ok (version 0.9.1, cuda:0 RTX)" in out.text and "/bin/comfy" in out.text

    def down(timeout=5):
        raise cp.ComfyError("ComfyUI is not answering at http://10.0.0.9:8188 (refused).")
    monkeypatch.setattr(cp_client, "check_server", down)
    out = await app.tools.run(ctx_for(app, proj), "comfyplug", {"action": "check"})
    assert out.is_error and "NOT answering" in out.text and "don't try to start" in out.text


async def test_image_lands_in_the_session_folder_as_an_item(app, proj, fake_image):
    app.config.comfyplug = {"url": "http://10.0.0.9:8188"}
    ctx = ctx_for(app, proj)
    out = await app.tools.run(ctx, "comfyplug", {"action": "image", "prompt": "a brass gear", "out": "art/gear",
                                                 "seed": 7, "aspect": "16:9 (Widescreen)", "transparent": True})
    assert not out.is_error, out.text
    target = proj / "art" / "gear.png"
    assert target.is_file() and str(target) in out.text
    c = fake_image[0]
    assert c["seed"] == 7 and c["aspect"] == "16:9 (Widescreen)" and c["transparent"] is True
    assert c["url"] == "http://10.0.0.9:8188"  # the setting is applied for the job
    it = app.items.get(out.items[0])
    assert it["provider"] == "comfyplug" and it["model"] == "qwen-image-2.1" and it["session_id"] == ctx.session_id
    assert it["meta"]["feature"] == "comfyplug:image" and it["meta"]["prompt"] == "a brass gear"
    assert len(out.images) == 1  # the model gets to look at it
    u = app.db.one("SELECT * FROM usage_records WHERE provider='comfyplug'")
    assert u["feature"] == "comfyplug:image" and u["cost_usd"] == 0 and u["role"] == "tool"
    job = app.db.one("SELECT * FROM jobs WHERE kind='comfyplug'")
    assert job["status"] == "done" and job["title"].startswith("Image: a brass gear")


async def test_without_out_it_goes_to_the_media_folder(app, proj, fake_image):
    from gamedevworkstation.config import media_dir

    out = await app.tools.run(ctx_for(app, proj), "comfyplug", {"action": "image", "prompt": "a fox"})
    p = Path(fake_image[0]["out"])
    assert not out.is_error and p.parent == media_dir() / "comfyplug" and p.suffix == ".png"


async def test_paths_outside_the_session_folder_are_refused(app, proj, tmp_path, fake_image):
    out = await app.tools.run(ctx_for(app, proj), "comfyplug",
                              {"action": "image", "prompt": "x", "out": str(tmp_path / "elsewhere.png")})
    assert out.is_error and not fake_image
    out = await app.tools.run(ctx_for(app, proj), "comfyplug", {"action": "image", "prompt": "x", "out": "../up.png"})
    assert out.is_error and not fake_image


@pytest.mark.parametrize("args,msg", [
    ({"action": "image"}, "needs a prompt"),
    ({"action": "image", "prompt": "x", "steps": 0}, "steps must be"),
    ({"action": "image", "prompt": "x", "seed": True}, "seed must be"),
    ({"action": "edit", "prompt": "x"}, "needs image"),
    ({"action": "edit", "prompt": "x", "image": "nope.png"}, "no such file"),
    ({"action": "edit", "prompt": "x", "image": "in.png", "width": 512}, "both width and height"),
    ({"action": "model", "prompt": "x", "out": "m.fbx"}, ".glb"),
    ({"action": "sound", "prompt": "x", "variants": 99}, "variants must be"),
    ({"action": "workflow"}, "needs workflow"),
    ({"action": "workflow", "workflow": "wf.json", "slots": {"seed": 1}}, "slots must be"),
    ({"action": "dance"}, "action must be one of"),
])
async def test_bad_arguments_fail_before_any_job(app, proj, args, msg):
    (proj / "in.png").write_bytes(png())
    (proj / "wf.json").write_text("{}", encoding="utf-8")
    out = await app.tools.run(ctx_for(app, proj), "comfyplug", args)
    assert out.is_error and msg in out.text
    assert app.db.one("SELECT COUNT(*) AS n FROM jobs")["n"] == 0


async def test_edit_takes_an_item_id(app, proj, monkeypatch):
    src = proj / "in.png"
    src.write_bytes(png())
    s = app.store.create(folder=str(proj))
    iid = app.items.add_file(src, source="user", session_id=s["id"], provider=None, model=None)
    seen = {}

    def edit(src_, prompt, out, **kw):
        seen.update(src=src_, prompt=prompt, **kw)
        Path(out).write_bytes(png())
        return out
    monkeypatch.setattr(cp, "edit_image", edit)
    out = await app.tools.run(ToolContext(app=app, session=s, run_id="main:x"), "comfyplug",
                              {"action": "edit", "image": iid, "prompt": "make it night", "out": "night.png"})
    assert not out.is_error, out.text
    assert seen["src"] == str(src) and seen["prompt"] == "make it night" and seen["width"] is None
    assert app.items.get(out.items[0])["model"] == "qwen-image-2.1-edit"


async def test_model_reference_first_then_the_glb(app, proj, monkeypatch):
    calls = []

    def gen(prompt, out_glb, **kw):
        calls.append(kw)
        ref = str(Path(out_glb).with_name(Path(out_glb).stem + "_ref.png"))
        Path(out_glb).parent.mkdir(parents=True, exist_ok=True)
        if kw["ref_only"]:
            Path(ref).write_bytes(png())
            return {"glb": None, "ref": ref, "prompt_id": None}
        Path(out_glb).write_bytes(b"glTF")
        return {"glb": out_glb, "ref": kw["from_image"], "prompt_id": "p"}
    monkeypatch.setattr(cp, "generate_model", gen)
    ctx = ctx_for(app, proj)
    out = await app.tools.run(ctx, "comfyplug", {"action": "model", "prompt": "a lantern", "out": "m/lantern.glb",
                                                 "ref_only": True})
    assert not out.is_error and "reference image only" in out.text and len(out.images) == 1
    assert len(out.items) == 1 and (proj / "m" / "lantern_ref.png").is_file()
    out = await app.tools.run(ctx, "comfyplug", {"action": "model", "prompt": "a lantern", "out": "m/lantern.glb",
                                                 "from_image": "m/lantern_ref.png", "faces": 8000})
    assert not out.is_error, out.text
    assert calls[1]["from_image"] == str(proj / "m" / "lantern_ref.png") and calls[1]["faces"] == 8000
    assert [Path(app.items.get(i)["path"]).name for i in out.items] == ["lantern.glb"]


async def test_sound_variants_keep_the_good_takes(app, proj, monkeypatch):
    def variants(prompt, out_dir, name, n=3, **kw):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        outs = []
        for i in range(1, n + 1):
            p = Path(out_dir) / f"{name}_{i}.wav"
            if i == 2:
                outs.append((str(p), "take failed"))
            else:
                p.write_bytes(b"RIFF")
                outs.append(str(p))
        return outs
    monkeypatch.setattr(cp, "generate_variants", variants)
    out = await app.tools.run(ctx_for(app, proj), "comfyplug",
                              {"action": "sound", "prompt": "a clank", "out": "sfx/clank.wav", "variants": 3})
    assert not out.is_error and len(out.items) == 2 and "clank_1.wav" in out.text and "clank_3.wav" in out.text

    monkeypatch.setattr(cp, "generate_variants", lambda prompt, d, name, n=3, **kw: [(f"{d}/{name}_1.wav", "x")])
    out = await app.tools.run(ctx_for(app, proj), "comfyplug",
                              {"action": "sound", "prompt": "a clank", "out": "sfx/clank.wav", "variants": 1})
    assert out.is_error and "every take failed" in out.text
    assert app.db.one("SELECT status FROM jobs ORDER BY started_at DESC LIMIT 1")["status"] == "failed"


async def test_any_workflow_keeps_video_outputs(app, proj, monkeypatch):
    (proj / "wf").mkdir()
    (proj / "wf" / "video.json").write_text("{}", encoding="utf-8")
    seen = []

    def run_any(wf, out_dir, slots, exts, timeout, prefix=None):
        seen.append({"wf": wf, "slots": slots, "exts": exts, "timeout": timeout, "prefix": prefix})
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        p = Path(out_dir) / f"{prefix}_1.mp4"
        p.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return [str(p)]
    monkeypatch.setattr(cp, "run_any", run_any)
    app.config.comfyplug = {"timeout_s": 600}
    out = await app.tools.run(ctx_for(app, proj), "comfyplug", {
        "action": "workflow", "workflow": "wf/video.json", "out": "clips/intro", "slots": {"6.text": "a red fox"},
        "exts": [".mp4"]})
    assert not out.is_error, out.text
    assert seen[0] == {"wf": str(proj / "wf" / "video.json"), "slots": {"6.text": "a red fox"}, "exts": [".mp4"],
                       "timeout": 600, "prefix": "intro"}
    it = app.items.get(out.items[0])
    assert it["path"] == str(proj / "clips" / "intro" / "intro_1.mp4") and it["mime"] == "video/mp4"
    assert out.images == []

    await app.tools.run(ctx_for(app, proj), "comfyplug", {"action": "workflow", "workflow": "stable_audio3.json"})
    assert seen[1]["wf"] == "stable_audio3.json"  # a bundled template by name


async def test_jobs_run_one_at_a_time(app, proj, monkeypatch):
    active, peak = [0], [0]
    gate = threading.Lock()

    def gen(prompt, out, **kw):
        with gate:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        Path(out).write_bytes(png())
        with gate:
            active[0] -= 1
        return out
    monkeypatch.setattr(cp, "generate_image", gen)
    outs = await asyncio.gather(*(app.tools.run(ctx_for(app, proj), "comfyplug",
                                                {"action": "image", "prompt": f"p{i}", "out": f"{i}.png"})
                                  for i in range(3)))
    assert all(not o.is_error for o in outs) and peak[0] == 1


def test_rest_routes(app, proj, monkeypatch, fake_image):
    from gamedevworkstation.server import create_app

    monkeypatch.setattr(cp_client, "check_server", lambda timeout=5: {"system": {"comfyui_version": "1"}})
    monkeypatch.setattr(cp_client, "find_comfy", lambda: "/bin/comfy")

    def no_ffmpeg():
        raise cp.ComfyError("ffmpeg not found on PATH")
    monkeypatch.setattr(cp_client, "find_ffmpeg", no_ffmpeg)
    c = TestClient(create_app("t", app), headers={"Authorization": "Bearer t"})
    st = c.get("/api/comfyplug/status").json()
    assert st["server"]["ok"] and st["comfy_cli"] == "/bin/comfy" and st["ffmpeg"] is None and "ffmpeg" in st["ffmpeg_error"]
    s = app.store.create(folder=str(proj))
    r = c.post("/api/comfyplug/run", json={"action": "image", "prompt": "a gear", "out": "g.png", "session_id": s["id"]})
    assert r.status_code == 200 and r.json()["paths"] == [str(proj / "g.png")]
    assert app.items.get(r.json()["items"][0])["source"] == "user"
    assert c.post("/api/comfyplug/run", json={"action": "image"}).status_code == 400
    assert c.post("/api/comfyplug/run", json={"action": "image", "prompt": "x", "session_id": "nope"}).status_code == 404


def test_gdw_comfyplug_uses_the_settings_url(monkeypatch, tmp_path, capsys):
    import os

    home = Path(os.environ["GDW_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text('[comfyplug]\nurl = "http://10.1.1.1:8188"\n', encoding="utf-8")
    seen = []

    def check(timeout=5):
        seen.append(cp_client.comfy_url())
        raise cp.ComfyError("not answering")
    monkeypatch.setattr(cp_client, "check_server", check)
    assert F.cli(["check"]) == 1 and seen == ["http://10.1.1.1:8188"]
    monkeypatch.setenv("COMFY_URL", "http://10.2.2.2:8188")
    assert F.cli(["check"]) == 1 and seen[-1] == "http://10.2.2.2:8188"  # the environment wins
    assert "FAILED" in capsys.readouterr().err
