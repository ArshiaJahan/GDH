"""The Prefabs tab reads and edits scratch Unity projects through its session API."""
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from gamedevworkstation.app import AppState
from gamedevworkstation.features import prefab_yaml
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}
GRUNT = "Assets/Game/Enemies/Grunt.prefab"
BRUTE = "Assets/Game/Enemies/Brute.prefab"
ARCHER = "Assets/Game/Enemies/Archer.prefab"
BULLET = "Assets/Game/Projectiles/Bullet.prefab"
GRUNT_GUID = "a" * 32
BRUTE_GUID = "b" * 32
SCRIPT_GUID = "c" * 32

PREFAB = """\
%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &3
GameObject:
  m_Component:
  - component: {fileID: 43}
  m_Name: Archer
--- !u!4 &43
Transform:
  m_GameObject: {fileID: 3}
  m_Children: []
  m_Father: {fileID: 41}
--- !u!1 &1
GameObject:
  m_Component:
  - component: {fileID: 41}
  - component: {fileID: 114}
  - component: {fileID: 50}
  - component: {fileID: 212}
  m_Name: Grunt
--- !u!4 &41
Transform:
  m_GameObject: {fileID: 1}
  m_LocalPosition: {x: 0, y: 1.5, z: 0} # position
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_Children:
  - {fileID: 42}
  - {fileID: 43}
  m_Father: {fileID: 0}
--- !u!114 &114
MonoBehaviour:
  m_GameObject: {fileID: 1}
  m_Enabled: 0
  m_Name:
  m_Script: {fileID: 11500000, guid: SCRIPT_GUID, type: 3}
  m_EditorClassIdentifier: Assembly-CSharp::Game.Enemies.Health
  _maxHealth: 60 # points
  aggressive: 0
  title: 'Grunt'
  subtitle: Grunt
  empty:
  target: {fileID: 3}
  drops:
  - {fileID: 0}
  notes: |-
    Grunt
  nested:
    maxHealth: 5
  m_EditorHideFlags: 0
--- !u!50 &50
Rigidbody2D:
  m_GameObject: {fileID: 1}
  m_Mass: 6.0
  m_LinearDamping: 0.1
  m_GravityScale: 1
  m_BodyType: 0
--- !u!212 &212
SpriteRenderer:
  m_GameObject: {fileID: 1}
  m_Color: {r: 1, g: 0.5, b: 0, a: 1}
  m_FlipX: 0
--- !u!1 &2
GameObject:
  m_Component:
  - component: {fileID: 42}
  m_Name: Bullet
--- !u!4 &42
Transform:
  m_GameObject: {fileID: 2}
  m_Children: []
  m_Father: {fileID: 41}
""".replace("SCRIPT_GUID", SCRIPT_GUID)

VARIANT = """\
%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1001 &55
PrefabInstance:
  m_Modification:
    m_TransformParent: {fileID: 0}
    m_Modifications:
    - target: {fileID: 114, guid: GRUNT_GUID, type: 3}
      propertyPath: _maxHealth
      value: 80
      objectReference: {fileID: 0}
    - target: {fileID: 1, guid: GRUNT_GUID, type: 3}
      propertyPath: m_Name
      value: Brute
      objectReference: {fileID: 0}
    m_RemovedComponents: []
  m_SourcePrefab: {fileID: 100100000, guid: GRUNT_GUID, type: 3}
--- !u!4 &405 stripped
Transform:
  m_CorrespondingSourceObject: {fileID: 41, guid: GRUNT_GUID, type: 3}
  m_PrefabInstance: {fileID: 55}
""".replace("GRUNT_GUID", GRUNT_GUID)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        file.write(text)
    return path


def asset(root: Path, path: str, text: str, guid: str) -> Path:
    write(root / (path + ".meta"), f"fileFormatVersion: 2\nguid: {guid}\n")
    return write(root / path, text)


def fields(detail, id="114"):
    return {
        field["key"]: field
        for obj in detail["objects"]
        for comp in obj["components"]
        if comp["file_id"] == id
        for field in comp["fields"]
    }


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "workspace" / "Game"
    write(root / "ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.0.1f1\n")
    asset(root, GRUNT, PREFAB, GRUNT_GUID)
    asset(root, "Assets/Game/Enemies/Health.cs",
          "namespace Game.Enemies { class Health { public bool aggressive; } }", SCRIPT_GUID)
    state = AppState(db_path=tmp_path / "x.db")
    session = state.store.create(folder=str(tmp_path / "workspace"))
    with TestClient(create_app("t", state), headers=H) as client:
        yield client, root, f"/api/sessions/{session['id']}/prefabs", state


