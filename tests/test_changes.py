import subprocess

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "c.db")
    with TestClient(create_app("t", s)) as c:
        yield c, s, tmp_path


def test_git_changes_diff_revert(env):
    c, s, tmp = env
    repo = tmp / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\ny = 2\n")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"]):
        subprocess.run(cmd, cwd=repo, check=True)
    sid = s.store.create(folder=str(repo))["id"]
    (repo / "a.py").write_text("x = 1\ny = 3\nz = 4\n")
    (repo / "new.txt").write_text("hello\n")
    ch = c.get(f"/api/sessions/{sid}/changes", headers=H).json()
    by = {f["path"]: f for f in ch["files"]}
    assert ch["mode"] == "git" and by["a.py"]["added"] == 2 and by["a.py"]["removed"] == 1
    assert by["new.txt"]["status"] == "added"
    d = c.get(f"/api/sessions/{sid}/changes/diff", params={"root": str(repo), "path": "a.py"}, headers=H).json()
    assert d["original"] == "x = 1\ny = 2\n" and "z = 4" in d["modified"] and d["language"] == "python"
    c.post(f"/api/sessions/{sid}/changes/revert", json={"root": str(repo), "path": "a.py"}, headers=H)
    c.post(f"/api/sessions/{sid}/changes/revert", json={"root": str(repo), "path": "new.txt"}, headers=H)
    assert (repo / "a.py").read_text() == "x = 1\ny = 2\n" and not (repo / "new.txt").exists()
    assert c.get(f"/api/sessions/{sid}/changes", headers=H).json()["files"] == []
    # Can't reach outside the session's folders.
    assert c.get(f"/api/sessions/{sid}/changes/diff", params={"root": "/etc", "path": "passwd"}, headers=H).status_code == 403


def test_snapshot_changes_without_git(env):
    c, s, tmp = env
    folder = tmp / "plain"
    folder.mkdir()
    (folder / "doc.md").write_text("one\n")
    sid = s.store.create(folder=str(folder))["id"]
    s.changes.snapshot(sid, folder / "doc.md")
    (folder / "doc.md").write_text("one\ntwo\n")
    s.changes.snapshot(sid, folder / "made.txt")
    (folder / "made.txt").write_text("new\n")
    ch = c.get(f"/api/sessions/{sid}/changes", headers=H).json()
    assert ch["mode"] == "snapshots"
    assert {(f["path"], f["status"], f["added"]) for f in ch["files"]} == {("doc.md", "modified", 1), ("made.txt", "added", 1)}
    c.post(f"/api/sessions/{sid}/changes/revert", json={"root": str(folder), "path": "doc.md"}, headers=H)
    assert (folder / "doc.md").read_text() == "one\n"
