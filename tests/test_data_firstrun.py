"""Data lifecycle and first run: versioned DB migrations, event retention, full purge on delete,
snapshot size cap, storage maintenance, config overrides, the no-key message, OOXML text and
Copy to Downloads naming."""
import sqlite3
import time
import tomllib
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation import config as config_mod
from gamedevworkstation.app import AppState
from gamedevworkstation.config import data_dir, load_config, media_dir, save_config_patch, sessions_dir
from gamedevworkstation.core.types import ImageBlock, Message, TextBlock
from gamedevworkstation.db import DB, SCHEMA, SCHEMA_VERSION
from gamedevworkstation.items import extract_text
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


def wait_idle(c, sid, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not c.get(f"/api/sessions/{sid}", headers=H).json()["running"]:
            return
        time.sleep(0.02)
    raise TimeoutError


# ------------------------------------------------------------------ migrations


def test_new_database_is_versioned_with_incremental_vacuum(tmp_path):
    db = DB(tmp_path / "new.db")
    assert db.user_version() == SCHEMA_VERSION
    assert db.auto_vacuum_mode() == "incremental"
    cols = {r["name"] for r in db.all("PRAGMA table_info(snapshots)")}
    assert "too_large" in cols


def test_old_database_migrates_once_and_keeps_data(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.executescript(SCHEMA)  # the original tables, no added columns, user_version 0
    c.execute("INSERT INTO sessions (id, created_at, updated_at, model) VALUES ('ses_1', 1, 1, 'm')")
    c.execute("INSERT INTO messages (id, session_id, role, content, created_at) VALUES "
              "('msg_1', 'ses_1', 'user', '[{\"type\": \"text\", \"text\": \"hello there\"}]', 5)")
    c.execute("INSERT INTO snapshots (session_id, path, content, ts) VALUES ('ses_1', '/x', X'00', 1)")
    c.commit()
    c.close()
    db = DB(p)
    assert db.user_version() == SCHEMA_VERSION
    s = db.one("SELECT * FROM sessions WHERE id='ses_1'")
    assert s["activity_at"] == 5 and s["last_read_at"] == 5 and s["group_id"] is None
    assert db.one("SELECT too_large FROM snapshots")["too_large"] == 0
    assert db.one("SELECT 1 AS x FROM sqlite_master WHERE name='events_ts'")
    assert db.one("SELECT message_id FROM messages_fts WHERE messages_fts MATCH 'hello'")["message_id"] == "msg_1"
    db.execute("UPDATE sessions SET last_read_at=1")
    db.close()
    db = DB(p)  # v1 already applied: not run again (it would reset last_read_at only if the column were missing)
    assert db.one("SELECT last_read_at FROM sessions")["last_read_at"] == 1
    assert db.auto_vacuum_mode() == "none"  # an existing file only switches at a full VACUUM
    db.vacuum()
    assert db.auto_vacuum_mode() == "incremental"


# ---------------------------------------------------------------------- events


def test_status_updates_are_not_persisted_and_old_events_pruned(state):
    bus = state.bus
    bus.publish("session.updated", {"id": "first"}, "first")
    ev = bus.publish("status.updated", {"providers": []})
    assert ev["seq"] is None
    assert not state.db.one("SELECT 1 AS x FROM events WHERE type='status.updated'")
    a = bus.publish("session.updated", {"id": "a"}, "a")
    b = bus.publish("session.updated", {"id": "b"}, "b")
    state.db.execute("UPDATE events SET ts=? WHERE seq<=?", [time.time() - 8 * 86400, a["seq"]])
    assert bus.prune(7) == 2
    assert [e["seq"] for e in bus.replay(0)] == [b["seq"]]
    assert bus.replay_gap(a["seq"] - 1)  # a client that missed `a` must reload, not replay
    assert not bus.replay_gap(a["seq"])
    state.db.execute("DELETE FROM events")
    assert bus.last_seq() == b["seq"]  # seq keeps counting after everything is pruned
    assert bus.publish("x.y", {})["seq"] == b["seq"] + 1


def test_ws_tells_a_client_behind_the_retention_window_to_resync(client, state):
    state.bus.publish("session.updated", {"id": "seen"}, "seen")
    first = state.bus.publish("session.updated", {"id": "a"}, "a")
    state.bus.publish("session.updated", {"id": "b"}, "b")
    state.db.execute("DELETE FROM events WHERE seq<=?", [first["seq"]])  # pruned: the oldest go first
    with client.websocket_connect(f"/ws?token={TOKEN}&since={first['seq'] - 1}") as ws:
        assert ws.receive_json()["type"] == "ws.resync"
        assert ws.receive_json()["type"] == "ws.ready"


# ------------------------------------------------------------------------ purge


def test_purge_removes_everything_the_session_owns(client, state):
    keep = client.post("/api/sessions", json={"title": "keep"}, headers=H).json()
    gone = client.post("/api/sessions", json={"title": "gone"}, headers=H).json()
    sid = gone["id"]
    up = media_dir() / "uploads" / "u1"
    up.mkdir(parents=True)
    own, shared = up / "own.png", media_dir() / "shared.png"
    own.write_bytes(b"png")
    shared.write_bytes(b"png")
    user_file = Path(state.db.path).parent / "mine.txt"  # outside the media dir: never deleted
    user_file.write_text("x")
    for p in (own, shared, user_file):
        state.items.add_file(p, source="user", session_id=sid, provider="anthropic", model="m")
    state.store.add_message(sid, Message(role="user", content=[TextBlock(text="private words")]))
    # The other session's copied message still shows the shared image.
    state.store.add_message(keep["id"], Message(role="user", content=[ImageBlock(media_type="image/png", path=str(shared))]))
    state.changes.snapshot(sid, user_file)
    jid = state.jobs.start(sid, "subagent", "unit", meta={"subagent": "sub_abc"})
    tdir = data_dir() / "subagents"
    tdir.mkdir(exist_ok=True)
    (tdir / "sub_abc.json").write_text("{}")
    (sessions_dir() / sid).mkdir(parents=True)
    (sessions_dir() / sid / "scratch.txt").write_text("x")
    state.db.insert("approvals", {"id": "apr_1", "session_id": sid, "kind": "command", "payload": "{}",
                                  "created_at": time.time()})

    assert client.delete(f"/api/sessions/{sid}?purge=1", headers=H).json()["purged"]

    for table in ("snapshots", "jobs", "approvals", "items", "messages"):
        assert not state.db.one(f"SELECT 1 AS x FROM {table} WHERE session_id=?", [sid]), table
    assert not state.db.one("SELECT 1 AS x FROM messages_fts WHERE messages_fts MATCH 'private'")
    assert not own.exists() and not up.exists()
    assert shared.exists() and user_file.exists()
    assert not (tdir / "sub_abc.json").exists() and not (sessions_dir() / sid).exists()
    assert state.jobs.get(jid) is None
    # Only the deletion notice itself is left of it in the event log.
    assert [r["type"] for r in state.db.all("SELECT type FROM events WHERE session_id=?", [sid])] == ["session.deleted"]
    assert client.get(f"/api/sessions/{keep['id']}/messages", headers=H).status_code == 200


# -------------------------------------------------------------------- snapshots


def test_snapshot_size_cap(client, state, monkeypatch, tmp_path):
    from gamedevworkstation import services

    monkeypatch.setattr(services, "SNAPSHOT_MAX_BYTES", 10)
    folder = tmp_path / "proj"
    folder.mkdir()
    big, small = folder / "big.txt", folder / "small.txt"
    big.write_text("0123456789abcdef")
    small.write_text("tiny")
    s = client.post("/api/sessions", json={"folder": str(folder)}, headers=H).json()
    state.changes.snapshot(s["id"], big)
    state.changes.snapshot(s["id"], small)
    assert state.db.one("SELECT content, too_large FROM snapshots WHERE path=?", [str(big)]) == \
        {"content": None, "too_large": 1}
    big.write_text("changed")
    small.write_text("changed")
    files = {f["path"]: f for f in client.get(f"/api/sessions/{s['id']}/changes", headers=H).json()["files"]}
    assert files["big.txt"]["too_large"] and files["big.txt"]["note"] == "too large to snapshot"
    assert not files["small.txt"].get("too_large")
    d = client.get(f"/api/sessions/{s['id']}/changes/diff", params={"root": str(folder), "path": "big.txt"},
                   headers=H).json()
    assert d["original"] == "[too large to snapshot]"
    r = client.post(f"/api/sessions/{s['id']}/changes/revert", json={"root": str(folder), "path": "big.txt"}, headers=H)
    assert r.status_code == 409 and big.read_text() == "changed"
    assert client.post(f"/api/sessions/{s['id']}/changes/revert", json={"root": str(folder), "path": "small.txt"},
                       headers=H).status_code == 200
    assert small.read_text() == "tiny"


# ---------------------------------------------------------------------- storage


def test_storage_usage_and_compact(client, state):
    state.bus.publish("session.updated", {"blob": "x" * 50_000}, "s")
    state.db.execute("UPDATE events SET ts=0")
    (media_dir() / "a.bin").write_bytes(b"x" * 1000)
    u = client.get("/api/storage", headers=H).json()
    assert u["database"]["bytes"] > 0 and u["database"]["schema_version"] == SCHEMA_VERSION
    assert u["media"]["bytes"] >= 1000 and u["events"]["retention_days"] == 7
    assert {"snapshots", "logs", "transcripts", "last_maintenance"} <= set(u)
    r = client.post("/api/storage/compact", headers=H).json()
    assert r["pruned_events"] >= 1 and r["usage"]["events"]["count"] == 0
    assert r["usage"]["database"]["auto_vacuum"] == "incremental"
    assert r["usage"]["last_maintenance"]


def test_daily_maintenance_runs_at_startup(state):
    state.bus.publish("session.updated", {}, "s")
    state.db.execute("UPDATE events SET ts=0")
    with TestClient(create_app(TOKEN, state)):
        t0 = time.time()
        while state.db.kv_get("storage.maintenance_at") is None and time.time() - t0 < 5:
            time.sleep(0.02)
    assert state.db.kv_get("storage.maintenance_at")
    assert not state.db.one("SELECT 1 AS x FROM events WHERE ts=0")


# ----------------------------------------------------------------------- config


def _user(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def test_first_run_writes_only_overrides(tmp_path):
    p = tmp_path / "config.toml"
    cfg = load_config(p)
    assert _user(p) == {"config_version": config_mod.CONFIG_FORMAT}
    assert cfg.tiers["claude.fast"] == "claude-haiku-5-5"  # from the packaged defaults


def test_old_full_copy_is_slimmed_to_changes(tmp_path):
    p = tmp_path / "config.toml"
    full = config_mod.DEFAULT_CONFIG_PATH.read_text().replace("trash_days = 30", "trash_days = 9")
    p.write_text(full)
    cfg = load_config(p)
    assert cfg.sessions["trash_days"] == 9
    assert _user(p) == {"config_version": config_mod.CONFIG_FORMAT, "sessions": {"trash_days": 9}}
    assert (tmp_path / "config.toml.bak").read_text() == full  # the original stays as a backup
    # A later change of a default now reaches this user.
    newer = tmp_path / "defaults.toml"
    newer.write_text(config_mod.DEFAULT_CONFIG_PATH.read_text().replace('"claude.fast" = "claude-haiku-5-5"',
                                                                         '"claude.fast" = "claude-haiku-6"'))
    assert newer.read_text() != config_mod.DEFAULT_CONFIG_PATH.read_text()
    config_mod.DEFAULT_CONFIG_PATH, old = newer, config_mod.DEFAULT_CONFIG_PATH
    try:
        assert load_config(p).tiers["claude.fast"] == "claude-haiku-6"
    finally:
        config_mod.DEFAULT_CONFIG_PATH = old


def test_save_keeps_only_differences_atomically_with_backup():
    p = config_mod.config_path()
    defaults = tomllib.loads(config_mod.DEFAULT_CONFIG_PATH.read_text())
    # The Settings page saves whole sections: values equal to the defaults aren't pinned.
    cfg = save_config_patch({"limits": {**defaults["limits"], "global_daily_usd": 123}, "orchestrator": defaults["orchestrator"]})
    assert cfg.limits["global_daily_usd"] == 123
    user = _user(p)
    assert user["limits"] == {"global_daily_usd": 123} and "orchestrator" not in user
    before = p.read_text()
    save_config_patch({"limits": {"global_daily_usd": 5}})
    assert (p.parent / "config.toml.bak").read_text() == before
    assert not list(p.parent.glob(".config.toml.*.tmp"))
    # Setting a value back to its default removes the override.
    save_config_patch({"limits": {"global_daily_usd": defaults["limits"]["global_daily_usd"]}})
    assert "limits" not in _user(p)


@pytest.mark.parametrize("bad", ["this is = = not toml", '[models."x"]\nprovider = "openai"\ninput = "lots"\n'])
def test_broken_config_starts_with_defaults_and_is_kept(client, monkeypatch, bad):
    monkeypatch.setattr(config_mod, "_load_error", None)
    p = config_mod.config_path()
    p.write_text(bad)
    cfg = load_config()
    assert cfg.tiers["claude.fast"] == "claude-haiku-5-5"
    broken = list(p.parent.glob("config.toml.broken-*"))
    assert len(broken) == 1 and broken[0].read_text() == bad
    assert _user(p) == {"config_version": config_mod.CONFIG_FORMAT}
    err = client.get("/api/state", headers=H).json()["config_error"]
    assert err["broken_path"] == str(broken[0]) and "default settings" in err["message"] and err["error"]


# ------------------------------------------------------------------- first run


def test_setup_checklist_status(client, monkeypatch, tmp_path):
    st = client.get("/api/setup", headers=H).json()
    assert st == {"keys": {"anthropic": False, "openai": False, "elevenlabs": False}, "folder": False, "skill": False}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123456")
    client.post("/api/sessions", json={"folder": str(tmp_path)}, headers=H)
    st = client.get("/api/setup", headers=H).json()
    assert st["keys"]["anthropic"] and st["folder"] and not st["skill"]


def test_message_without_a_key_is_a_friendly_note(client):
    s = client.post("/api/sessions", json={}, headers=H).json()
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "hi"}, headers=H)
    wait_idle(client, s["id"])
    last = client.get(f"/api/sessions/{s['id']}/messages", headers=H).json()[-1]
    assert last["meta"]["error"] is True and last["meta"]["error_kind"] == "no_key"
    assert last["meta"]["provider"] == "anthropic"
    text = last["content"][0]["text"]
    assert "Settings → Accounts" in text and "ProviderError" not in text


# ---------------------------------------------------------------------- items


def _zip(path: Path, parts: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, body in parts.items():
            z.writestr(name, body)
    return path


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'


def test_ooxml_text_extraction(tmp_path):
    docx = _zip(tmp_path / "a.docx", {"word/document.xml":
        f'<w:document {W}><w:body><w:p><w:r><w:t>Quarterly</w:t></w:r><w:r><w:t xml:space="preserve"> report</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Second</w:t><w:tab/><w:t>para</w:t></w:r></w:p></w:body></w:document>'})
    assert extract_text(docx) == "Quarterly report\nSecond\tpara"
    slide = lambda t: f'<p:sld xmlns:p="x" {A}><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:sld>'  # noqa: E731
    pptx = _zip(tmp_path / "b.pptx", {"ppt/slides/slide10.xml": slide("Ten"), "ppt/slides/slide2.xml": slide("Two")})
    assert extract_text(pptx) == "Slide 2\nTwo\n\nSlide 10\nTen"
    xlsx = _zip(tmp_path / "c.xlsx", {
        "xl/sharedStrings.xml": f'<sst {S}><si><t>Name</t></si><si><r><t>Ada</t></r><r><t> L</t></r></si></sst>',
        "xl/worksheets/sheet1.xml": f'<worksheet {S}><sheetData><row><c t="s"><v>0</v></c><c><v>42</v></c></row>'
                                    '<row><c t="s"><v>1</v></c><c t="inlineStr"><is><t>x</t></is></c></row>'
                                    '</sheetData></worksheet>'})
    assert extract_text(xlsx) == "Sheet 1\nName\t42\nAda L\tx"
    assert extract_text(docx, limit=5) == "Quart"
    assert extract_text(_zip(tmp_path / "empty.docx", {"other.xml": "<x/>"})) is None
    (tmp_path / "broken.xlsx").write_bytes(b"not a zip")
    assert extract_text(tmp_path / "broken.xlsx") is None


def test_ooxml_skips_oversized_parts(tmp_path, monkeypatch):
    from gamedevworkstation import items

    monkeypatch.setattr(items, "OOXML_MAX_PART", 50)
    docx = _zip(tmp_path / "big.docx", {"word/document.xml": f'<w:document {W}><w:body><w:p><w:r><w:t>{"x" * 100}'
                                                             '</w:t></w:r></w:p></w:body></w:document>'})
    assert extract_text(docx) is None


def test_copy_to_downloads_never_overwrites(client, state, monkeypatch, tmp_path):
    home = tmp_path / "fakehome"
    monkeypatch.setenv("HOME", str(home))
    src = media_dir() / "report.pdf"
    src.write_bytes(b"new")
    iid = state.items.add_file(src, source="user", session_id=None, provider=None, model=None)
    (home / "Downloads").mkdir(parents=True)
    (home / "Downloads" / "report.pdf").write_bytes(b"old")
    paths = [client.post(f"/api/items/{iid}/copy-to-downloads", headers=H).json()["path"] for _ in range(2)]
    assert [Path(p).name for p in paths] == ["report (2).pdf", "report (3).pdf"]
    assert (home / "Downloads" / "report.pdf").read_bytes() == b"old"
    assert Path(paths[0]).read_bytes() == b"new"
