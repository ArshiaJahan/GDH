import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/unity-onboarding/scripts/onboard.py"


def write(root, name, contents):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def onboard(folder, *args):
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), str(folder), *args],
        cwd=folder,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "workspace" / "Game"
    write(root, "ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.0.1f1\n")
    write(root, "Packages/manifest.json", '{"dependencies": {}}\n')
    write(root, "Assets/Scripts/A.cs", "// TODO: Finish the controller\n")
    write(
        root,
        "ProjectSettings/EditorBuildSettings.asset",
        "EditorBuildSettings:\n  m_Scenes:\n  - enabled: 1\n"
        "    path: Assets/Scenes/Main Scene.unity\n",
    )
    write(
        root,
        "BACKLOG.md",
        "# Backlog\n\n"
        "## M0 First playable\nStatus: active\n\n"
        "### M0-S01 Queue the tutorial\n- Status: todo\n\n"
        "### M0-S02 Tune the controller\n- Status: doing\n\n"
        "### M0-S03 Deliver the prototype\n- Status: done\n\n"
        "### M0-S04 Import animation\n- Status: blocked\n",
    )
    write(root, "HANDOFF.md", "# Handoff\n\n## Next steps\n- Check the input map\n- [x] Review old map\n")
    write(root, "TODO.md", "# TODO\n- [ ] Add a camera\n- [x] Remove old camera\n")
    return root


def test_nested_project_and_todos(project, tmp_path):
    result = onboard(tmp_path, "--no-write")
    assert result.returncode == 0, result.stderr
    assert f"root: {project.resolve()}\n" in result.stdout
    assert "build scenes: Main Scene\n" in result.stdout
    assert "active milestone M0 First playable" in result.stdout
    assert "\n1. M0-S02 Tune the controller [doing]" in result.stdout
    assert "\n2. M0-S01 Queue the tutorial [todo]" in result.stdout
    assert "\n3. Check the input map [todo]" in result.stdout
    assert "\n4. Add a camera [todo]" in result.stdout
    todo_section = result.stdout.split("## Open to-dos", 1)[1]
    assert "Deliver the prototype" not in todo_section
    assert "Review old map" not in todo_section
    assert "Remove old camera" not in todo_section
    assert todo_section.count("M0-S04") == 1
    assert "\nblocked: M0-S04 Import animation\n" in result.stdout
    assert not (project / ".gdw").exists()


def test_code_todos(project):
    for args in (("init", "-q"), ("add", "Assets/Scripts/A.cs")):
        subprocess.run(
            ["git", *args], cwd=project, stdin=subprocess.DEVNULL, check=True, timeout=10
        )

    result = onboard(project, "--no-write")
    assert result.returncode == 0, result.stderr
    assert "code TODO/FIXME/HACK: 1 (top: Assets/Scripts/A.cs (1))" in result.stdout


def test_missing_project(tmp_path):
    result = onboard(tmp_path, "--no-write")
    assert result.returncode == 1
    assert result.stdout.startswith("RESULT: FAIL no Unity project")


def test_cache_and_changed_handoff(project):
    first = onboard(project)
    assert first.returncode == 0, first.stderr
    assert first.stdout.splitlines()[-1] == "RESULT: OK todos=4 changed_docs=0 cached=no"
    ignore = project / ".gdw" / ".gitignore"
    assert ignore.read_text(encoding="utf-8") == "onboarding.json\n"

    second = onboard(project)
    assert second.returncode == 0, second.stderr
    assert second.stdout.splitlines()[-1] == "RESULT: OK todos=4 changed_docs=0 cached=yes"

    write(project, "HANDOFF.md", "# Handoff\n\n## Next steps\n- Verify controller bindings\n")
    third = onboard(project)
    assert third.returncode == 0, third.stderr
    assert "HANDOFF.md **CHANGED**" in third.stdout
    assert "Verify controller bindings" in third.stdout
    assert third.stdout.splitlines()[-1] == "RESULT: OK todos=4 changed_docs=1 cached=no"


def test_compact_docs_and_metadata(project):
    for folder in ("HandOffDocs", "docs", "design", "production"):
        for index in range(8):
            write(project, f"{folder}/note-{index}.md", "# Notes\n")
    for index in range(45):
        write(project, f"docs/topic-notes/note-{index:02}.md", "# Toy\n")
    for index in range(20):
        write(project, f"production/archive/report-{index:02}.md", "# Report\n")

    result = onboard(project)
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) <= 60
    for folder in ("HandOffDocs", "docs", "design", "production"):
        assert f"{folder}/note-0.md" in result.stdout
        assert f"{folder}/note-6.md" not in result.stdout
    assert "docs/ (+47 more .md" in result.stdout
    assert "docs/topic-notes/note-00.md" not in result.stdout

    result = onboard(project, "--json", "--no-write")
    assert result.returncode == 0, result.stderr
    docs = json.loads(result.stdout)["docs"]
    assert len(docs) == 60
    tracked = next(doc for doc in docs if doc["path"] == "docs/topic-notes/note-00.md")
    assert tracked["sha"] and tracked["mtime"]

    write(project, tracked["path"], "# Changed toy\n")
    result = onboard(project, "--no-write")
    assert result.returncode == 0, result.stderr
    assert "docs/ (+47 more .md: topic-notes/ 45) **CHANGED**" in result.stdout
    assert result.stdout.splitlines()[-1] == "RESULT: OK todos=4 changed_docs=1 cached=no"


