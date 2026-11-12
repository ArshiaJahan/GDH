import time

import pytest
from fastapi.testclient import TestClient

from workspace.app import AppState
from workspace.server import create_app

H = {"Authorization": "Bearer t"}


@pytest.fixture
def setup(tmp_path):
    s = AppState(db_path=tmp_path / "i.db")
    a = s.store.create(title="Alpha")["id"]
    time.sleep(0.01)
    b = s.store.create(title="Beta")["id"]
    f = tmp_path / "files"
    f.mkdir()
    (f / "report.html").write_text("<html><title>Quarterly report</title><body>revenue grew</body></html>")
    (f / "notes.pdf").write_bytes(b"%PDF-1.4 not really")
    (f / "voice.mp3").write_bytes(b"ID3")
    (f / "data.csv").write_text("a,b\n1,2\n")
    s.items.add_file(f / "report.html", source="agent", session_id=a, provider="anthropic", model="claude-opus-5-5")
    s.items.add_file(f / "data.csv", source="agent", session_id=a, provider="openai", model="gpt-6.1-sol")
    s.items.add_file(f / "voice.mp3", source="tool", session_id=b, provider="elevenlabs", model="eleven_v4",
                     extracted_text="welcome to the show")
    s.items.add_file(f / "notes.pdf", source="user", session_id=b, provider="anthropic", model="claude-opus-5-5",
                     extracted_text="revenue figures for Q3")
    s.items.add(kind="link", source="agent", session_id=a, provider="anthropic", url="https://example.com/a", title="A")
    assert s.items.add(kind="link", source="agent", session_id=a, url="https://example.com/a") is None  # de-duplicated
    s.items.add(kind="link", source="agent", session_id=b, url="https://example.com/a", title="A")  # other session ok
    with TestClient(create_app("t", s)) as c:
        yield c, s, a, b


def ids(groups):
    return [(g["session_title"], sorted(i["filename"] or i["url"] for i in g["items"])) for g in groups]


def test_tabs_provider_filter_and_groups(setup):
    c, s, a, b = setup
    assert ids(c.get("/api/items?tab=artifacts", headers=H).json()) == [("Alpha", ["report.html"])]
    assert ids(c.get("/api/items?tab=media", headers=H).json()) == [("Beta", ["voice.mp3"])]
    files = ids(c.get("/api/items?tab=files", headers=H).json())
    assert files == [("Beta", ["notes.pdf"]), ("Alpha", ["data.csv"])]  # sessions by last activity
    links = c.get("/api/items?tab=links", headers=H).json()
    assert sorted(g["count"] for g in links) == [1, 1]
    assert ids(c.get("/api/items?tab=files&provider=codex", headers=H).json()) == [("Alpha", ["data.csv"])]
    assert ids(c.get("/api/items?tab=media&provider=elevenlabs", headers=H).json()) == [("Beta", ["voice.mp3"])]
    assert c.get("/api/items?tab=media&provider=claude", headers=H).json() == []
    counts = c.get(f"/api/items/counts?sessions={a}", headers=H).json()
    assert counts == {"artifacts": 1, "media": 0, "files": 1, "links": 1}


def test_search_scoped_to_one_session(setup):
    c, s, a, b = setup
    everywhere = c.get("/api/items/search?q=revenue", headers=H).json()
    assert {g["session_title"] for g in everywhere} == {"Alpha", "Beta"}
    only_b = c.get(f"/api/items/search?q=revenue&sessions={b}", headers=H).json()
    assert [g["session_title"] for g in only_b] == ["Beta"]
    hit = only_b[0]["items"][0]
    assert hit["filename"] == "notes.pdf" and "<mark>revenue</mark>" in hit["hl_text"]
    assert c.get(f"/api/items/search?q=quarterly&sessions={b}", headers=H).json() == []
    assert c.get("/api/items/search?q=quart", headers=H).json()[0]["items"][0]["filename"] == "report.html"  # prefix


def test_artifact_versions(setup, tmp_path):
    c, s, a, b = setup
    p = tmp_path / "files" / "report.html"
    p.write_text("<html><title>v2</title></html>")
    s.items.add_file(p, source="agent", session_id=a, provider="anthropic", model="claude-sonnet-5-5")
    arts = c.get("/api/items?tab=artifacts", headers=H).json()[0]["items"]
    assert len(arts) == 1 and arts[0]["version"] == 2
    assert [v["version"] for v in c.get(f"/api/items/{arts[0]['id']}", headers=H).json()["versions"]] == [2, 1]


def test_agent_write_indexes_artifact(setup, tmp_path):
    c, s, a, b = setup
    folder = tmp_path / "proj"
    folder.mkdir()
    s.store.update(a, folder=str(folder))
    p = folder / "chart.svg"
    p.write_text("<svg/>")
    s.changes.notify(a, p)
    arts = [i["filename"] for g in c.get(f"/api/items?tab=artifacts&sessions={a}", headers=H).json() for i in g["items"]]
    assert "chart.svg" in arts
