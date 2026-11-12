"""Live events (slow clients cut off, deltas coalesced, resync when replay is too long), message
paging, and attachments that can't break a session."""
import asyncio
import base64
import json
import shutil

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from workspace import events as ev_mod
from workspace import server as server_mod
from workspace.app import AppState
from workspace.core.media import MAX_IMAGE_BYTES, image_payload
from workspace.core.types import ImageBlock, Message
from workspace.events import EventBus, Subscriber
from workspace.providers.anthropic_provider import block_to_wire
from workspace.providers.fake import FakeProvider, text_response
from workspace.providers.openai_provider import user_part
from workspace.server import create_app

TOKEN = "t"
H = {"Authorization": f"Bearer {TOKEN}"}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture
def state(tmp_path):
    return AppState(db_path=tmp_path / "s.db")


@pytest.fixture
def client(state):
    with TestClient(create_app(TOKEN, state)) as c:
        yield c


# ------------------------------------------------------------------ event bus


async def test_slow_subscriber_is_cut_off_not_left_hanging(state):
    bus: EventBus = state.bus
    q = bus.subscribe(maxsize=5)
    for i in range(10):
        bus.publish("groups.updated", {"i": i})
    assert q.overflowed and q.closed and q not in bus._subs
    assert await asyncio.wait_for(q.get(), 1) is None  # the send loop ends instead of waiting forever


async def test_deltas_coalesce_while_a_client_is_behind(state):
    q = state.bus.subscribe()
    for _ in range(200):
        state.bus.publish("message.delta", {"id": "m1", "text": "ab"}, "s1")
    state.bus.publish("message.delta", {"id": "m2", "text": "z"}, "s1")
    state.bus.publish("terminal.output", {"tab": "t", "data": "x"}, "s1")
    state.bus.publish("terminal.output", {"tab": "t", "data": "y"}, "s1")
    got = [q.get_nowait() for _ in range(q.qsize())]
    assert [e["type"] for e in got] == ["message.delta", "message.delta", "terminal.output"]
    assert got[0]["data"]["text"] == "ab" * 200 and got[1]["data"]["text"] == "z" and got[2]["data"]["data"] == "xy"


def test_subscriber_preserves_order_across_types():
    s = Subscriber(10)
    for t in ("message.delta", "message.created", "message.delta"):
        s.put({"type": t, "session_id": "a", "data": {"id": "m", "text": "q"}, "ts": 0, "seq": None})
    assert [s.get_nowait()["type"] for _ in range(3)] == ["message.delta", "message.created", "message.delta"]


def test_ws_overflow_closes_socket_so_client_reconnects(client, state, monkeypatch):
    monkeypatch.setattr(state.bus, "subscribe", lambda maxsize=5: EventBus.subscribe(state.bus, 5))
    with client.websocket_connect(f"/ws?token={TOKEN}&since={state.bus.last_seq()}") as ws:
        while json.loads(ws.receive_text())["type"] != "ws.ready":
            pass

        def burst():
            for i in range(20):
                state.bus.publish("groups.updated", {"i": i})

        client.portal.call(burst)
        with pytest.raises(WebSocketDisconnect) as e:
            while True:
                ws.receive_text()
        assert e.value.code == server_mod.WS_OVERFLOW


def test_ws_resync_when_too_far_behind(client, state, monkeypatch):
    monkeypatch.setattr(server_mod, "REPLAY_MAX", 3)
    for i in range(6):
        state.bus.publish("groups.updated", {"i": i})
    with client.websocket_connect(f"/ws?token={TOKEN}&since=0") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "ws.resync" and first["seq"] == state.bus.last_seq()
        assert json.loads(ws.receive_text())["type"] == "ws.ready"
    seq = state.bus.last_seq()
    state.bus.publish("groups.updated", {"i": 99})
    with client.websocket_connect(f"/ws?token={TOKEN}&since={seq}") as ws:  # close enough: a normal replay
        assert json.loads(ws.receive_text())["data"] == {"i": 99}


# -------------------------------------------------------------------- paging


def test_message_pages_newest_first_and_hide_compacted(client, state):
    sid = client.post("/api/sessions", json={}, headers=H).json()["id"]
    ids = [state.store.add_message(sid, Message.user(f"m{i}")).id for i in range(10)]
    state.store.mark_compacted(ids[:3])
    p = client.get(f"/api/sessions/{sid}/messages/page?limit=4", headers=H).json()
    assert [m["content"][0]["text"] for m in p["messages"]] == ["m6", "m7", "m8", "m9"]
    assert p["has_more"] and p["compacted"] == 3
    p2 = client.get(f"/api/sessions/{sid}/messages/page?limit=4&before={p['messages'][0]['id']}", headers=H).json()
    assert [m["content"][0]["text"] for m in p2["messages"]] == ["m3", "m4", "m5"] and not p2["has_more"]
    p3 = client.get(f"/api/sessions/{sid}/messages/page?limit=50&compacted=1", headers=H).json()
    assert len(p3["messages"]) == 10 and p3["messages"][0]["meta"]["compacted"] and p3["compacted"] == 3
    assert len(client.get(f"/api/sessions/{sid}/messages", headers=H).json()) == 10  # unchanged for API clients


