"""Review 3 (data): purge cleans converted copies and job logs, image dimension limits, auto-compaction
without a cut point, notices kept from models, the pre-migration config backup and value validation."""
import time

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.config import data_dir, media_dir
from gamedevworkstation.core.types import ImageBlock, Message, TextBlock, ToolResultBlock, ToolUseBlock
from gamedevworkstation.server import create_app

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def state(tmp_path):
    return AppState(db_path=tmp_path / "t.db")


@pytest.fixture
def client(state):
    with TestClient(create_app(TOKEN, state)) as c:
        yield c


# ------------------------------------------------------------------ 1: purge


def test_purge_removes_converted_copies_upload_folders_and_job_logs(client, state):
    keep = client.post("/api/sessions", json={"title": "keep"}, headers=H).json()["id"]
    sid = client.post("/api/sessions", json={"title": "gone"}, headers=H).json()["id"]
    up = media_dir() / "uploads" / "u1"
    (up / "send").mkdir(parents=True)
    orig, sent = up / "photo.heic", up / "send" / "abc.jpg"
    orig.write_bytes(b"heic")
    sent.write_bytes(b"jpg")
    conv = media_dir() / "converted"
    conv.mkdir(parents=True)
    own_conv, shared_conv = conv / "own.jpg", conv / "shared.jpg"
    own_conv.write_bytes(b"jpg")
    shared_conv.write_bytes(b"jpg")
    tool_img = media_dir() / "shot.png"  # an image in a tool result
    tool_img.write_bytes(b"png")
    # A second upload folder that a duplicate still shows: kept whole.
    up2 = media_dir() / "uploads" / "u2"
    (up2 / "send").mkdir(parents=True)
    (up2 / "a.png").write_bytes(b"png")
    (up2 / "send" / "x.jpg").write_bytes(b"jpg")

    state.items.add_file(orig, source="user", session_id=sid, provider="anthropic", model="m")
    state.store.add_message(sid, Message(role="user", content=[
        ImageBlock(media_type="image/jpeg", path=str(sent), name="photo.heic"),
        ImageBlock(media_type="image/jpeg", path=str(own_conv)),
        ImageBlock(media_type="image/jpeg", path=str(shared_conv)),
        ImageBlock(media_type="image/png", path=str(up2 / "send" / "x.jpg"))]))
    state.store.add_message(sid, Message(role="user", meta={"tool_results": True}, content=[
        ToolResultBlock(tool_use_id="t1", content=[ImageBlock(media_type="image/png", path=str(tool_img))])]))
    state.store.add_message(keep, Message(role="user", content=[
        ImageBlock(media_type="image/jpeg", path=str(shared_conv)),
        ImageBlock(media_type="image/png", path=str(up2 / "a.png"))]))
    jid = state.jobs.start(sid, "command", "ls")
    other_jid = state.jobs.start(keep, "command", "ls")
    jdir = data_dir() / "jobs"
    jdir.mkdir(parents=True, exist_ok=True)
    (jdir / f"{jid}.log").write_text("secret output")
    (jdir / f"{other_jid}.log").write_text("other output")
    outside = data_dir().parent / "outside.jpg"  # never anything outside the data dir
    outside.write_bytes(b"x")
    state.store.add_message(sid, Message(role="user", content=[ImageBlock(media_type="image/jpeg", path=str(outside))]))

    assert client.delete(f"/api/sessions/{sid}?purge=1", headers=H).json()["purged"]

    assert not up.exists()  # original, send/ copy and the folder itself
    assert not own_conv.exists() and shared_conv.exists()
    assert not tool_img.exists()
    assert (up2 / "a.png").exists() and (up2 / "send" / "x.jpg").exists()
    assert not (jdir / f"{jid}.log").exists() and (jdir / f"{other_jid}.log").exists()
    assert outside.exists()


# ------------------------------------------------------------ 2: image dimensions

import base64  # noqa: E402
import struct  # noqa: E402
import zlib  # noqa: E402

from gamedevworkstation.core import media  # noqa: E402

needs_sips = pytest.mark.skipif(media._sips() is None, reason="needs macOS sips")


