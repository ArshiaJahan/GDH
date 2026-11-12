import asyncio
import sys

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.agent.tools import ToolContext
from gamedevworkstation.app import AppState
from gamedevworkstation.server import create_app

from .conftest import FIXTURES, untrusted

H = {"Authorization": "Bearer t"}
SERVER = {"name": "demo", "transport": "stdio", "command": sys.executable,
          "args": [str(FIXTURES / "mcp" / "demo_server.py")]}


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "m.db")
    with TestClient(create_app("t", s)) as c:
        yield c, s


def test_add_test_and_list_tools(env):
    c, s = env
    assert c.post("/api/mcp/servers", json=SERVER, headers=H).status_code == 200
    r = c.post("/api/mcp/servers/demo/test", headers=H).json()
    assert r["ok"], r
    assert {t["name"] for t in r["tools"]} == {"add", "shout"}
    bad = c.post("/api/mcp/servers", json={"name": "bad", "transport": "stdio", "command": "/nonexistent/bin"}, headers=H)
    assert bad.status_code == 200
    assert c.post("/api/mcp/servers/bad/test", headers=H).json()["ok"] is False


async def test_session_tools_call_and_shared_approval(tmp_path):
    s = AppState(db_path=tmp_path / "m2.db")
    from gamedevworkstation.features import mcp_feature
    from fastapi import APIRouter, FastAPI

    mcp_feature.register(FastAPI(), APIRouter(), s)
    s.db.insert("mcp_servers", {"name": "demo", "transport": "stdio", "command": SERVER["command"],
                                "args": SERVER["args"], "env": {}, "headers": {}, "enabled_default": 1, "shared": 0})
    sess = s.store.create()
    await s.mcp.warm(sess)
    names = [t.name for t in s.mcp.tool_specs(sess)]
    assert "mcp__demo__add" in names
    ctx = ToolContext(app=s, session=sess, run_id="main:x")
    out = await s.mcp.call(ctx, "mcp__demo__add", {"a": 2, "b": 40})
    assert untrusted(out.text) == ("mcp:demo.add", "42") and not out.is_error  # marked as outside content
    # Per-session toggle off → not offered.
    sess2 = s.store.update(sess["id"], settings={"connectors": {"demo": False}})
    assert s.mcp.tool_specs(sess2) == []
    # Shared (other machine) servers: hidden until opted in, then every call asks.
    s.db.execute("UPDATE mcp_servers SET shared=1")
    sess3 = s.store.update(sess["id"], settings={"connectors": {}, "shared_tools": False})
    assert s.mcp.tool_specs(sess3) == []
    sess4 = s.store.update(sess["id"], settings={"shared_tools": True})
    assert "mcp__demo__shout" in [t.name for t in s.mcp.tool_specs(sess4)]
    ctx4 = ToolContext(app=s, session=sess4, run_id="main:x")
    task = asyncio.create_task(s.mcp.call(ctx4, "mcp__demo__shout", {"text": "hi"}))
    for _ in range(200):
        pend = s.approvals.pending(sess["id"])
        if pend:
            break
        await asyncio.sleep(0.01)
    assert pend[0]["kind"] == "shared_tool"
    s.approvals.resolve(pend[0]["id"], "approve")
    assert untrusted((await task).text) == ("mcp:demo.shout", "HI")
    await s.mcp.aclose()


def test_skills_api(env):
    c, s = env
    sk = c.get("/api/skills", headers=H).json()
    assert any(x["name"] == "delegation" for x in sk["skills"]) and sk["global"] == ["delegation"]
    content = "---\nname: notes\ndescription: Keep tidy notes.\n---\n\n# Notes\nBe brief."
    assert c.put("/api/skills/notes", json={"content": content}, headers=H).json()["name"] == "notes"
    assert c.get("/api/skills/notes", headers=H).json()["content"] == content
    assert c.put("/api/skills/Bad Name", json={"content": "x"}, headers=H).status_code == 400
    c.post("/api/skills/global", json={"names": ["delegation", "notes"]}, headers=H)
    new = c.post("/api/sessions", json={}, headers=H).json()
    assert new["settings"]["skills"] == ["delegation", "notes"]
