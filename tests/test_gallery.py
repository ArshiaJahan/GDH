"""Gallery: /api/gallery list (scoping, order), the file route, screenshot requests and the live event."""
import time

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "g.db")
    with TestClient(create_app("t", s)) as c:
        yield c, s, tmp_path


def _media(s, tmp_path, sid, name, source="tool", data=b"\x89PNG"):
    p = tmp_path / name
    p.write_bytes(data)
    return s.items.add_file(p, source=source, session_id=sid, provider=None, model=None, extracted_text="")


def test_list_is_session_scoped_newest_first_and_media_only(env):
    c, s, tmp = env
    a, b = s.store.create(title="A")["id"], s.store.create(title="B")["id"]
    i1 = _media(s, tmp, a, "one.png")
    time.sleep(0.01)
    i2 = _media(s, tmp, a, "two.mp4", data=b"x")
    time.sleep(0.01)
    i3 = _media(s, tmp, a, "three.mp3", data=b"ID3")
    _media(s, tmp, b, "other.png")
    _media(s, tmp, a, "upload.png", source="user")
    (tmp / "doc.txt").write_text("x")
    s.items.add_file(tmp / "doc.txt", source="agent", session_id=a, provider=None, model=None)
    r = c.get("/api/gallery", params={"session_id": a}, headers=H)
    assert r.status_code == 200
    got = r.json()
    assert [e["id"] for e in got] == [i3, i2, i1]
    assert [e["kind"] for e in got] == ["audio", "video", "image"]
    e = got[2]
    assert {"id", "kind", "path", "url", "title", "created_at", "source"} <= set(e)
    assert e["url"] == f"/api/gallery/file/{i1}?session_id={a}" and e["path"].endswith("one.png")
    assert [e["id"] for e in c.get("/api/gallery", params={"session_id": a, "kinds": "image"}, headers=H).json()] == [i1]
    assert c.get("/api/gallery", params={"session_id": "nope"}, headers=H).status_code == 404
    assert c.get("/api/gallery", params={"session_id": a}).status_code == 401


def test_file_route_serves_only_registered_media_of_the_session(env):
    c, s, tmp = env
    a, b = s.store.create(folder=str(tmp))["id"], s.store.create()["id"]
    iid = _media(s, tmp, a, "pic.png", data=b"PNGDATA")
    r = c.get(f"/api/gallery/file/{iid}", params={"session_id": a}, headers=H)
    assert r.status_code == 200 and r.content == b"PNGDATA"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert c.get(f"/api/gallery/file/{iid}", params={"session_id": b}, headers=H).status_code == 404
    # A path is never accepted, only item ids.
    secret = tmp / "secret.png"
    secret.write_bytes(b"s")
    for bad in (str(secret), "../secret.png", "itm_missing"):
        assert c.get(f"/api/gallery/file/{bad}", params={"session_id": a}, headers=H).status_code in (404, 422), bad
    # Non-media items (even registered) and deleted ones are refused.
    (tmp / "n.txt").write_text("x")
    tid = s.items.add_file(tmp / "n.txt", source="agent", session_id=a, provider=None, model=None)
    assert c.get(f"/api/gallery/file/{tid}", params={"session_id": a}, headers=H).status_code == 404
    s.items.delete(iid)
    assert c.get(f"/api/gallery/file/{iid}", params={"session_id": a}, headers=H).status_code == 404


def test_screenshot_post_creates_pending_then_fails(env):
    c, s, _ = env
    a = s.store.create()["id"]
    sub = s.bus.subscribe()
    r = c.post("/api/gallery/screenshot", json={"session_id": a, "prompt": "  the main menu  "}, headers=H)
    assert r.status_code == 200
    e = r.json()
    assert e["status"] == "pending" and e["prompt"] == "the main menu" and e["source"] == "screenshot"
    deadline = time.time() + 3
    while time.time() < deadline:
        got = [x for x in c.get("/api/gallery", params={"session_id": a}, headers=H).json() if x["id"] == e["id"]]
        if got and got[0]["status"] != "pending":
            break
        time.sleep(0.02)
    assert got[0]["status"] == "failed" and "isn't a Unity project" in got[0]["reason"]
    assert got[0]["prompt"] == "the main menu"
    events = []
    while not sub.empty():
        ev = sub.get_nowait()
        if ev["type"] == "gallery.updated":
            events.append((ev["session_id"], ev["data"]["id"], ev["data"]["status"]))
    assert events == [(a, e["id"], "pending"), (a, e["id"], "failed")]
    assert c.post("/api/gallery/screenshot", json={"session_id": a, "prompt": " "}, headers=H).status_code == 400
    assert c.post("/api/gallery/screenshot", json={"session_id": "x", "prompt": "p"}, headers=H).status_code == 404