def edit(client, url, key, value, *, path=GRUNT, file_id="114", part=None):
    return client.post(url + "/edit", json=change(key, value, path=path, file_id=file_id, part=part))


def change(key, value, *, path=GRUNT, file_id="114", part=None):
    return {"path": path, "file_id": file_id, "key": key, "part": part, "value": value}


def test_scan_and_grouping(env):
    client, root, url, _ = env
    asset(root, BRUTE, VARIANT, BRUTE_GUID)
    asset(root, BULLET, PREFAB, "d" * 32)
    for folder in ("Library", "Packages", "Temp", ".gdw", ".hidden"):
        write(root / folder / "Archer.prefab", PREFAB)
        write(root / "Assets" / folder / "Archer.prefab", PREFAB)
    result = client.get(url).json()
    assert result["root"] == str(root.resolve())
    assert isinstance(result["scanned_at"], float)
    assert result["group_by"] == "category"
    assert result["groups"] == [{"name": "Enemies", "count": 2}, {"name": "Projectiles", "count": 1}]
    prefabs = {p["path"]: p for p in result["prefabs"]}
    assert set(prefabs) == {GRUNT, BRUTE, BULLET}
    assert prefabs[GRUNT] == {
        "path": GRUNT, "name": "Grunt", "guid": GRUNT_GUID, "group": "Enemies",
        "folder": "Assets/Game/Enemies", "components": ["Transform", "Health", "Rigidbody2D", "SpriteRenderer"],
        "variant_of": None, "edited": 0, "preview": False,
    }
    assert prefabs[BRUTE]["variant_of"] == {"path": GRUNT, "guid": GRUNT_GUID, "name": "Grunt"}
    config = {"categories": {"Enemies": ["Assets/**/Enemies/**"], "Brute": [BRUTE]}}
    write(root / ".gdw/prefab-categories.json", json.dumps(config))
    result = client.get(url).json()
    assert {p["path"]: p["group"] for p in result["prefabs"]} == {
        GRUNT: "Enemies", BRUTE: "Enemies", BULLET: "Uncategorized",
    }
    assert client.get(url, params={"group_by": "folder"}).json()["groups"] == [
        {"name": "Game/Enemies", "count": 2}, {"name": "Game/Projectiles", "count": 1},
    ]
    assert client.get(url, params={"group_by": "component"}).json()["groups"] == [{"name": "Health", "count": 3}]


def test_scan_only_reparses_changed_files(env, monkeypatch):
    client, root, url, _ = env
    asset(root, BULLET, PREFAB, "d" * 32)
    seen = []
    real_parse = prefab_yaml.parse

    def traced(text):
        seen.append(text)
        return real_parse(text)

    monkeypatch.setattr(prefab_yaml, "parse", traced)
    assert client.get(url).status_code == 200
    assert len(seen) == 2
    seen.clear()
    assert client.get(url).status_code == 200
    assert seen == []
    write(root / BULLET, PREFAB.replace("m_Name: Grunt", "m_Name: Brute") + "\n")
    assert client.get(url).status_code == 200
    assert len(seen) == 1 and "m_Name: Brute" in seen[0]


def test_detail_fields_and_hierarchy(env):
    client, _, url, _ = env
    result = client.get(url + "/detail", params={"path": GRUNT}).json()
    assert result["guid"] == GRUNT_GUID and result["variant_of"] is None and result["overrides"] == []
    assert [(obj["name"], obj["parent_file_id"]) for obj in result["objects"]] == [
        ("Grunt", None), ("Bullet", "1"), ("Archer", "1"),
    ]
    health = result["objects"][0]["components"][1]
    assert {key: value for key, value in health.items() if key != "fields"} == {
        "file_id": "114", "type": "Health", "namespace": "Game.Enemies", "builtin": False,
        "script_path": "Assets/Game/Enemies/Health.cs", "enabled": False,
    }
    own = fields(result)
    assert own["_maxHealth"] == {
        "key": "_maxHealth", "value": "60", "label": "Max Health", "kind": "number", "editable": True, "edited": None,
    }
    assert own["aggressive"]["kind"] == "bool"
    assert own["title"]["kind"] == "string" and own["title"]["value"] == "Grunt"
    for key, kind in [("target", "reference"), ("drops", "list"), ("notes", "other"), ("nested", "other")]:
        assert own[key]["kind"] == kind and own[key]["editable"] is False
    assert "m_EditorHideFlags" not in own
    pos = fields(result, "41")["m_LocalPosition"]
    assert pos["label"] == "Local Position" and pos["kind"] == "vector" and pos["editable"]
    assert pos["parts"] == {"x": "0", "y": "1.5", "z": "0"}
    color = fields(result, "212")["m_Color"]
    assert color["kind"] == "color" and color["parts"] == {"r": "1", "g": "0.5", "b": "0", "a": "1"}
    assert set(fields(result, "50")) == {"m_Mass", "m_LinearDamping", "m_GravityScale"}


