import json
import os
import stat
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from gamedevworkstation.app import AppState
from gamedevworkstation.server import create_app

H = {"Authorization": "Bearer t"}

FAKE_CODEX = r"""#!/usr/bin/env python3
import json, sys, os
args = sys.argv[1:]
prompt = sys.stdin.read()
open(os.environ["FAKE_CODEX_LOG"], "a").write(json.dumps({"args": args, "prompt": prompt}) + "\n")
cwd = args[args.index("-C") + 1]
def emit(o): print(json.dumps(o), flush=True)
emit({"type": "thread.started", "thread_id": "thr_123"})
emit({"type": "item.completed", "item": {"id": "i1", "type": "command_execution", "command": "bash -lc ls", "status": "completed", "aggregated_output": "a.py", "exit_code": 0}})
open(os.path.join(cwd, "codex_out.txt"), "w").write("written by codex")
emit({"type": "item.completed", "item": {"id": "i2", "type": "file_change", "changes": [{"path": "codex_out.txt", "kind": "add"}], "status": "completed"}})
emit({"type": "item.completed", "item": {"id": "i3", "type": "agent_message", "text": "Done: wrote codex_out.txt"}})
emit({"type": "turn.completed", "usage": {"input_tokens": 2000, "cached_input_tokens": 1500, "output_tokens": 300, "reasoning_output_tokens": 100}})
"""


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "codex"
    exe.write_text(FAKE_CODEX)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "codex.log"
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    return log


@pytest.fixture
def env(tmp_path):
    s = AppState(db_path=tmp_path / "h.db")
    with TestClient(create_app("t", s)) as c:
        yield c, s


def wait_idle(c, sid):
    for _ in range(200):
        if not c.get(f"/api/sessions/{sid}", headers=H).json()["running"]:
            return
        time.sleep(0.03)
    raise TimeoutError


def test_codex_cli_harness(env, fake_codex, tmp_path):
    c, s = env
    folder = tmp_path / "proj"
    folder.mkdir()
    s.config.modes["allowlist"] = ["codex_cli:*"]  # Accept edits asks too (test_codex_cli_asks_in_accept_edits)
    sid = c.post("/api/sessions", json={"folder": str(folder), "mode": "accept_edits"}, headers=H).json()["id"]
    assert c.patch(f"/api/sessions/{sid}", json={"harness": "codex_cli"}, headers=H).status_code == 200
    c.post(f"/api/sessions/{sid}/messages", json={"text": "write a file"}, headers=H)
    wait_idle(c, sid)
    msgs = c.get(f"/api/sessions/{sid}/messages", headers=H).json()
    assert msgs[-1]["content"][0]["text"] == "Done: wrote codex_out.txt"
    assert any(b.get("name") == "shell" for m in msgs for b in m["content"])
    assert (folder / "codex_out.txt").exists()
    call = json.loads(fake_codex.read_text().splitlines()[0])
    a = call["args"]
    assert a[:2] == ["exec", "--json"] and a[a.index("-m") + 1] == "gpt-6.1-sol" and "workspace-write" in a
    assert call["prompt"] == "write a file"
    u = s.db.one("SELECT * FROM usage_records WHERE session_id=?", [sid])
    assert (u["provider"], u["input_tokens"], u["cache_read_tokens"], u["reasoning_tokens"]) == ("openai", 500, 1500, 100)
    # Second turn resumes the thread.
    c.post(f"/api/sessions/{sid}/messages", json={"text": "again"}, headers=H)
    wait_idle(c, sid)
    second = json.loads(fake_codex.read_text().splitlines()[1])["args"]
    assert "resume" in second and "thr_123" in second


def test_codex_cli_subagent_unit(env, fake_codex, tmp_path):
    import asyncio

    from gamedevworkstation.agent.tools import ToolContext

    c, s = env
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x=1\n")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"]):
        subprocess.run(cmd, cwd=repo, check=True)
    sess = s.store.create(folder=str(repo), mode="accept_edits")
    s.config.modes["allowlist"] = ["codex_cli:*"]

    async def go():
        ctx = ToolContext(app=s, session=sess, run_id=f"main:{sess['id']}")
        out = await s.tools.run(ctx, "spawn_subagent", {"name": "fix", "tier": "codex.cli", "effort": "medium",
                                                         "instructions": "fix the bug", "run_in_background": False,
                                                         "job_type": "debug"})
        return out

    out = asyncio.run(go())
    assert "Done: wrote codex_out.txt" in out.text and "worktree" in out.text
    wt = s.worktrees_root(sess["id"])
    assert any((p / "codex_out.txt").exists() for p in wt.iterdir())
    assert not (repo / "codex_out.txt").exists()
    row = s.db.one("SELECT * FROM delegation_stats WHERE job_type='debug'")
    assert row["tier"] == "codex.cli" and row["success"] == 1 and row["model"] == "gpt-6.1-sol"


def test_agent_sdk_harness(env, tmp_path, monkeypatch):
    import claude_agent_sdk as sdk
    from claude_agent_sdk import AssistantMessage, ResultMessage, UserMessage
    from claude_agent_sdk import TextBlock as T, ToolResultBlock as R, ToolUseBlock as U

    c, s = env
    seen = {}

    async def fake_query(*, prompt, options=None, transport=None):
        async for m in prompt:
            seen["prompt"] = m["message"]["content"]
        seen["opts"] = options
        decision = await options.can_use_tool("Bash", {"command": "rm -rf build"}, None)
        seen["decision"] = decision.behavior
        yield AssistantMessage(content=[T(text="Checking."), U(id="tu1", name="Read", input={"file_path": "a.py"})],
                               model="claude-sonnet-5-5")
        yield UserMessage(content=[R(tool_use_id="tu1", content="x=1", is_error=False)])
        yield AssistantMessage(content=[T(text="All good.")], model="claude-sonnet-5-5")
        yield ResultMessage(subtype="success", duration_ms=1200, duration_api_ms=1000, is_error=False, num_turns=2,
                            session_id="sdk_sess_1", total_cost_usd=0.0123,
                            usage={"input_tokens": 900, "output_tokens": 80, "cache_read_input_tokens": 3000})

    monkeypatch.setattr(sdk, "query", fake_query)
    folder = tmp_path / "p"
    folder.mkdir()
    sid = c.post("/api/sessions", json={"folder": str(folder), "model": "claude-sonnet-5-5", "mode": "plan"},
                 headers=H).json()["id"]
    c.patch(f"/api/sessions/{sid}", json={"harness": "agent_sdk"}, headers=H)
    c.post(f"/api/sessions/{sid}/messages", json={"text": "check a.py"}, headers=H)
    wait_idle(c, sid)
    assert seen["prompt"] == "check a.py" and seen["opts"].permission_mode == "plan"
    assert seen["opts"].cwd == str(folder) and seen["decision"] == "deny"  # plan mode blocks Bash
    msgs = c.get(f"/api/sessions/{sid}/messages", headers=H).json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[2]["meta"]["tool_results"] and msgs[-1]["content"][0]["text"] == "All good."
    u = s.db.one("SELECT cost_usd, cache_read_tokens FROM usage_records WHERE session_id=?", [sid])
    assert u == {"cost_usd": 0.0123, "cache_read_tokens": 3000}
    assert c.get(f"/api/sessions/{sid}", headers=H).json()["settings"]["agent_sdk_session"] == "sdk_sess_1"
