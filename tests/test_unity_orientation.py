import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/unity-orientation/scripts/orient.py"


def write(root, name, contents):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def orient(folder, *args):
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
    result = orient(tmp_path, "--no-write")
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

    result = orient(project, "--no-write")
    assert result.returncode == 0, result.stderr
    assert "code TODO/FIXME/HACK: 1 (top: Assets/Scripts/A.cs (1))" in result.stdout


def test_missing_project(tmp_path):
    result = orient(tmp_path, "--no-write")
    assert result.returncode == 1
    assert result.stdout.startswith("RESULT: FAIL no Unity project")


def test_cache_and_changed_handoff(project):
    first = orient(project)
    assert first.returncode == 0, first.stderr
    assert first.stdout.splitlines()[-1] == "RESULT: OK todos=4 changed_docs=0 cached=no"
    ignore = project / ".gdw" / ".gitignore"
    assert ignore.read_text(encoding="utf-8") == "orientation.json\n"

    second = orient(project)
    assert second.returncode == 0, second.stderr
    assert second.stdout.splitlines()[-1] == "RESULT: OK todos=4 changed_docs=0 cached=yes"

    write(project, "HANDOFF.md", "# Handoff\n\n## Next steps\n- Verify controller bindings\n")
    third = orient(project)
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

    result = orient(project)
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) <= 60
    for folder in ("HandOffDocs", "docs", "design", "production"):
        assert f"{folder}/note-0.md" in result.stdout
        assert f"{folder}/note-6.md" not in result.stdout
    assert "docs/ (+47 more .md" in result.stdout
    assert "docs/topic-notes/note-00.md" not in result.stdout

    result = orient(project, "--json", "--no-write")
    assert result.returncode == 0, result.stderr
    docs = json.loads(result.stdout)["docs"]
    assert len(docs) == 60
    tracked = next(doc for doc in docs if doc["path"] == "docs/topic-notes/note-00.md")
    assert tracked["sha"] and tracked["mtime"]

    write(project, tracked["path"], "# Changed toy\n")
    result = orient(project, "--no-write")
    assert result.returncode == 0, result.stderr
    assert "docs/ (+47 more .md: topic-notes/ 45) **CHANGED**" in result.stdout
    assert result.stdout.splitlines()[-1] == "RESULT: OK todos=4 changed_docs=1 cached=no"


def test_skill_is_indexed_cheaply_and_routed():
    from gamedevworkstation import skills as sk
    from gamedevworkstation.agent.context import est

    settings = {"skill_mode": "progressive", "pinned_skills": ["delegation"]}
    line = next(x for x in sk.skills_index(settings).splitlines() if x.startswith("- unity-orientation:"))
    assert est(line) <= 60
    assert est(sk.skill_load_text("unity-orientation")) <= 1000
    files = sk.skill_files("unity-orientation")
    assert {"scripts/orient.py", "references/practices.md", "references/handoff-template.md"} <= set(files)
    router = (Path(__file__).resolve().parents[1] / "skills" / "unity-router" / "SKILL.md").read_text(encoding="utf-8")
    assert "| 3 |" in router and "unity-orientation" in router.split("| 3 |", 1)[1].split("\n", 1)[0]