@pytest.mark.parametrize("eol,trailing", [("\r\n", True), ("\n", False)])
def test_scalar_edits_keep_other_bytes(env, eol, trailing):
    client, root, url, _ = env
    original = (PREFAB if trailing else PREFAB.rstrip("\n")).replace("\n", eol)
    prefab = write(root / GRUNT, original)
    expected = original
    for index, (key, value, before, after, fid, part) in enumerate([
        ("_maxHealth", "95.5", "_maxHealth: 60", "_maxHealth: 95.5", "114", None),
        ("aggressive", "true", "aggressive: 0", "aggressive: 1", "114", None),
        ("title", "Brute's # title", "title: 'Grunt'", "title: 'Brute''s # title'", "114", None),
        ("m_LocalPosition", "-2.25", "y: 1.5", "y: -2.25", "41", "y"),
        ("subtitle", "Archer: Grunt", "subtitle: Grunt", "subtitle: 'Archer: Grunt'", "114", None),
        ("empty", "Archer", "empty:", "empty: Archer", "114", None),
    ], start=1):
        response = edit(client, url, key, value, file_id=fid, part=part)
        assert response.status_code == 200, response.text
        assert response.json()["step"] == index
        expected = expected.replace(before, after, 1)
        assert prefab.read_bytes() == expected.encode("utf-8")
    assert fields(response.json()["detail"])["title"]["edited"] == {"was": "Grunt", "step": 3}
    for _ in range(6):
        assert client.post(url + "/undo", json={}).status_code == 200
    assert prefab.read_bytes() == original.encode("utf-8")
    for _ in range(6):
        assert client.post(url + "/redo", json={}).status_code == 200
    assert prefab.read_bytes() == expected.encode("utf-8")


def test_invalid_edits_and_paths(env):
    client, root, url, _ = env
    outside = write(root / "Outside.prefab", PREFAB)
    (root / "Assets/Archer.prefab").symlink_to(outside)
    for key, value, fid, part in [
        ("_maxHealth", "no", "114", None), ("aggressive", "5", "114", None),
        ("title", "Brute\nArcher", "114", None), ("target", "3", "114", None),
        ("m_LocalPosition", "1", "41", "r"), ("m_LocalPosition", "1", "41", None),
    ]:
        assert edit(client, url, key, value, file_id=fid, part=part).status_code == 400
    for path in ("Assets/../Outside.prefab", "Outside.prefab", str(outside), "Assets\\Archer.prefab"):
        assert edit(client, url, "_maxHealth", "70", path=path).status_code == 400
    for path in ("Assets/Unknown.prefab", "Assets/Archer.prefab"):
        assert edit(client, url, "_maxHealth", "70", path=path).status_code == 404
    assert edit(client, url, "missing", "70").status_code == 404
    assert edit(client, url, "_maxHealth", "70", file_id="999").status_code == 404
    assert outside.read_bytes() == (root / GRUNT).read_bytes() == PREFAB.encode("utf-8")
    assert client.get(url + "/history").json() == {"position": 0, "steps": []}