def png(w: int, h: int) -> bytes:
    """A valid grayscale PNG (tiny on disk however large in pixels)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + bytes(w) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def jpeg_header(w: int, h: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0\x01\x01\0\0\x01\0\x01\0\0"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof


def test_image_dims_reads_headers():
    assert media.image_dims(png(3000, 2)) == (3000, 2)
    assert media.image_dims(jpeg_header(4032, 3024)) == (4032, 3024)
    assert media.image_dims(b"GIF89a" + struct.pack("<HH", 640, 480)) == (640, 480)
    vp8x = b"RIFF\0\0\0\0WEBPVP8X" + b"\0" * 8 + (2999).to_bytes(3, "little") + (99).to_bytes(3, "little")
    assert media.image_dims(vp8x) == (3000, 100)
    assert media.image_dims(b"not an image") is None
    assert media.MAX_SIDE <= 2000


def test_small_images_are_sent_as_they_are(tmp_path):
    p = tmp_path / "s.png"
    p.write_bytes(png(800, 600))
    assert media.prepare_image(p, "image/png", tmp_path / "out") == (str(p), "image/png", None)


@needs_sips
def test_images_over_the_pixel_limit_are_resized_at_attach_time(tmp_path):
    p = tmp_path / "wide.png"
    p.write_bytes(png(3000, 40))  # a few KB, but 3000 px wide
    send, mime, note = media.prepare_image(p, "image/png", tmp_path / "out")
    assert send != str(p) and mime == "image/png" and "3000×40" in note
    assert max(media.file_dims(media.Path(send))) <= media.MAX_SIDE
    assert media.image_dims(p.read_bytes()) == (3000, 40)  # the original is untouched


@needs_sips
def test_oversized_images_in_tool_results_are_shrunk_per_request(tmp_path):
    from gamedevworkstation.providers.anthropic_provider import messages_to_wire

    data = base64.b64encode(png(2600, 30)).decode()
    msgs = [Message(role="user", content=[TextBlock(text="hi")]),
            Message(role="assistant", content=[ToolUseBlock(id="t1", name="shot", input={})]),
            Message(role="user", content=[ToolResultBlock(tool_use_id="t1", content=[
                ImageBlock(media_type="image/png", data=data)])])]
    wire = messages_to_wire(msgs)
    img = wire[-1]["content"][0]["content"][0]
    assert img["type"] == "image"
    assert max(media.image_dims(base64.b64decode(img["source"]["data"]))) <= media.MAX_SIDE


def test_without_sips_only_what_no_provider_takes_is_stubbed(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_sips", lambda: None)
    media._FIT_CACHE.clear()
    ok, huge = tmp_path / "ok.png", tmp_path / "huge.png"
    ok.write_bytes(png(2500, 2))
    huge.write_bytes(png(9000, 2))
    assert media.image_payload("image/png", None, str(ok), "ok.png")[0] == "image/png"
    note = media.image_payload("image/png", None, str(huge), "huge.png")
    assert isinstance(note, str) and "9000×2" in note


def test_stub_rejected_images_leaves_out_only_the_offending_ones(tmp_path):
    big, small = tmp_path / "big.png", tmp_path / "small.png"
    big.write_bytes(png(2500, 2))
    small.write_bytes(png(500, 2))
    msgs = [Message(role="user", content=[ImageBlock(media_type="image/png", path=str(big), name="big.png"),
                                          ImageBlock(media_type="image/png", path=str(small), name="small.png")])]
    err = ("Error code: 400 - messages.0.content.0.image.source.base64: image dimensions exceed max allowed "
           "size for many-image requests: 2000 pixels")
    assert media.is_image_rejected(400, err)
    assert not media.is_image_rejected(400, "prompt is too long")
    out, n = media.stub_rejected_images(msgs, err)
    assert n == 1 and isinstance(out[0].content[0], TextBlock) and "big.png" in out[0].content[0].text
    assert isinstance(out[0].content[1], ImageBlock)
    assert isinstance(msgs[0].content[0], ImageBlock)  # the stored messages are untouched
    out, n = media.stub_rejected_images(msgs, "image is too large")  # no limit stated: every image
    assert n == 2


async def test_image_rejection_retries_without_the_image(tmp_path):
    from fastapi import APIRouter, FastAPI

    from gamedevworkstation.providers.base import ProviderError
    from gamedevworkstation.providers.fake import FakeProvider, text_response
    from gamedevworkstation.routes import register_routes

    app = AppState(db_path=tmp_path / "c.db")
    register_routes(FastAPI(), APIRouter(), app)
    big = tmp_path / "big.png"
    big.write_bytes(png(2500, 2))
    s = app.store.create(effort="low")
    app.store.add_message(s["id"], Message(role="user", content=[
        TextBlock(text="look"), ImageBlock(media_type="image/png", path=str(big), name="big.png")]))

    def reject(req):
        raise ProviderError("Error code: 400 - image dimensions exceed max allowed size for many-image "
                            "requests: 2000 pixels", status=400)

    fake = FakeProvider("anthropic", [reject, text_response("seen")])
    app.providers.override("anthropic", "default", fake)
    await app.runner.start(s["id"])
    msgs = app.store.messages(s["id"])
    assert msgs[-1].text() == "seen" and not any(m.meta.get("error") for m in msgs)
    assert any(m.meta.get("notice") == "image_rejected" for m in msgs)
    sent = fake.calls[-1].messages[0].content
    assert isinstance(sent[1], TextBlock) and "left out" in sent[1].text
    assert isinstance(msgs[0].content[1], ImageBlock)  # kept in the session


# ------------------------------------------------------------------ 5: notices


@pytest.fixture
def app(tmp_path):
    from fastapi import APIRouter, FastAPI

    from gamedevworkstation.routes import register_routes

    a = AppState(db_path=tmp_path / "n.db")
    register_routes(FastAPI(), APIRouter(), a)
    return a


def notice(text: str) -> Message:
    return Message(role="assistant", content=[TextBlock(text=text)], meta={"notice": "max_tokens"})


def test_harness_recap_leaves_out_notices(app):
    s = app.store.create()
    app.store.add_message(s["id"], Message.user("first question"))
    app.store.add_message(s["id"], Message.assistant("first answer"))
    app.store.add_message(s["id"], notice("NOTICE-TEXT the reply hit the output limit"))
    last = app.store.add_message(s["id"], Message.user("next"))
    recap = app.extensions["harnesses"]._recap(s["id"], last)
    assert "first answer" in recap and "NOTICE-TEXT" not in recap


@pytest.mark.auto_title
async def test_title_generation_ignores_notices(app):
    from gamedevworkstation.providers.fake import FakeProvider, text_response

    s = app.store.create()
    app.store.add_message(s["id"], Message.user("plan a trip"))
    app.store.add_message(s["id"], notice("NOTICE-TEXT paused after 60 model calls"))
    from gamedevworkstation.features.sessions_mgmt import Titler

    titler = Titler(app)
    assert not titler.wants_title(s["id"])  # a notice isn't a reply
    app.store.add_message(s["id"], Message.assistant("Here is a plan."))
    assert titler.wants_title(s["id"])
    fake = FakeProvider("anthropic", [text_response("Trip Plan")])
    app.providers.override("anthropic", "default", fake)
    await titler.generate(s["id"])
    assert "NOTICE-TEXT" not in fake.calls[-1].messages[-1].text()


async def test_compaction_hides_notices_before_the_cut(app):
    from gamedevworkstation.agent import context as cx
    from gamedevworkstation.providers.fake import FakeProvider, text_response

    s = app.store.create()
    sid = s["id"]
    for i in range(5):
        app.store.add_message(sid, Message.user(f"q{i}"))
        app.store.add_message(sid, Message.assistant(f"a{i}"))
        app.store.add_message(sid, notice(f"notice {i}"))
        time.sleep(0.002)
    app.providers.override("anthropic", "default", FakeProvider("anthropic", [text_response("- summary")]))
    msgs = app.runner.model_history(sid)
    cut = cx.manual_cut(msgs)
    assert cut is not None
    first_kept = msgs[cut].meta["created_at"]
    await cx.compact_messages(app, sid, msgs, cut)
    visible = app.store.messages(sid, include_compacted=False)
    shown = [m.text() for m in visible if m.meta.get("notice")]
    hidden = [m.text() for m in app.store.messages(sid) if m.meta.get("notice") and m.meta["compacted"]]
    assert hidden and all(m.meta["created_at"] >= first_kept for m in visible if m.meta.get("notice"))
    assert "notice 4" in shown and "notice 0" in hidden


# --------------------------------------------------------------------- 6: config

import tomllib  # noqa: E402

from gamedevworkstation import config as config_mod  # noqa: E402


def test_pre_migration_backup_is_kept_apart_from_save_backups(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "config_path", lambda: tmp_path / "config.toml")
    p = tmp_path / "config.toml"
    full = config_mod.DEFAULT_CONFIG_PATH.read_text().replace("trash_days = 30", "trash_days = 9")
    p.write_text(full)
    config_mod.load_config(p)
    pre = tmp_path / config_mod.PRE_OVERRIDES_BACKUP
    assert pre.read_text() == full
    config_mod.save_config_patch({"limits": {"global_daily_usd": 7}}, p)
    config_mod.save_config_patch({"limits": {"global_daily_usd": 8}}, p)
    assert pre.read_text() == full  # later saves only replace config.toml.bak
    assert (tmp_path / "config.toml.bak").read_text() != full


def test_wrong_typed_settings_are_ignored_with_a_banner(client, monkeypatch):
    monkeypatch.setattr(config_mod, "_load_error", None)
    monkeypatch.setattr(config_mod, "_invalid", None)
    p = config_mod.config_path()
    p.write_text(f'config_version = {config_mod.CONFIG_FORMAT}\n'
                 '[orchestrator]\nmax_tokens = "lots"\ntool_output_chars = "40000"\n'
                 '[sessions]\ntrash_days = -3\nevent_retention_days = 3\nauto_title = "yes"\n'
                 '[delegation]\nmax_parallel = { claude_codex = "four", codex_cli = 1 }\n'
                 '[limits]\nsession_usd = 4\n')
    cfg = config_mod.load_config()
    assert cfg.orchestrator["max_tokens"] == 32000  # the default
    assert cfg.orchestrator["tool_output_chars"] == 40000  # a number written as a string is converted
    assert cfg.sessions["trash_days"] == 30 and cfg.sessions["event_retention_days"] == 3
    assert cfg.sessions["auto_title"] is True
    assert cfg.delegation["max_parallel"] == {"claude_codex": 4, "codex_cli": 1}
    assert cfg.limits["session_usd"] == 4 and cfg.limits["global_daily_usd"] == 25
    assert not list(p.parent.glob("config.toml.broken-*"))  # the file stays, for the user to fix
    err = config_mod.load_error()
    assert err["keys"] == ["orchestrator.max_tokens", "delegation.max_parallel.claude_codex",
                           "sessions.trash_days", "sessions.auto_title"]
    assert "orchestrator.max_tokens" in err["message"]
    # Settings refuses wrong types, and fixing the value clears the banner.
    r = client.patch("/api/settings", json={"orchestrator": {"max_tokens": "big"}}, headers=H)
    assert r.status_code == 400 and "orchestrator.max_tokens" in r.text
    for patch in ({"orchestrator": {"max_tokens": 16000}}, {"delegation": {"max_parallel": {"claude_codex": 3}}}):
        assert client.patch("/api/settings", json=patch, headers=H).status_code == 200
    config_mod.save_config_patch({"sessions": {"trash_days": 10, "auto_title": False}})
    assert config_mod.load_error() is None
    assert tomllib.loads(p.read_text())["orchestrator"]["max_tokens"] == 16000


@pytest.mark.auto_title
async def test_claude_code_sessions_skip_the_api_title_call(app):
    from gamedevworkstation.features.sessions_mgmt import Titler

    s = app.store.create()
    app.store.add_message(s["id"], Message.user("plan a trip"))
    app.store.add_message(s["id"], Message.assistant("Here is a plan."))
    titler = Titler(app)
    assert titler.wants_title(s["id"])
    app.store.update(s["id"], harness="claude_code")
    assert app.store.get(s["id"])["harness"] == "claude_code"
    assert not titler.wants_title(s["id"])  # subscription session: never bills the API for a title