# ---------------------------------------------------------------- attachments


def test_missing_huge_or_odd_images_become_notes(tmp_path):
    ok = tmp_path / "ok.png"
    ok.write_bytes(PNG)
    assert block_to_wire(ImageBlock(media_type="image/png", path=str(ok), name="ok.png"), "user")["type"] == "image"
    gone = ImageBlock(media_type="image/png", path=str(tmp_path / "deleted.png"), name="deleted.png")
    w = block_to_wire(gone, "user")
    assert w["type"] == "text" and "no longer available" in w["text"]
    assert user_part(gone)["type"] == "input_text"
    big = tmp_path / "big.png"
    big.write_bytes(b"\0" * (MAX_IMAGE_BYTES + 1))
    assert "over the model's image limit" in image_payload("image/png", None, str(big), "big.png")
    heic = tmp_path / "x.heic"
    heic.write_bytes(b"....")
    assert "isn't a format" in image_payload("image/heic", None, str(heic), "x.heic")


async def test_a_deleted_attachment_doesnt_break_later_turns(state, tmp_path):
    from workspace.providers.anthropic_provider import messages_to_wire

    img = tmp_path / "photo.png"
    img.write_bytes(PNG)
    fake = FakeProvider()
    fake.script = [text_response("seen"), text_response("still fine")]
    state.providers.override("anthropic", "default", fake)
    s = state.store.create(effort="low")
    state.store.add_message(s["id"], Message.user("look", ImageBlock(media_type="image/png", path=str(img), name="p")))
    await state.runner.start(s["id"])
    img.unlink()
    state.store.add_message(s["id"], Message.user("and now?"))
    await state.runner.start(s["id"])
    assert state.store.messages(s["id"])[-1].text() == "still fine"
    wire = messages_to_wire(fake.calls[-1].messages)
    assert "no longer available" in json.dumps(wire)


@pytest.mark.skipif(not shutil.which("sips"), reason="needs macOS sips")
def test_upload_converts_unsupported_images_and_keeps_the_original(client, state, tmp_path):
    # A 1x1 BMP: a format providers don't take inline.
    bmp = (b"BM" + (58).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little") + (40).to_bytes(4, "little")
           + (1).to_bytes(4, "little") * 2 + (1).to_bytes(2, "little") + (24).to_bytes(2, "little")
           + b"\0" * 4 + (4).to_bytes(4, "little") + b"\0" * 16 + b"\xff\0\0\0")
    r = client.post("/api/uploads", files={"file": ("pic.bmp", bmp, "image/bmp")}, headers=H).json()
    assert r["send_mime"] == "image/jpeg" and r["send_path"].endswith(".jpg") and "note" in r
    assert r["path"].endswith("pic.bmp")
    sid = client.post("/api/sessions", json={}, headers=H).json()["id"]
    state.providers.override("anthropic", "default", FakeProvider())
    client.post(f"/api/sessions/{sid}/messages", json={"text": "see", "attachments": [r]}, headers=H)
    msg = state.store.messages(sid)[0]
    b = msg.content[1]
    assert b.path == r["send_path"] and b.media_type == "image/jpeg"
    assert state.items.get(b.item_id)["path"] == r["path"]  # the item is the original file


def test_request_media_is_capped_oldest_first():
    from workspace.core.media import cap_media

    img = lambda n: {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A" * n}}  # noqa: E731
    wire = [{"role": "user", "content": [img(10), {"type": "text", "text": "x"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "y"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": [img(10)]}, img(10)]}]
    cap_media(wire, limit=25)
    assert wire[0]["content"][0]["type"] == "text" and "left out" in wire[0]["content"][0]["text"]
    assert wire[2]["content"][0]["content"][0]["type"] == "image" and wire[2]["content"][1]["type"] == "image"
    oa = [{"role": "user", "content": [{"type": "input_image", "image_url": "data:image/png;base64," + "A" * 30}]}]
    assert cap_media(oa, limit=10)[0]["content"][0]["type"] == "input_text"


def test_regex_guard_catches_catastrophic_shapes():
    from workspace.agent.builtin_tools import _risky_regex

    for bad in ("(a+)+", "((a+))+", "(a|aa)+$", "(.*a){10}", "(x*)*"):
        assert _risky_regex(bad), bad
    for ok in ("foo.*bar", "(abc)+", r"\(a+\)+", r"def (\w+)\(", "[(]+)+"):
        assert not _risky_regex(ok), ok