def test_variant_overrides_and_undo(env):
    client, root, url, _ = env
    prefab = asset(root, BRUTE, VARIANT, BRUTE_GUID)
    original_base = (root / GRUNT).read_bytes()
    result = client.get(url + "/detail", params={"path": BRUTE}).json()
    assert result["objects"][0]["name"] == "Brute"
    assert fields(result)["_maxHealth"]["override"] and fields(result)["_maxHealth"]["value"] == "80"
    assert fields(result)["aggressive"]["inherited"] and fields(result)["aggressive"]["value"] == "0"
    assert result["overrides"][0] == {
        "target_file_id": "114", "target_guid": GRUNT_GUID, "property_path": "_maxHealth",
        "value": "80", "object_reference": None,
    }
    response = edit(client, url, "aggressive", "true", path=BRUTE)
    assert response.status_code == 200, response.text
    assert fields(response.json()["detail"])["aggressive"]["override"]
    added = (
        f"    - target: {{fileID: 114, guid: {GRUNT_GUID}, type: 3}}\n"
        "      propertyPath: aggressive\n      value: 1\n      objectReference: {fileID: 0}\n"
    )
    appended = VARIANT.replace("    m_RemovedComponents:", added + "    m_RemovedComponents:")
    assert prefab.read_bytes() == appended.encode("utf-8")
    response = edit(client, url, "_maxHealth", "100", path=BRUTE)
    assert response.status_code == 200, response.text
    edited = appended.replace("      value: 80", "      value: 100")
    assert prefab.read_bytes() == edited.encode("utf-8")
    assert client.post(url + "/undo", json={}).json()["paths"] == [BRUTE]
    assert prefab.read_bytes() == appended.encode("utf-8")
    assert client.post(url + "/undo", json={}).json()["position"] == 0
    assert prefab.read_bytes() == VARIANT.encode("utf-8")
    for position in (1, 2):
        assert client.post(url + "/redo", json={}).json()["position"] == position
    assert prefab.read_bytes() == edited.encode("utf-8")
    assert (root / GRUNT).read_bytes() == original_base


@pytest.mark.parametrize("marker", ["", " []", " [] # mods"])
def test_variant_empty_modification_list_round_trip(env, marker):
    client, root, url, _ = env
    variant = VARIANT[:VARIANT.index("    m_Modifications:")] + "    m_Modifications:" + marker + "\n" + (
        VARIANT[VARIANT.index("    m_RemovedComponents:"):]
    )
    variant = variant.rstrip("\n").replace("\n", "\r\n")
    prefab = asset(root, BRUTE, variant, BRUTE_GUID)
    response = edit(client, url, "m_LocalPosition", "4", file_id="41", part="y", path=BRUTE)
    assert response.status_code == 200, response.text
    field = fields(response.json()["detail"], "41")["m_LocalPosition"]
    assert field["override"] is True and field["parts"]["y"] == "4"
    assert field["value"] == "{x: 0, y: 4, z: 0}"
    updated = prefab.read_bytes()
    assert client.post(url + "/undo", json={}).status_code == 200
    assert prefab.read_bytes() == variant.encode("utf-8")
    assert client.post(url + "/redo", json={}).status_code == 200
    assert prefab.read_bytes() == updated


def test_categories_get_returns_saved_mapping(env):
    client, _root, url, _state = env
    assert client.get(url + "/categories").json() == {"categories": {}}
    client.put(url + "/categories", json={"categories": {"Enemies": ["Assets/**/Grunt.prefab"]}})
    assert client.get(url + "/categories").json() == {"categories": {"Enemies": ["Assets/**/Grunt.prefab"]}}


def test_undo_redo_conflict_and_force(env):
    client, root, url, _ = env
    assert edit(client, url, "_maxHealth", "70").status_code == 200
    file = write(root / GRUNT, PREFAB.replace("_maxHealth: 60", "_maxHealth: 90")
                 .replace("title: 'Grunt'", "title: 'Brute'"))
    conflict = client.post(url + "/undo", json={"force": False})
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": {"conflict": [{"path": GRUNT, "key": "_maxHealth", "expected": "70", "actual": "90"}]}}
    assert b"_maxHealth: 90" in file.read_bytes()
    assert client.post(url + "/undo", json={"force": True}).json() == {"ok": True, "position": 0, "paths": [GRUNT]}
    assert file.read_bytes() == PREFAB.replace("title: 'Grunt'", "title: 'Brute'").encode("utf-8")
    write(file, file.read_bytes().decode("utf-8").replace("_maxHealth: 60", "_maxHealth: 50"))
    conflict = client.post(url + "/redo", json={})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["conflict"][0]["expected"] == "60"
    assert client.post(url + "/redo", json={"force": True}).json()["position"] == 1
    assert b"_maxHealth: 70" in file.read_bytes()