def test_indexing_media_publishes_event_but_not_for_other_kinds(env):
    c, s, tmp = env
    a = s.store.create()["id"]
    sub = s.bus.subscribe()
    iid = _media(s, tmp, a, "new.png")
    (tmp / "n.txt").write_text("x")
    s.items.add_file(tmp / "n.txt", source="agent", session_id=a, provider=None, model=None)
    evs = []
    while not sub.empty():
        evs.append(sub.get_nowait())
    gal = [e for e in evs if e["type"] == "gallery.updated"]
    assert len(gal) == 1 and gal[0]["session_id"] == a and gal[0]["data"] == {"session_id": a, "id": iid, "status": "done"}


def test_mark_done_indexes_the_image_and_merges_with_the_entry(env):
    from gamedevworkstation.features import gallery

    c, s, tmp = env
    sess = s.store.create(folder=str(tmp))
    eid = c.post("/api/gallery/screenshot", json={"session_id": sess["id"], "prompt": "boss room"}, headers=H).json()["id"]
    time.sleep(0.2)
    img = tmp / "shot.png"
    img.write_bytes(b"png")
    gallery.update_entry(s, sess["id"], eid, status="pending", reason=None)
    gallery.mark_done(s, sess, eid, img)
    got = c.get("/api/gallery", params={"session_id": sess["id"]}, headers=H).json()
    assert len(got) == 1 and got[0]["status"] == "done" and got[0]["prompt"] == "boss room" and got[0]["source"] == "screenshot"
    assert c.get(got[0]["url"], headers=H).content == b"png"


def test_startup_fails_pending_entries_and_preserves_finished_entries(tmp_path):
    from gamedevworkstation.features import gallery as G

    s = AppState(db_path=tmp_path / "restarted.db")
    sid = s.store.create()["id"]
    s.db.kv_set(f"gallery:{sid}", {
        "waiting": {"id": "waiting", "status": "pending", "created_at": "2026-01-01"},
        "done": {"id": "done", "status": "done", "created_at": "2026-01-01"},
        "failed": {"id": "failed", "status": "failed", "reason": "declined", "created_at": "2026-01-01"},
    })
    with TestClient(create_app("t", s)):
        assert G.get_entry(s, sid, "waiting")["reason"] == "interrupted (the app restarted)"
        assert G.get_entry(s, sid, "waiting")["status"] == "failed"
        assert G.get_entry(s, sid, "done")["status"] == "done"
        assert G.get_entry(s, sid, "failed")["reason"] == "declined"


def test_gallery_file_resolves_symlinks_and_limits_roots(env):
    from gamedevworkstation.config import data_dir

    c, s, tmp = env
    root = tmp / "project"
    root.mkdir()
    sess = s.store.create(folder=str(root))
    sid = sess["id"]
    other = tmp / "other"
    other.mkdir()
    s.store.create(folder=str(other))  # another session's folder is not permission for this session
    outside = _media(s, other, sid, "private.png")
    assert c.get(f"/api/gallery/file/{outside}", params={"session_id": sid}, headers=H).status_code == 404
    (root / "escape.png").symlink_to(other / "private.png")
    link = s.items.add_file(root / "escape.png", source="tool", session_id=sid, provider=None, model=None)
    assert c.get(f"/api/gallery/file/{link}", params={"session_id": sid}, headers=H).status_code == 404
    for directory in (root, data_dir(), s.worktrees_root(sid) / "sub"):
        directory.mkdir(parents=True, exist_ok=True)
        iid = _media(s, directory, sid, "allowed.png", data=b"ok")
        assert c.get(f"/api/gallery/file/{iid}", params={"session_id": sid}, headers=H).content == b"ok"
    # An indexed path can later become a symlink or disappear entirely.
    (directory / "allowed.png").unlink()
    (directory / "allowed.png").symlink_to(other / "private.png")
    assert c.get(f"/api/gallery/file/{iid}", params={"session_id": sid}, headers=H).status_code == 404
    (directory / "allowed.png").unlink()
    assert c.get(f"/api/gallery/file/{iid}", params={"session_id": sid}, headers=H).status_code == 404


def test_session_delete_removes_only_its_gallery_key(env):
    c, s, _ = env
    sid = s.store.create()["id"]
    other = s.store.create()["id"]
    s.db.kv_set(f"gallery:{sid}", {"pending": {"status": "pending"}})
    s.db.kv_set(f"gallery:{other}", {"keep": {"status": "done"}})
    s.store.delete(sid)
    assert s.db.kv_get(f"gallery:{sid}") is None
    assert s.db.kv_get(f"gallery:{other}") == {"keep": {"status": "done"}}
