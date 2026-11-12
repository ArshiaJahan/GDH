"""The new-session screen's backend: claude_code (the Claude subscription) is the default harness of
new sessions, the greeting name, and the permission modes (no bypass)."""
import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.config import load_config
from gamedevworkstation.features import session_routes
from gamedevworkstation.server import create_app, new_session_harness

TOKEN = "test-token"
H = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _account_name_cache():
    lookup = session_routes.account_full_name
    lookup.cache_clear()
    yield
    lookup.cache_clear()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(TOKEN, AppState(db_path=tmp_path / "n.db"))) as c:
        yield c


@pytest.mark.shipped_harness_default
def test_new_sessions_default_to_claude_code(client):
    assert load_config().sessions["default_harness"] == "claude_code"
    r = client.post("/api/sessions", json={}, headers=H)  # no CLI needed to open it (GDW_CLAUDE_CLI_SEARCH=0)
    assert r.status_code == 200, r.text
    assert r.json()["harness"] == "claude_code"
    # Chosen settings come along; an explicit harness still wins (API clients).
    r = client.post("/api/sessions", json={"harness": "builtin", "mode": "plan", "effort": "high"}, headers=H)
    assert r.status_code == 200 and r.json()["harness"] == "builtin" and r.json()["mode"] == "plan"


@pytest.mark.shipped_harness_default
def test_internal_creators_keep_the_builtin_loop(tmp_path):
    S = AppState(db_path=tmp_path / "i.db")
    assert S.store.create(title="Scheduled")["harness"] == "builtin"  # scheduled tasks, campaigns, fleet


@pytest.mark.shipped_harness_default
def test_default_harness_setting(tmp_path):
    cfg = load_config()
    cfg.sessions["default_harness"] = "codex_cli"
    assert new_session_harness(cfg) == "codex_cli"
    cfg.sessions["default_harness"] = "nonsense"
    assert new_session_harness(cfg) == "claude_code"
    cfg.sessions.pop("default_harness")
    assert new_session_harness(cfg) == "claude_code"


def test_modes_have_no_bypass(client):
    env = client.get("/api/environment", headers=H).json()
    assert env["modes"] == ["plan", "ask", "accept_edits"]
    for bad in ("bypassPermissions", "bypass", "dontAsk", "auto"):
        assert client.post("/api/sessions", json={"mode": bad}, headers=H).status_code == 400
    sid = client.post("/api/sessions", json={"mode": "accept_edits"}, headers=H).json()["id"]
    assert client.patch(f"/api/sessions/{sid}", json={"mode": "bypassPermissions"}, headers=H).status_code == 400
    assert client.patch(f"/api/sessions/{sid}", json={"mode": "plan"}, headers=H).json()["mode"] == "plan"


@pytest.mark.parametrize("full,name", [
    ("Arshia Jahan", "Arshia J."),
    ("  arshia   jahan-smith ", "arshia J."),
    ("Mary Ann van der Berg", "Mary B."),
    ("Arshia", "Arshia"),
    ("Élodie Ñúñez", "Élodie Ñ."),
    ("", None),
    ("   ", None),
    ("arshia@example.com", None),
    ("Arshia Jahan <arshia@example.com>", None),
    ("1234 5678", None),
])
def test_greeting_name_format(full, name):
    assert session_routes.greeting_name(full) == name


def test_greeting_endpoint(client, monkeypatch):
    monkeypatch.setattr(session_routes, "account_full_name", lambda: "Arshia Jahan")
    assert client.get("/api/greeting", headers=H).json() == {"name": "Arshia J."}
    monkeypatch.setattr(session_routes, "account_full_name", lambda: "someone@example.com")
    assert client.get("/api/greeting", headers=H).json() == {"name": None}
    monkeypatch.setattr(session_routes, "account_full_name", lambda: "")
    assert client.get("/api/greeting", headers=H).json() == {"name": None}


def test_account_full_name_reads_only_the_local_account(monkeypatch):
    calls = []

    def run(argv, **_kw):
        calls.append(argv)
        raise OSError("no id")

    monkeypatch.setattr(session_routes.subprocess, "run", run)
    monkeypatch.setattr(session_routes.sys, "platform", "darwin")
    name = session_routes.account_full_name()  # falls back to the passwd entry
    assert calls == [["/usr/bin/id", "-F"]]
    assert isinstance(name, str) and "@" not in (session_routes.greeting_name(name) or "")


def test_account_full_name_is_cached_for_repeated_greetings(client, monkeypatch):
    from types import SimpleNamespace

    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="Arshia Jahan\n")

    monkeypatch.setattr(session_routes.subprocess, "run", run)
    monkeypatch.setattr(session_routes.sys, "platform", "darwin")
    for _ in range(3):
        assert client.get("/api/greeting", headers=H).json() == {"name": "Arshia J."}
    assert calls == [["/usr/bin/id", "-F"]]