def test_history_order_and_replacing_redo_tail(env):
    client, root, url, _ = env
    assert edit(client, url, "_maxHealth", "70").json()["step"] == 1
    assert edit(client, url, "_maxHealth", "80").json()["step"] == 2
    assert client.post(url + "/undo", json={}).json()["position"] == 1
    history = client.get(url + "/history").json()
    assert history["position"] == 1
    assert [(s["id"], s["undone"]) for s in history["steps"]] == [(2, True), (1, False)]
    assert history["steps"][0]["edits"][0]["before"] == "70"
    assert client.get(url).json()["prefabs"][0]["edited"] == 1
    response = edit(client, url, "_maxHealth", "75").json()
    replacement = response["step"]
    assert fields(response["detail"])["_maxHealth"]["edited"] == {"was": "70", "step": replacement}
    assert client.post(url + "/redo", json={}).json() == {"ok": True, "position": 2, "paths": []}
    history = client.get(url + "/history").json()
    assert [(s["id"], s["undone"]) for s in history["steps"]] == [(replacement, False), (1, False)]
    assert client.get(url).json()["prefabs"][0]["edited"] == 2
    assert (root / ".gdw/.gitignore").read_text(encoding="utf-8") == "prefab-history.json\n"


def test_history_retains_only_500_steps(env):
    client, root, url, _ = env
    journal = root / ".gdw/prefab-history.json"
    steps = [{"id": index, "at": 0.0, "summary": "Edit Grunt", "edits": []}
             for index in range(1, 501)]
    write(journal, json.dumps({"steps": steps, "position": 500}))
    assert edit(client, url, "_maxHealth", "70").json()["step"] == 501
    history = client.get(url + "/history").json()
    assert len(history["steps"]) == history["position"] == 500
    assert history["steps"][0]["id"] == 501 and history["steps"][-1]["id"] == 2


def test_batch_is_one_step_and_invalid_batch_writes_nothing(env):
    client, root, url, _ = env
    bullet = asset(root, BULLET, PREFAB, "d" * 32)
    edits = [change("_maxHealth", "70"), change("_maxHealth", "80"),
             change("aggressive", "1", path=BULLET)]
    bad = client.post(url + "/edit_many", json={"edits": edits + [change("missing", "99")]})
    assert bad.status_code == 404
    assert (root / GRUNT).read_bytes() == PREFAB.encode("utf-8")
    assert bullet.read_bytes() == PREFAB.encode("utf-8")
    assert not (root / ".gdw/prefab-history.json").exists()
    response = client.post(url + "/edit_many", json={"edits": edits, "summary": "Move Speed × 0.9"})
    assert response.json() == {"ok": True, "step": 1}
    history = client.get(url + "/history").json()
    assert len(history["steps"]) == history["position"] == 1
    assert history["steps"][0]["summary"] == "Move Speed × 0.9"
    assert len(history["steps"][0]["edits"]) == 3
    assert {p["edited"] for p in client.get(url).json()["prefabs"]} == {1}
    assert client.post(url + "/undo", json={}).json()["paths"] == [GRUNT, BULLET]
    assert (root / GRUNT).read_bytes() == bullet.read_bytes() == PREFAB.encode("utf-8")
    assert client.post(url + "/redo", json={}).json()["position"] == 1
    assert b"_maxHealth: 80" in (root / GRUNT).read_bytes()
    assert b"aggressive: 1" in bullet.read_bytes()


def test_categories_and_preview(env):
    client, root, url, _ = env
    data = {"categories": {"Brute": [], "Grunt": [GRUNT]}}
    result = client.put(url + "/categories", json=data)
    assert result.status_code == 200 and result.json() == data
    assert json.loads((root / ".gdw/prefab-categories.json").read_text(encoding="utf-8")) == data
    assert client.get(url).json()["groups"] == [{"name": "Grunt", "count": 1}]
    params = {"path": GRUNT}
    assert client.get(url + "/preview", params=params).status_code == 404
    preview = root / ".gdw/prefab-previews" / f"{GRUNT_GUID}.png"
    preview.parent.mkdir()
    image = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02"
        "0000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
    )
    preview.write_bytes(image)
    response = client.get(url + "/preview", params=params)
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content == image
    assert client.get(url).json()["prefabs"][0]["preview"] is True


def test_session_without_unity_project(env, tmp_path):
    client, _, _, state = env
    folder = tmp_path / "outside"
    # This project is four levels down and should not be discovered.
    write(folder / "A/B/C/D/ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.0.1f1\n")
    session = state.store.create(folder=str(folder))
    response = client.get(f"/api/sessions/{session['id']}/prefabs")
    assert response.status_code == 200
    result = response.json()
    assert result["root"] is None
    assert result["error"] == "no Unity project in this session's folder"
    assert result["groups"] == result["prefabs"] == []