def test_skill_is_indexed_cheaply_and_routed():
    from gamedevworkstation import skills as sk
    from gamedevworkstation.agent.context import est

    settings = {"skill_mode": "progressive", "pinned_skills": ["delegation"]}
    line = next(x for x in sk.skills_index(settings).splitlines() if x.startswith("- unity-onboarding:"))
    assert est(line) <= 60
    assert est(sk.skill_load_text("unity-onboarding")) <= 1000
    files = sk.skill_files("unity-onboarding")
    assert {"scripts/onboard.py", "references/practices.md", "references/handoff-template.md"} <= set(files)
    router = (Path(__file__).resolve().parents[1] / "skills" / "unity-router" / "SKILL.md").read_text(encoding="utf-8")
    assert "| 3 |" in router and "unity-onboarding" in router.split("| 3 |", 1)[1].split("\n", 1)[0]


PLAIN = ("%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_Name: {name}\n--- !u!4 &2\nTransform:\n  m_GameObject: {{fileID: 1}}\n"
         "  m_Children: []\n  m_Father: {{fileID: 0}}\n")
VARIANT = ("%YAML 1.1\n--- !u!1001 &1\nPrefabInstance:\n  m_Modification:\n    serializedVersion: 3\n"
           "    m_TransformParent: {{fileID: 0}}\n    m_Modifications: []\n"
           "  m_SourcePrefab: {{fileID: 100100000, guid: {base}, type: 3}}\n"
           "--- !u!4 &2 stripped\nTransform:\n  m_PrefabInstance: {{fileID: 1}}\n")


def prefab(root, rel, guid, base=None):
    write(root, rel, VARIANT.format(base=base) if base else PLAIN.format(name=Path(rel).stem))
    write(root, rel + ".meta", f"fileFormatVersion: 2\nguid: {guid}\n")


def test_prefabs_fill_categories_by_folder(project):
    g = lambda n: f"{n:032x}"
    prefab(project, "Assets/Game/Enemies/Grunt.prefab", g(1))
    prefab(project, "Assets/Game/Enemies/Brute.prefab", g(2), base=g(1))
    prefab(project, "Assets/Game/Enemies/Elite/BruteElite.prefab", g(3), base=g(2))
    prefab(project, "Assets/Game/Enemies/Ghost.prefab", g(4), base=g(99))
    prefab(project, "Assets/Props/Crate.prefab", g(5))

    dry = onboard(project, "--no-write")
    assert "5 prefabs in 3 folders; 3 variants (up to 2 deep)" in dry.stdout
    assert "**1 variants have a missing base prefab**: Assets/Game/Enemies/Ghost.prefab" in dry.stdout
    assert "not written (--no-write)" in dry.stdout
    assert not (project / ".gdw" / "prefab-categories.json").exists()

    first = onboard(project)
    assert "Prefabs tab categories written: one per folder" in first.stdout
    cats = json.loads((project / ".gdw" / "prefab-categories.json").read_text(encoding="utf-8"))["categories"]
    assert cats == {"Game/Enemies": ["Assets/Game/Enemies/*.prefab"],
                    "Game/Enemies/Elite": ["Assets/Game/Enemies/Elite/*.prefab"], "Props": ["Assets/Props/*.prefab"]}

    # The Prefabs tab groups by exactly these categories: nested folders don't fall into their parent's group.
    from gamedevworkstation.features.prefabs import _scan
    scan = _scan(project, "category")
    assert {p["name"]: p["group"] for p in scan["prefabs"]} == {
        "Grunt": "Game/Enemies", "Brute": "Game/Enemies", "Ghost": "Game/Enemies",
        "BruteElite": "Game/Enemies/Elite", "Crate": "Props"}
    assert {p["name"]: (p["variant_of"] or {}).get("name") for p in scan["prefabs"]}["BruteElite"] == "Brute"

    # A new folder refreshes our own file; once the user sets their own categories, onboarding leaves them alone.
    prefab(project, "Assets/FX/Spark.prefab", g(6))
    assert "categories updated" in onboard(project).stdout
    assert "FX" in json.loads((project / ".gdw" / "prefab-categories.json").read_text(encoding="utf-8"))["categories"]
    write(project, ".gdw/prefab-categories.json", '{"categories": {"Mine": ["Assets/**"]}}\n')
    assert "kept the user's own Prefabs tab categories" in onboard(project, "--refresh").stdout
    assert json.loads((project / ".gdw" / "prefab-categories.json").read_text(encoding="utf-8")) == {
        "categories": {"Mine": ["Assets/**"]}}


def test_old_gitignore_gets_onboarding_cache(project):
    write(project, ".gdw/.gitignore", "orientation.json\n")
    onboard(project)
    assert (project / ".gdw" / ".gitignore").read_text(encoding="utf-8") == "orientation.json\nonboarding.json\n"
