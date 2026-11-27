"""The agent's `prefabs` and `gallery` tools: the session sees what its Prefabs and Gallery tabs show."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.features import prefab_edit
from gamedevworkstation.features.hooks import build_context_pack
from gamedevworkstation.server import create_app

from .test_prefabs import BRUTE, BRUTE_GUID, GRUNT, GRUNT_GUID, PREFAB, SCRIPT_GUID, VARIANT, asset, change


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "Game"
    (root / "ProjectSettings").mkdir(parents=True)
    (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.1f1\n", encoding="utf-8")
    asset(root, GRUNT, PREFAB, GRUNT_GUID)
    asset(root, BRUTE, VARIANT, BRUTE_GUID)
    asset(root, "Assets/Game/Enemies/Health.cs",
          "namespace Game.Enemies { class Health { public bool aggressive; } }", SCRIPT_GUID)
    app = AppState(db_path=tmp_path / "x.db")
    create_app("t", app)  # registers the feature tools
    session = app.store.create(folder=str(root), mode="ask")
    app.approvals.ask = AsyncMock(return_value={"status": "approved"})
    return app, root, session


def run(app, session, name, args):
    ctx = ToolContext(app=app, session=app.store.get(session["id"]), run_id="main:x")
    return asyncio.run(app.tools.run(ctx, name, args))


def test_list_detail_and_history(env):
    app, root, session = env
    out = run(app, session, "prefabs", {"op": "list"}).text
    assert "2 of 2 prefabs" in out and GRUNT in out and "variant of Grunt" in out
    assert BRUTE not in run(app, session, "prefabs", {"op": "list", "query": "grunt"}).text
    detail = run(app, session, "prefabs", {"op": "detail", "path": BRUTE}).text
    assert "Health (file_id 114" in detail and "_maxHealth = 80 [number; override]" in detail
    assert "aggressive = 0 [bool; inherited]" in detail
    # A user's edit in the tab shows up as by tab.
    prefab_edit.edit_many(prefab_edit.Project(root), [change("_maxHealth", "70")], "Grunt · Max Health 60 → 70")
    hist = run(app, session, "prefabs", {"op": "history"}).text
    assert "by tab: Grunt · Max Health 60 → 70" in hist


def test_edit_asks_writes_and_is_undoable_in_the_tab(env):
    app, root, session = env
    out = run(app, session, "prefabs", {"op": "edit", "summary": "Tougher grunt",
                                         "edits": [{"path": GRUNT, "file_id": "114", "key": "_maxHealth", "value": "90"}]})
    assert not out.is_error and "step #1" in out.text
    card = app.approvals.ask.call_args
    assert card.args[1] == "edit" and card.args[2]["action"] == "prefab edit"
    assert "_maxHealth: 90" in (root / GRUNT).read_text(encoding="utf-8")
    assert "by agent" in run(app, session, "prefabs", {"op": "history"}).text
    prefab_edit.move(prefab_edit.Project(root), redo=False, force=False)
    assert "_maxHealth: 60" in (root / GRUNT).read_text(encoding="utf-8")


def test_edit_errors_and_plan_mode(env):
    app, root, session = env
    bad = run(app, session, "prefabs", {"op": "edit", "edits": [{"path": GRUNT, "file_id": "114", "key": "nope", "value": "1"}]})
    assert bad.is_error and "Unknown prefab field" in bad.text
    app.store.update(session["id"], mode="plan")
    refused = run(app, session, "prefabs", {"op": "edit", "edits": [{"path": GRUNT, "file_id": "114", "key": "_maxHealth", "value": "1"}]})
    assert refused.is_error and "Plan only" in refused.text
    assert "_maxHealth: 60" in (root / GRUNT).read_text(encoding="utf-8")


def test_prefabs_tool_only_in_unity_sessions(env, tmp_path):
    app, root, session = env
    names = {s.name for s in app.tools.specs(session=app.store.get(session["id"]))}
    assert {"prefabs", "gallery"} <= names
    plain = app.store.create(folder=str(tmp_path))
    app.store.update(plain["id"], settings={"unity_project": False})
    names = {s.name for s in app.tools.specs(session=app.store.get(plain["id"]))}
    assert "gallery" in names and "prefabs" not in names


def test_gallery_tool_lists_entries(env, tmp_path):
    app, root, session = env
    assert run(app, session, "gallery", {}).text == "The Gallery is empty."
    png = root / "Logs/harness/shot.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    app.items.add(session_id=session["id"], kind="media", source="tool", path=str(png), mime="image/png",
                  title="shot.png")
    out = run(app, session, "gallery", {"kinds": "image"}).text
    assert "1 entries" in out and "image from tool" in out and str(png) in out


def test_context_pack_names_the_tabs(env):
    app, root, session = env
    pack = build_context_pack(app, app.store.get(session["id"]))
    assert "Prefabs tab" in pack["text"] and "`gallery`" in pack["text"]
