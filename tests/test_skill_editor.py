"""The Skills page editor API: a skill's other files, read-only built-ins, and Customize."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workspace import skills as sk
from workspace.app import AppState
from workspace.server import create_app

H = {"Authorization": "Bearer t"}


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app("t", AppState(db_path=tmp_path / "s.db"))) as client:
        yield client


def test_builtin_files_are_listed_and_readable_but_not_writable(c):
    r = c.get("/api/skills/game-designer/files", headers=H).json()
    assert r["source"] == "builtin" and r["editable"] is False
    paths = [f["path"] for f in r["files"]]
    assert paths and "SKILL.md" not in paths and all(f["size"] > 0 for f in r["files"])
    ref = next(p for p in paths if p.startswith("references/"))
    f = c.get("/api/skills/game-designer/file", params={"path": ref}, headers=H).json()
    assert f["editable"] is False and f["binary"] is False and f["content"]
    r = c.put("/api/skills/game-designer/file", params={"path": ref}, json={"content": "x"}, headers=H)
    assert r.status_code == 403
    assert (sk.builtin_skills_dir() / "game-designer" / ref).read_text() == f["content"]


@pytest.mark.parametrize("path", ["../delegation/SKILL.md", "/etc/hosts", "SKILL.md", "nope.md", ""])
def test_paths_outside_the_skill_or_its_skill_md_are_404(c, path):
    assert c.get("/api/skills/game-designer/file", params={"path": path}, headers=H).status_code == 404


def test_customize_copies_the_whole_folder_and_overrides_the_builtin(c):
    before = {x["name"]: x for x in c.get("/api/skills", headers=H).json()["skills"]}["game-designer"]
    assert before["source"] == "builtin" and before["overrides_builtin"] is False
    builtin_files = sk.skill_files("game-designer")
    s = c.post("/api/skills/game-designer/customize", headers=H).json()
    assert s["source"] == "user" and s["overrides_builtin"] is True
    assert s["content"] == (sk.builtin_skills_dir() / "game-designer" / "SKILL.md").read_text()
    assert sk.skill_files("game-designer") == builtin_files  # the user's copy has them all
    # The copy's files are editable; the built-in stays untouched.
    ref = next(p for p in builtin_files if p.startswith("references/"))
    r = c.put("/api/skills/game-designer/file", params={"path": ref}, json={"content": "mine\n"}, headers=H)
    assert r.status_code == 200 and r.json()["content"] == "mine\n" and r.json()["editable"] is True
    assert (sk.builtin_skills_dir() / "game-designer" / ref).read_text() != "mine\n"
    # Customizing again keeps the user's edits.
    c.post("/api/skills/game-designer/customize", headers=H)
    assert c.get("/api/skills/game-designer/file", params={"path": ref}, headers=H).json()["content"] == "mine\n"
    # New files can't be created through the file endpoint.
    assert c.put("/api/skills/game-designer/file", params={"path": "references/new.md"}, json={"content": "x"},
                 headers=H).status_code == 404


def test_customize_unknown_or_user_skill(c):
    assert c.post("/api/skills/no-such-skill/customize", headers=H).status_code == 404
    sk.save_skill("mine", "---\nname: mine\ndescription: Mine.\n---\nBody")
    assert c.post("/api/skills/mine/customize", headers=H).json()["source"] == "user"


def test_first_save_over_a_builtin_keeps_its_other_files(c):
    r = c.put("/api/skills/game-designer", json={"content": "---\nname: game-designer\ndescription: Mine.\n---\nMine"},
              headers=H)
    assert r.status_code == 200
    user = Path(r.json()["path"]).parent
    assert user.parent == sk.user_skills_dir()
    assert sk.skill_files("game-designer") and all((user / f).is_file() for f in sk.skill_files("game-designer"))
    assert (user / "SKILL.md").read_text().endswith("Mine")


def test_binary_files_are_flagged_not_dumped(c):
    sk.save_skill("bin", "---\nname: bin\ndescription: B.\n---\nBody")
    (sk.user_skills_dir() / "bin" / "assets").mkdir()
    (sk.user_skills_dir() / "bin" / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    f = c.get("/api/skills/bin/file", params={"path": "assets/logo.png"}, headers=H).json()
    assert f["binary"] is True and f["content"] == ""
    r = c.put("/api/skills/bin/file", params={"path": "assets/logo.png"}, json={"content": "x"}, headers=H)
    assert r.status_code == 400
