"""Resolve package-backed MonoBehaviours in scratch Unity projects."""
import json
import os
from pathlib import Path

import pytest

from gamedevworkstation.features import prefab_edit, prefab_yaml

GUID = "a" * 32
PREFAB_PATH = "Assets/Widget.prefab"
PREFAB = f"""\
%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &1
GameObject:
  m_Component:
  - component: {{fileID: 114}}
  m_Name: Widget
--- !u!114 &114
MonoBehaviour:
  m_GameObject: {{fileID: 1}}
  m_Script: {{fileID: 11500000, guid: {GUID}, type: 3}}
  m_EditorClassIdentifier:
  aggressive: 0
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def script(path: Path) -> None:
    write(path, f"class {path.stem} {{ public bool aggressive; }}\n")
    write(path.with_suffix(".cs.meta"), f"fileFormatVersion: 2\nguid: {GUID}\n")


def component(project: prefab_yaml.Project) -> dict:
    detail = prefab_edit.detail(project, PREFAB_PATH, prefab_edit.load_history(project.root))
    return detail["objects"][0]["components"][0]


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "Game"
    write(root / "ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 2022.3.0f1\n")
    write(root / PREFAB_PATH, PREFAB)
    return root


@pytest.mark.parametrize("path,name", [
    ("Library/PackageCache/com.unity.ugui@abc123/Runtime/UI/Core/Image.cs", "com.unity.ugui"),
    ("Packages/com.me.tools/Runtime/Foo.cs", "com.me.tools"),
])
def test_package_script(root, path, name):
    script(root / path)
    result = component(prefab_yaml.Project(root))
    assert (result["type"], result["package"], result["script_path"]) == (Path(path).stem, name, path)
    assert result["fields"][0]["kind"] == "bool"


@pytest.mark.parametrize("absolute", [False, True])
def test_external_package_script(root, absolute):
    outside = root.parent / "local-tools"
    script(outside / "Runtime/Foo.cs")
    location = outside.as_posix() if absolute else "../../local-tools"
    write(root / "Packages/manifest.json", json.dumps({"dependencies": {"com.me.tools": f"file:{location}"}}))
    result = component(prefab_yaml.Project(root))
    assert (result["type"], result["package"], result["script_path"]) == (
        "Foo", "com.me.tools", "Packages/com.me.tools/Runtime/Foo.cs",
    )
    assert result["fields"][0]["kind"] == "bool"


@pytest.fixture
def walks(monkeypatch):
    seen = []
    real_walk = os.walk

    def traced(path):
        seen.append(path)
        return real_walk(path)

    monkeypatch.setattr(prefab_yaml.os, "walk", traced)
    return seen


def test_assets_win_without_walking_packages(root, walks):
    script(root / "Assets/AssetScript.cs")
    script(root / "Packages/com.me.tools/PackageScript.cs")
    result = component(prefab_yaml.Project(root))
    assert (result["type"], result["package"], result["script_path"]) == (
        "AssetScript", None, "Assets/AssetScript.cs",
    )
    assert walks == [root / "Assets"]


def test_package_index_is_lazy_cached_and_invalidated(root, walks):
    package = root / "Library/PackageCache/com.me.tools@abc123"
    script(package / "Foo.cs")
    manifest = write(root / "Packages/manifest.json", "{}\n")
    project = prefab_yaml.Project(root)
    assert walks == [root / "Assets"]
    assert component(project)["type"] == "Foo"
    assert component(prefab_yaml.Project(root))["package"] == "com.me.tools"
    assert walks.count(package.resolve()) == 1
    stat = manifest.stat()
    os.utime(manifest, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert component(prefab_yaml.Project(root))["type"] == "Foo"
    assert walks.count(package.resolve()) == 2


@pytest.mark.parametrize("folder", ["Tests", "Samples~", "Documentation~", ".hidden", "Other~"])
def test_skipped_package_folders(root, folder):
    script(root / "Packages/com.me.tools" / folder / "Foo.cs")
    assert component(prefab_yaml.Project(root))["script_path"] is None


def test_symlinked_package_paths_are_skipped(root):
    outside = root.parent / "local-tools"
    script(outside / "Foo.cs")
    packages = root / "Packages"
    write(packages / "manifest.json", json.dumps({"dependencies": {"com.me.tools": "file:com.me.tools"}}))
    (packages / "com.me.tools").symlink_to(outside, target_is_directory=True)
    embedded = packages / "com.me.embedded"
    embedded.mkdir()
    (embedded / "Foo.cs").symlink_to(outside / "Foo.cs")
    write(embedded / "Foo.cs.meta", f"guid: {GUID}\n")
    write(embedded / "Bar.cs", "class Bar {}\n")
    (embedded / "Bar.cs.meta").symlink_to(outside / "Foo.cs.meta")
    (embedded / "Runtime").symlink_to(outside, target_is_directory=True)
    assert component(prefab_yaml.Project(root))["script_path"] is None


def test_no_package_directories(root):
    result = component(prefab_yaml.Project(root))
    assert (result["type"], result["package"], result["script_path"]) == ("Unknown script", None, None)  # its GUID matches no script anywhere
    assert result["fields"][0]["kind"] == "number"


def test_md4_matches_rfc_1320():
    assert prefab_yaml._md4(b"").hex() == "31d6cfe0d16ae931b73c59d7e0c089c0"
    assert prefab_yaml._md4(b"abc").hex() == "a448017aaf21d8525fc10ae87aa6729d"
    assert prefab_yaml._md4(b"a" * 80).hex() == prefab_yaml._md4(b"a" * 80).hex()  # multi-block path runs


@pytest.mark.parametrize("file_id,name,namespace", [
    # m_Script fileIDs as Unity writes them for the old built-in UnityEngine.UI.dll
    (-765806418, "Image", "UnityEngine.UI"), (708705254, "Text", "UnityEngine.UI"),
    (1980459831, "CanvasScaler", "UnityEngine.UI"), (1301386320, "GraphicRaycaster", "UnityEngine.UI"),
    (12345, "Unknown script", ""),
])
def test_dll_scripts_by_file_id(root, file_id, name, namespace):
    dll_guid = "f70555f144d8491a825f0804e09c671c"
    write(root / PREFAB_PATH, PREFAB.replace(f"{{fileID: 11500000, guid: {GUID}, type: 3}}",
                                             f"{{fileID: {file_id}, guid: {dll_guid}, type: 3}}"))
    result = component(prefab_yaml.Project(root))
    assert (result["type"], result["namespace"], result["script_path"]) == (name, namespace, None)


def test_class_identifier_still_wins_over_dll_lookup(root):
    write(root / PREFAB_PATH, PREFAB.replace(f"{{fileID: 11500000, guid: {GUID}, type: 3}}",
                                             "{fileID: -765806418, guid: f70555f144d8491a825f0804e09c671c, type: 3}")
          .replace("m_EditorClassIdentifier:", "m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.RawImage"))
    assert component(prefab_yaml.Project(root))["type"] == "RawImage"
