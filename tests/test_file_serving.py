"""/api/file: only safe types are served without the sandbox CSP; /api/file/resolve for the shell."""
import pytest
from fastapi.testclient import TestClient

from workspace.app import AppState
from workspace.config import data_dir
from workspace.server import create_app

H = {"Authorization": "Bearer t"}


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "f.db")
    with TestClient(create_app("t", s)) as c:
        yield c, s


SANDBOXED = ["page.html", "page.htm", "pic.svg", "pic.svgz", "doc.xhtml", "doc.xht", "data.xml", "style.xsl",
             "style.xslt", "archive.mht", "archive.mhtml", "page.shtml", "script.js", "notes.md", "blob.bin",
             "noext", "app.webmanifest", "page.HTML"]
INLINE = ["pic.png", "pic.jpg", "pic.gif", "pic.webp", "song.mp3", "clip.mp4", "doc.pdf", "notes.txt", "data.json"]


@pytest.mark.parametrize("name", SANDBOXED + INLINE)
def test_only_known_safe_types_skip_the_sandbox(env, name):
    c, _ = env
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("<script>alert(1)</script>")
    r = c.get("/api/file", params={"path": str(d / name)}, headers=H)
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    if name in SANDBOXED:
        assert r.headers.get("content-security-policy") == "sandbox", (name, r.headers.get("content-type"))
    else:
        assert "content-security-policy" not in r.headers, name


def test_resolve_only_answers_for_servable_files(env, tmp_path):
    c, s = env
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "report.html").write_text("x")
    (tmp_path / "secret.txt").write_text("x")
    s.store.create(folder=str(folder))
    link = folder / "link.txt"
    link.symlink_to(tmp_path / "secret.txt")
    r = c.get("/api/file/resolve", params={"path": str(folder / "sub" / ".." / "report.html")}, headers=H)
    assert r.status_code == 200 and r.json() == {"path": str((folder / "report.html").resolve())}
    for bad in (tmp_path / "secret.txt", link, folder, folder / "missing.txt"):
        assert c.get("/api/file/resolve", params={"path": str(bad)}, headers=H).status_code == 404, bad
    assert c.get("/api/file/resolve", params={"path": str(folder / "report.html")}).status_code == 401
