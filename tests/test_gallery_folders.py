"""Folder discovery, imports, and file serving through the session Gallery."""
import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.features import gallery
from gamedevworkstation.server import create_app


@pytest.fixture
def env(tmp_path):
    state = AppState(db_path=tmp_path / "gallery.db")
    project = tmp_path / "Project"
    project.mkdir()
    sid = state.store.create(folder=str(project))["id"]
    with TestClient(create_app("t", state), headers={"Authorization": "Bearer t"}) as client:
        yield client, state, sid, project


def media(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"media")
    return path


def test_default_folders_scan_visible_media_and_one_level_of_unity_projects(env):
    client, _, sid, project = env
    shots = project / "Logs/harness/screenshots"
    shot = media(shots, "nested/shot.PNG")
    for name in ("readme.txt", ".hidden.png", ".git/hidden.png", ".private/hidden.png", "Library/cache.png",
                 "Temp/cache.png", "node_modules/cache.png", "a/b/c/d/e/f/g/too-deep.png"):
        media(shots, name)
    child = project / "Nested Game"
    (child / "ProjectSettings").mkdir(parents=True)
    (child / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.1f1\n", encoding="utf-8")
    video = media(child, "Recordings/game.mov")
    media(project, "Not Unity/Captures/unrelated.png")
    response = client.get("/api/gallery", params={"session_id": sid})
    assert response.status_code == 200
    by_path = {entry["path"]: entry for entry in response.json()}
    assert set(by_path) == {str(shot), str(video)}
    assert by_path[str(shot)] == {
        "id": (fid := "f_" + hashlib.sha1(os.fsencode(shot.resolve())).hexdigest()[:16]),
        "kind": "image", "path": str(shot), "url": f"/api/gallery/folder-file/{fid}?session_id={sid}",
        "title": "shot.PNG", "created_at": shot.stat().st_mtime, "source": "folder",
        "folder": str(shots), "status": "done",
    }
    assert by_path[str(video)]["kind"] == "video"
    assert client.get("/api/gallery/folders", params={"session_id": sid}).json() == {
        "default": [{"path": str(shots), "exists": True, "count": 1},
                    {"path": str(video.parent), "exists": True, "count": 1}],
        "imported": [],
    }


def test_import_remove_and_validate_folders(env):
    client, state, sid, project = env
    imported = project.parent / "More media"
    sound = media(imported, "music.flac")
    linked = project.parent / "link"
    linked.symlink_to(imported, target_is_directory=True)
    params = {"session_id": sid}

    def add(path):
        return client.post("/api/gallery/folders", json={**params, "path": str(path)})

    for invalid in (sound, imported / "missing", linked, "/", "~", "relative"):
        response = add(invalid)
        assert response.status_code == 400
        assert response.json()["detail"]
    events = state.bus.subscribe()
    assert add(imported).status_code == 200
    assert add(imported / ".").status_code == 200
    assert state.db.kv_get(f"gallery_folders:{sid}") == [str(imported)]
    event = events.get_nowait()
    assert event["type"] == "gallery.updated" and event["session_id"] == sid
    assert events.empty()
    assert client.get("/api/gallery/folders", params=params).json()["imported"] == [
        {"path": str(imported), "exists": True, "count": 1},
    ]
    entry = client.get("/api/gallery", params=params).json()[0]
    assert entry["kind"] == "audio"
    for index in range(19):
        directory = project.parent / f"import-{index}"
        directory.mkdir()
        assert add(directory).status_code == 200
    assert add(imported).status_code == 200
    assert add(project).status_code == 400
    sound.unlink()
    imported.rmdir()
    assert client.get("/api/gallery/folders", params=params).json()["imported"][0] == {
        "path": str(imported), "exists": False, "count": 0,
    }
    removal = {**params, "path": str(imported)}
    assert client.delete("/api/gallery/folders", params=removal).status_code == 200
    assert client.delete("/api/gallery/folders", params=removal).status_code == 404
    assert str(imported) not in state.db.kv_get(f"gallery_folders:{sid}")
    assert client.get("/api/gallery", params=params).json() == []


def test_folder_file_only_serves_current_regular_files_in_the_session(env):
    client, state, sid, project = env
    shots = project / "Screenshots"
    shot = media(shots, "nested/shot.png")
    gone = media(shots, "nested/gone.png")
    outside = media(project.parent, "private.png")
    (shots / "file-link.png").symlink_to(outside)
    (shots / "dir-link").symlink_to(outside.parent, target_is_directory=True)
    params = {"session_id": sid}
    entries = {e["title"]: e for e in client.get("/api/gallery", params=params).json()}
    assert set(entries) == {"shot.png", "gone.png"}
    response = client.get(entries["shot.png"]["url"])
    assert response.status_code == 200 and response.content == b"media"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/gallery/folder-file/f_unknown", params=params).status_code == 404
    other = state.store.create()["id"]
    assert client.get(f"/api/gallery/folder-file/{entries['shot.png']['id']}",
                      params={"session_id": other}).status_code == 404
    gone.unlink()
    assert client.get(entries["gone.png"]["url"]).status_code == 404
    shot.unlink()
    shot.symlink_to(outside)
    assert client.get(entries["shot.png"]["url"]).status_code == 404


def test_indexed_media_wins_and_filters_are_applied_before_the_limit(env):
    client, state, sid, project = env
    shots = project / "Screenshots"
    indexed = media(shots, "indexed.png")
    uploaded = media(project, "upload.jpg")
    video = media(shots, "clip.mp4")
    image = media(shots, "still.jpeg")
    tool = state.items.add_file(indexed, source="tool", session_id=sid, provider=None, model=None)
    user = state.items.add_file(uploaded, source="user", session_id=sid, provider=None, model=None)
    gallery._save(state, sid, {"pending": {"id": "pending", "prompt": "menu", "status": "pending",
                                          "created_at": video.stat().st_mtime + 1}})

    def entries(**filters):
        response = client.get("/api/gallery", params={"session_id": sid, **filters})
        assert response.status_code == 200
        return response.json()

    all_entries = entries()
    assert [e["created_at"] for e in all_entries] == sorted((e["created_at"] for e in all_entries), reverse=True)
    assert {e["title"] for e in all_entries} == {"indexed.png", "upload.jpg", "clip.mp4", "still.jpeg", "menu"}
    assert [(e["id"], e["source"]) for e in all_entries if e["path"] == str(indexed)] == [(tool, "tool")]
    assert [(e["id"], e["source"]) for e in entries(source="user", limit=1)] == [(user, "user")]
    assert client.get(entries(source="user")[0]["url"]).content == b"media"
    assert {e["id"] for e in entries(source="generated")} == {tool, "pending"}
    assert {Path(e["path"]) for e in entries(source="folders")} == {video, image}
    assert [e["path"] for e in entries(kinds="video", limit=1)] == [str(video)]
    assert [e["path"] for e in entries(source="folders", kinds="image")] == [str(image)]


def test_scan_keeps_newest_files_and_refreshes_nested_changes(env, monkeypatch):
    client, _, sid, project = env
    monkeypatch.setattr(gallery, "MAX_FOLDER_FILES", 2)
    captures = project / "Captures"
    for index in range(3):
        path = media(captures, f"nested/{index}.jpg")
        os.utime(path, (index + 1, index + 1))
    params = {"session_id": sid}
    assert [e["title"] for e in client.get("/api/gallery", params=params).json()] == ["2.jpg", "1.jpg"]
    new = media(captures, "nested/new.jpg")
    os.utime(new, (10, 10))
    assert [e["title"] for e in client.get("/api/gallery", params=params).json()] == ["2.jpg", "1.jpg"]
    assert [e["title"] for e in client.get("/api/gallery", params={**params, "refresh": True}).json()] == ["new.jpg", "2.jpg"]
