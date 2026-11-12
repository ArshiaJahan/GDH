"""Claude Code sessions (harness claude_code) against a fake `claude` (tests/fixtures/fake_claude.py).

The backend runs for real (uvicorn on a free 127.0.0.1 port) because the fake CLI calls
GameDevWorkstation's MCP server over HTTP, as the real CLI does. Nothing here runs the real `claude`
or touches ~/.claude, the Keychain or the real data dir (conftest isolates GDW_HOME; HOME is a
temp folder too)."""
import asyncio
import errno
import json
import os
import signal
import socket
import stat
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import uvicorn

from gamedevworkstation.app import AppState
from gamedevworkstation.config import data_dir
from gamedevworkstation.core.types import Message, Usage
from gamedevworkstation.features import claude_code as ccm
from gamedevworkstation.features.claude_cli import LOGIN_HINT, child_env
from gamedevworkstation.server import create_app

FAKE = Path(__file__).parent / "fixtures" / "fake_claude.py"
H = {"Authorization": "Bearer t"}
LEAKY = {"ANTHROPIC_API_KEY": "sk-ant-must-not-leak", "ANTHROPIC_AUTH_TOKEN": "tok-must-not-leak",
         "ANTHROPIC_BASE_URL": "https://proxy.invalid", "ANTHROPIC_API_KEY_WORK": "sk-ant-profile",
         "CLAUDE_CONFIG_DIR": "/nonexistent/claude-config", "CLAUDE_CODE_USE_BEDROCK": "1",
         "CLAUDE_CODE_USE_VERTEX": "1", "CLAUDE_CODE_OAUTH_TOKEN": "oauth-must-not-leak",
         "OPENAI_API_KEY": "sk-openai-must-not-leak", "GDW_KEY_ANTHROPIC_WORK": "private",
         "GDW_KEY_OPENAI_X": "private", "GDW_TOKEN": "private", "FOO_SECRET": "private"}


def _free_port() -> int:
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


class Live:
    def __init__(self, tmp: Path, exe: Path, log: Path):
        self.tmp, self.exe, self.log = tmp, exe, log
        self.db = tmp / "cc.db"
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.S: AppState | None = None
        self.c: httpx.Client | None = None

    def start(self) -> "Live":
        S = AppState(db_path=self.db)
        S.config.claude_code["cli_path"] = str(self.exe)
        port = _free_port()
        S.listen_port = port
        app = create_app("t", S)
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                                    lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                break
            time.sleep(0.02)
        self.S, self.port = S, port
        self.c = httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=H, timeout=30)
        return self

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
            self.thread.join(15)  # type: ignore[union-attr]
        if self.c:
            self.c.close()

    # ------------------------------------------------------------ helpers

    def session(self, folder: Path, mode: str = "ask", **extra) -> str:
        r = self.c.post("/api/sessions", json={"folder": str(folder), "mode": mode, "harness": "claude_code",
                                               "model": "claude-sonnet-5-5", **extra})
        assert r.status_code == 200, r.text
        assert r.json()["harness"] == "claude_code"
        return r.json()["id"]

    def send(self, sid: str, text: str) -> None:
        r = self.c.post(f"/api/sessions/{sid}/messages", json={"text": text})
        assert r.status_code == 200, r.text

    def get(self, sid: str) -> dict:
        return self.c.get(f"/api/sessions/{sid}").json()

    def wait_idle(self, sid: str, timeout: float = 30) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if not self.get(sid)["running"]:
                return
            time.sleep(0.05)
        raise TimeoutError("session still running")

    def msgs(self, sid: str) -> list[dict]:
        return self.c.get(f"/api/sessions/{sid}/messages").json()

    def entries(self) -> list[dict]:
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def starts(self) -> list[dict]:
        return [e for e in self.entries() if "argv" in e]

    def events(self, kind: str) -> list[dict]:
        return [e for e in self.entries() if e.get("event") == kind]

    def wait_for(self, fn, timeout: float = 20):
        end = time.time() + timeout
        while time.time() < end:
            if v := fn():
                return v
            time.sleep(0.05)
        raise TimeoutError

    def pending(self, sid: str) -> list[dict]:
        return self.c.get("/api/approvals", params={"session_id": sid}).json()


@pytest.fixture
def live(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "claude"
    exe.write_text(f"#!{sys.executable}\n" + FAKE.read_text())
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "claude.log"
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home-dir"))  # nothing may reach the real ~/.claude
    home = tmp_path / "home-dir"
    home.mkdir()
    (home / "fake_claude.json").write_text(json.dumps({"log": str(log), "state": str(tmp_path / "state")}))
    for k, v in LEAKY.items():
        monkeypatch.setenv(k, v)
    lv = Live(tmp_path, exe, log).start()
    yield lv
    lv.stop()


def _opt(argv: list[str], name: str) -> str | None:
    for i, a in enumerate(argv):
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
        if a == name:
            return argv[i + 1]
    return None


def _project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    p.mkdir(exist_ok=True)
    return p


# ---------------------------------------------------------------- the turn


def test_turn_flags_env_and_event_mapping(live, tmp_path):
    folder = _project(tmp_path)
    sid = live.session(folder)
    live.send(sid, "hello")
    live.wait_idle(sid)
    msgs = live.msgs(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    reply = msgs[-1]
    assert reply["content"][0]["text"] == "Hello from fake claude (turn 1)."
    assert reply["meta"]["harness"] == "claude_code" and reply["meta"]["billing"] == "subscription"
    # The streamed message (message.started + deltas) and the stored one share an id.
    started = live.S.db.all("SELECT data FROM events WHERE session_id=? AND type='message.started'", [sid])
    assert reply["id"] in [json.loads(r["data"])["id"] for r in started]

    (start,) = live.starts()
    argv, env = start["argv"], start["env"]
    for flag in ("-p", "--verbose", "--include-partial-messages", "--strict-mcp-config"):
        assert flag in argv
    assert argv[argv.index("--input-format") + 1] == "stream-json"
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    s = live.get(sid)
    assert _opt(argv, "--session-id") == s["settings"]["claude_code_session"]
    assert _opt(argv, "--resume") is None
    assert _opt(argv, "--model") == "claude-sonnet-5-5"
    assert _opt(argv, "--permission-mode") == "manual"
    assert _opt(argv, "--permission-prompt-tool") == "mcp__gdw__approve"
    assert _opt(argv, "--setting-sources") is None and "--safe-mode" in argv
    assert _opt(argv, "--append-system-prompt").startswith("You are running inside GameDevWorkstation")
    assert _opt(argv, "--add-dir") == str(live.S.worktrees_root(sid))
    assert "--bare" not in argv and not any("dangerously" in a for a in argv)
    assert not any(a.split("=", 1)[-1] in ccm.FORBIDDEN_MODES for a in argv if a.startswith("--permission-mode"))
    assert start["cwd"] == str(folder.resolve())
    cfg = Path(_opt(argv, "--mcp-config"))
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    server = json.loads(cfg.read_text())["mcpServers"]["gdw"]
    assert server["type"] == "http" and server["url"] == f"http://127.0.0.1:{live.port}/mcp/gdw"
    assert server["headers"]["Authorization"].startswith("Bearer ") and "Bearer t" != server["headers"]["Authorization"]
    # Subscription auth only: no key, token, base URL, cloud switch or config dir reaches the CLI.
    for k in LEAKY:
        assert k not in env, k
    assert env["MCP_TOOL_TIMEOUT"].isdigit()
    for e in live.entries():
        if "auth_status_env" in e:
            assert not any(k in e["auth_status_env"] for k in LEAKY)
    # The PreToolUse hook was registered through the control protocol before the first message.
    (init,) = [e for e in live.events("control_request") if e["subtype"] == "initialize"]
    assert init["request"]["hooks"]["PreToolUse"][0]["hookCallbackIds"] == [ccm.HOOK_ID]

    # A second turn goes to the same long-lived process.
    live.send(sid, "hello again")
    live.wait_idle(sid)
    assert live.msgs(sid)[-1]["content"][0]["text"] == "Hello from fake claude (turn 2)."
    assert len(live.starts()) == 1
    jobs = live.c.get("/api/jobs", params={"session_id": sid}).json()
    assert [j["status"] for j in jobs if j["kind"] == "claude_code"] == ["done", "done"]
    info = live.c.get(f"/api/claude-code/sessions/{sid}").json()
    assert info["resume_command"] == f"claude --resume {s['settings']['claude_code_session']}"


def test_child_env_strips_every_auth_override():
    env = child_env({**LEAKY, "PATH": "/bin", "HOME": "/Users/x", "ANTHROPIC_MODEL": "x",
                     "ANTHROPIC_VERTEX_PROJECT_ID": "p", "CLAUDE_CODE_USE_FOUNDRY": "1",
                     "CLAUDE_CODE_SKIP_BEDROCK_AUTH": "1", "AWS_BEARER_TOKEN_BEDROCK": "b", "CLAUDECODE": "1"})
    assert set(env) == {"PATH", "HOME", "MCP_TOOL_TIMEOUT"}


def test_never_forbidden_modes(tmp_path, monkeypatch):
    base = dict(session_id="00000000-0000-0000-0000-000000000000", resume=None, model="m", effort="high",
                mcp_config=tmp_path / "m.json", add_dirs=[], system_prompt=None, setting_sources="",
                strict_mcp=True)
    for mode in ("ask", "accept_edits", "plan", "bogus"):
        argv = ccm.build_argv("claude", mode=mode, **base)
        pm = _opt(argv, "--permission-mode")
        assert pm in ("manual", "acceptEdits", "plan") and pm not in ccm.FORBIDDEN_MODES
        assert not any(f in argv for f in ccm.FORBIDDEN_FLAGS)
    assert set(ccm.CLI_MODE.values()).isdisjoint(ccm.FORBIDDEN_MODES)
    assert {"bypassPermissions", "dontAsk", "auto"} <= ccm.FORBIDDEN_MODES
    for bad in ccm.FORBIDDEN_MODES:  # even if the mapping were changed, the builder refuses
        monkeypatch.setitem(ccm.CLI_MODE, "ask", bad)
        with pytest.raises(ValueError):
            ccm.build_argv("claude", mode="ask", **base)
    assert _opt(ccm.build_argv("claude", mode="plan", **{**base, "effort": "none"}), "--effort") is None


# ----------------------------------------------------- usage and limits


def test_usage_is_subscription_and_not_counted(live, tmp_path):
    S = live.S
    S.config.limits["global_daily_usd"] = 0.005  # below one turn's estimate
    S.config.limits["session_usd"] = 0.005
    sid = live.session(_project(tmp_path))
    live.send(sid, "hello")
    live.wait_idle(sid)
    live.send(sid, "hello")
    live.wait_idle(sid)
    assert live.msgs(sid)[-1]["content"][0]["text"] == "Hello from fake claude (turn 2)."  # never paused
    rows = S.db.all("SELECT * FROM usage_records WHERE session_id=? ORDER BY ts", [sid])
    assert len(rows) == 2
    for r in rows:  # per-turn deltas of the CLI's cumulative totals
        assert (r["provider"], r["billing"], r["role"]) == ("anthropic", "subscription", "main")
        assert (r["input_tokens"], r["output_tokens"]) == (1000, 800)
        assert r["cost_usd"] == pytest.approx(0.01)
    assert S.usage.spent_today() == 0 and S.usage.spent_session(sid) == 0
    S.usage.check(sid)  # no BudgetExceeded
    assert S.usage.headroom(sid) == pytest.approx(0.005)
    models = live.c.get("/api/usage/models").json()
    (card,) = [m for m in models if m["billing"] == "subscription"]
    assert card["display_name"].startswith("Claude subscription (estimated)") and card["cost"] == pytest.approx(0.02)
    sav = live.c.get("/api/usage/savings").json()
    assert sav["actual"] == 0 and sav["subscription_estimated"] == pytest.approx(0.02)
    per = live.c.get(f"/api/usage/session/{sid}").json()
    assert per["total_cost"] == 0 and per["subscription_estimated"] == pytest.approx(0.02)


# ------------------------------------------------------------ lifecycle


def test_resume_after_restart_and_after_the_process_died(live, tmp_path):
    folder = _project(tmp_path)
    sid = live.session(folder)
    live.send(sid, "hello")
    live.wait_idle(sid)
    first = live.get(sid)["settings"]["claude_code_session"]
    live.stop()  # the app quits: its claude process goes with it
    live.start()  # same database
    live.send(sid, "hello after restart")
    live.wait_idle(sid)
    second = live.starts()[-1]["argv"]
    assert _opt(second, "--resume") == first and _opt(second, "--session-id") is None
    assert _opt(second, "--mcp-config") and _opt(second, "--add-dir")  # not restored on resume: passed again
    assert live.msgs(sid)[-1]["content"][0]["text"] == "Hello from fake claude (turn 2)."
    # The process exits between turns: the next turn resumes it.
    live.send(sid, "hello then exit")
    live.wait_idle(sid)
    live.wait_for(lambda: sid not in live.S.extensions["claude_code"].procs)
    live.send(sid, "hello")
    live.wait_idle(sid)
    assert len(live.starts()) == 3 and _opt(live.starts()[-1]["argv"], "--resume") == first
    assert live.msgs(sid)[-1]["content"][0]["text"] == "Hello from fake claude (turn 4)."


def test_failed_resume_starts_fresh_with_a_recap(live, tmp_path):
    sid = live.session(_project(tmp_path))
    live.send(sid, "hello")
    live.wait_idle(sid)
    old = live.get(sid)["settings"]["claude_code_session"]
    live.stop()
    (tmp_path / "state" / f"{old}.json").unlink()  # the CLI's transcript is gone (30-day cleanup)
    live.start()
    live.send(sid, "hello")
    live.wait_idle(sid)
    a, b = live.starts()[-2:]
    assert _opt(a["argv"], "--resume") == old
    new = _opt(b["argv"], "--session-id")
    assert new and new != old and live.get(sid)["settings"]["claude_code_session"] == new
    assert live.events("user")[-1]["text"].startswith("Earlier in this conversation:")
    assert live.msgs(sid)[-1]["content"][0]["text"] == "Hello from fake claude (turn 1)."


def test_cancel_interrupts_and_keeps_the_process(live, tmp_path):
    sid = live.session(_project(tmp_path))
    live.send(sid, "slow")
    live.wait_for(lambda: live.events("user"))
    assert live.c.post(f"/api/sessions/{sid}/stop").json()["stopped"]
    live.wait_idle(sid)
    live.wait_for(lambda: live.events("interrupted"))
    assert live.events("interrupted")[-1]["how"] == "yes"
    assert any(e["subtype"] == "interrupt" for e in live.events("control_request"))
    jobs = [j for j in live.c.get("/api/jobs", params={"session_id": sid}).json() if j["kind"] == "claude_code"]
    assert jobs[0]["status"] == "cancelled"
    assert not [m for m in live.msgs(sid) if m["meta"].get("error_kind") == "harness"]  # a Stop is no error
    live.send(sid, "hello")
    live.wait_idle(sid)
    assert live.msgs(sid)[-1]["content"][0]["text"].startswith("Hello from fake claude")
    assert len(live.starts()) == 1  # the same process answered


def test_session_delete_kills_the_process(live, tmp_path):
    sid = live.session(_project(tmp_path))
    live.send(sid, "hello")
    live.wait_idle(sid)
    cc = live.S.extensions["claude_code"]
    proc = cc.procs[sid]
    assert live.c.delete(f"/api/sessions/{sid}").status_code == 200
    live.wait_for(lambda: proc.proc.returncode is not None)
    assert sid not in cc.procs and not proc.mcp_file.exists()


# --------------------------------------------------------- GDW tools via MCP


def test_gdw_tool_over_mcp(live, tmp_path):
    sid = live.session(_project(tmp_path))
    live.send(sid, "tool")
    live.wait_idle(sid)
    names = live.events("tools_list")[-1]["names"]
    assert {"task_boards", "task_search", "list_items", "read_skill", "approve"} <= set(names)
    assert not {"run_command", "read_file", "write_file", "spawn_subagent", "web_search", "web_fetch"} & set(names)
    out = live.events("tool_result")[-1]["result"]["result"]
    assert not out["isError"] and "Game" in out["content"][0]["text"]
    msgs = live.msgs(sid)
    uses = [b for m in msgs for b in m["content"] if b["type"] == "tool_use"]
    assert uses and uses[0]["name"] == "mcp__gdw__task_boards"
    results = [m for m in msgs if m["meta"].get("tool_results")]
    assert results and results[0]["content"][0]["tool_use_id"] == "toolu_1"
    assert msgs[-1]["content"][0]["text"] == "Boards listed."


def test_mcp_endpoint_security(live, tmp_path):
    sid = live.session(_project(tmp_path))
    tok = live.S.extensions["claude_code"].mcp.issue(sid)
    url = f"http://127.0.0.1:{live.port}/mcp/gdw"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    with httpx.Client(timeout=10) as h:
        assert h.post(url, json=body).status_code == 401
        assert h.post(url, json=body, headers={"Authorization": "Bearer t"}).status_code == 401  # not the app token
        assert h.post(url, json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
        good = {"Authorization": f"Bearer {tok}"}
        assert h.post(url, json=body, headers={**good, "Host": "evil.example:80"}).status_code == 403
        assert h.post(url, json=body, headers={**good, "Origin": "https://evil.example"}).status_code == 403
        assert h.get(url, headers=good).status_code == 405
        r = h.post(url, json=body, headers=good)
        assert r.status_code == 200 and any(t["name"] == "approve" for t in r.json()["result"]["tools"])
        assert h.post(url, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=good).status_code == 202
        live.S.extensions["claude_code"].mcp.revoke(sid)
        assert h.post(url, json=body, headers=good).status_code == 401


def test_gdw_tools_keep_plan_mode(live, tmp_path):
    """A GDW tool called through MCP runs with the session's ToolContext: Plan only mode refuses writes."""
    sid = live.session(_project(tmp_path), mode="plan")
    tok = live.S.extensions["claude_code"].mcp.issue(sid)
    call = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "task_create", "arguments": {"title": "From Claude Code"}}}
    r = httpx.post(f"http://127.0.0.1:{live.port}/mcp/gdw", json=call, headers={"Authorization": f"Bearer {tok}"})
    res = r.json()["result"]
    assert res["isError"] and "Plan only mode" in res["content"][0]["text"]
    assert not live.S.db.all("SELECT 1 FROM board_tasks WHERE title='From Claude Code'")
    call["params"]["name"] = "run_command"  # not offered: Claude Code has its own shell
    res = httpx.post(f"http://127.0.0.1:{live.port}/mcp/gdw", json=call, headers={"Authorization": f"Bearer {tok}"}).json()
    assert res["result"]["isError"] and "not available" in res["result"]["content"][0]["text"]


def test_usage_billing_column_migrates(tmp_path):
    import sqlite3

    from gamedevworkstation.db import DB

    db = DB(tmp_path / "old.db")
    with sqlite3.connect(tmp_path / "old.db") as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(usage_records)")}
    assert "billing" in cols
    S = AppState(db_path=tmp_path / "old.db")
    from gamedevworkstation.core.types import Usage

    row = S.usage.record(provider="anthropic", model="m", usage=Usage(cost_usd=1.0))
    assert row["billing"] == "api" and S.usage.spent_today() == 1.0
    del db


def test_mcp_server_speaks_mcp(live, tmp_path):
    """The MCP SDK's own client can initialize, list and call tools on the server."""
    import asyncio

    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    sid = live.session(_project(tmp_path))
    tok = live.S.extensions["claude_code"].mcp.issue(sid)

    async def go():
        client = create_mcp_http_client(headers={"Authorization": f"Bearer {tok}"})
        async with streamable_http_client(f"http://127.0.0.1:{live.port}/mcp/gdw", http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                res = await session.call_tool("task_boards", {})
                return [t.name for t in tools], res

    names, res = asyncio.run(go())
    assert "task_boards" in names and "approve" in names
    assert not res.is_error and "Game" in res.content[0].text


# ------------------------------------------------------- approvals and modes


def _answer(live, sid, decision):
    (card,) = live.wait_for(lambda: live.pending(sid))
    live.c.post(f"/api/approvals/{card['id']}", json={"decision": decision})
    return card


def test_permission_prompt_shows_a_card_and_relays_the_decision(live, tmp_path):
    sid = live.session(_project(tmp_path))
    live.send(sid, "prompt")
    card = _answer(live, sid, "approve")
    assert card["kind"] == "command" and card["payload"]["command"] == "echo hi"
    live.wait_idle(sid)
    assert live.events("decision")[-1]["decision"] == {"behavior": "allow", "updatedInput": {"command": "echo hi"}}
    assert live.msgs(sid)[-1]["content"][0]["text"] == "Permission: allow"
    live.send(sid, "prompt again")
    _answer(live, sid, "deny")
    live.wait_idle(sid)
    d = live.events("decision")[-1]["decision"]
    assert d["behavior"] == "deny" and d["message"] == "The user declined."
    assert live.msgs(sid)[-1]["content"][0]["text"] == "Permission: deny"


def test_approve_tool_accepts_other_input_shapes(tmp_path):
    import asyncio

    S = AppState(db_path=tmp_path / "u.db")
    cc = ccm.ClaudeCode(S)
    folder = _project(tmp_path)
    sid = S.store.create(folder=str(folder), mode="plan")["id"]

    async def go():
        a = await cc.approve(sid, {"toolName": "Bash", "toolInput": {"command": "ls"}})
        b = await cc.approve(sid, {"request": {"tool_name": "Edit", "tool_input": {"file_path": "x", "old_string": "a"}}})
        c = await cc.approve(sid, {})
        d = await cc.approve(sid, {"tool_name": "mcp__gdw__task_boards", "input": {}})
        e = await cc.pre_tool_use(sid, {"tool_name": "mcp__gdw__approve", "tool_input": {}})
        f = await cc.pre_tool_use(sid, {"tool_name": "ExitPlanMode", "tool_input": {"plan": "p"}})
        g = await cc.pre_tool_use(sid, {"tool_name": "Read", "tool_input": {"file_path": "/etc/passwd"}})
        return a, b, c, d, e, f, g

    a, b, c, d, e, f, g = asyncio.run(go())
    assert a == {"behavior": "deny", "message": "Plan only mode: no commands."}
    assert b == {"behavior": "deny", "message": "Plan only mode: no edits."}
    assert c["behavior"] == "deny" and "Malformed" in c["message"]
    assert d == {"behavior": "allow", "updatedInput": {}}
    assert e["hookSpecificOutput"]["permissionDecision"] == "deny"  # the model can't call the prompt tool
    assert f == {}  # left to the CLI's plan flow and then the prompt tool (GDW's plan card)
    assert g["hookSpecificOutput"]["permissionDecision"] == "deny"  # outside the session folder


def test_plan_mode_is_respected(live, tmp_path):
    folder = _project(tmp_path)
    sid = live.session(folder, mode="plan")
    live.send(sid, "hook")
    live.wait_idle(sid)
    resp = live.events("hook")[-1]["response"]
    assert resp["subtype"] == "success"
    out = resp["response"]["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and out["permissionDecisionReason"] == "Plan only mode: no edits."
    assert _opt(live.starts()[-1]["argv"], "--permission-mode") == "plan"
    assert not live.pending(sid) and not (folder / "plan.txt").exists()
    # A permission prompt for a command in Plan: refused without a card.
    live.send(sid, "prompt")
    live.wait_idle(sid)
    assert live.events("decision")[-1]["decision"] == {"behavior": "deny", "message": "Plan only mode: no commands."}
    # Switching to Accept edits restarts the process (resumed) in acceptEdits; the hook then allows the Write.
    live.c.patch(f"/api/sessions/{sid}", json={"mode": "accept_edits"})
    live.send(sid, "hook")
    live.wait_idle(sid)
    last = live.starts()[-1]["argv"]
    assert _opt(last, "--permission-mode") == "acceptEdits" and _opt(last, "--resume")
    assert live.events("hook")[-1]["response"]["response"]["hookSpecificOutput"]["permissionDecision"] == "allow"


# ---------------------------------------------------------------- login


def test_not_logged_in_shows_the_login_card(live, tmp_path, monkeypatch):
    cfg_file = tmp_path / "home-dir" / "fake_claude.json"
    cfg = json.loads(cfg_file.read_text())
    cfg_file.write_text(json.dumps({**cfg, "auth": {"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"}}))
    live.S.extensions["claude_code"].probe.forget()
    st = live.c.get("/api/claude-code/status", params={"refresh": 1}).json()
    assert st["installed"] and not st["logged_in"] and st["version"] == "9.9.9 (Claude Code)"
    assert st["auth"]["authMethod"] == "none"
    sid = live.session(_project(tmp_path))
    live.send(sid, "hello")
    live.wait_idle(sid)
    last = live.msgs(sid)[-1]
    assert last["meta"]["error_kind"] == "claude_login" and last["content"][0]["text"] == LOGIN_HINT
    assert "claude auth login" in LOGIN_HINT and not live.starts()  # nothing was started
    # Logged in now: Retry answers the message.
    cfg_file.write_text(json.dumps(cfg))
    assert live.c.post(f"/api/claude-code/sessions/{sid}/retry").json()["started"]
    live.wait_idle(sid)
    assert live.msgs(sid)[-1]["content"][0]["text"] == "Hello from fake claude (turn 1)."


def test_login_error_during_a_turn_shows_the_card(live, tmp_path):
    sid = live.session(_project(tmp_path))
    live.send(sid, "nologin")
    live.wait_idle(sid)
    assert live.msgs(sid)[-1]["meta"]["error_kind"] == "claude_login"


def test_harness_choice_needs_the_cli(live, tmp_path):
    live.S.config.claude_code["cli_path"] = str(tmp_path / "missing" / "claude")
    live.S.extensions["claude_code"].probe.forget()
    r = live.c.post("/api/sessions", json={"harness": "claude_code"})
    assert r.status_code == 400 and "claude" in r.json()["detail"]
    assert live.c.post("/api/sessions", json={"harness": "nope"}).status_code == 400
    env = live.c.get("/api/environment").json()
    assert env["harnesses"]["claude_code"] is False and env["claude_code"]["installed"] is False


def test_settings_section(live):
    r = live.c.patch("/api/settings", json={"claude_code": {"setting_sources": "user,project", "load_user_mcp": True}})
    assert r.status_code == 200 and r.json()["claude_code"]["setting_sources"] == "user,project"
    assert live.c.patch("/api/settings", json={"claude_code": {"setting_sources": "user,evil"}}).status_code == 400
    st = live.c.get("/api/claude-code/status").json()
    assert st["settings"]["load_user_mcp"] is True and st["settings"]["setting_sources"] == "user,project"


# ------------------------------------------------ review regressions (no listening socket required)

@pytest.fixture
async def rig(tmp_path, monkeypatch):
    """Real process runner + fake CLI, isolated HOME and data dir, with no HTTP tool calls."""
    home = tmp_path / "cli-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    state = tmp_path / "state"
    state.mkdir()
    log = tmp_path / "fake.log"
    config_file = home / "fake_claude.json"
    config = {"log": str(log), "state": str(state)}

    def configure(**changes):
        config.update(changes)
        config_file.write_text(json.dumps(config))

    configure()
    exe = tmp_path / "fake-claude"
    exe.write_text(f"#!{sys.executable}\n" + FAKE.read_text())
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    app = AppState(db_path=tmp_path / "regressions.db")
    app.config.claude_code["cli_path"] = str(exe)
    app.listen_port = 8765  # Only written into MCP config; these tests never connect to it.
    cc = ccm.ClaudeCode(app)
    app.extensions["claude_code"] = cc
    s = app.store.create(folder=str(_project(tmp_path)), model="claude-sonnet-5-5", skills=[], effort="low")
    sid = s["id"]

    async def send(text="hello"):
        app.store.add_message(sid, Message.user(text))
        await asyncio.wait_for(cc.run_turn(app.store.get(sid)), 5)

    def entries():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    yield SimpleNamespace(app=app, cc=cc, sid=sid, configure=configure, send=send, entries=entries,
                          state=state, exe=exe, folder=Path(s["folder"]))
    await cc.aclose()


async def _eventually(predicate):
    async def wait():
        while not (result := predicate()):
            await asyncio.sleep(0.01)
        return result

    return await asyncio.wait_for(wait(), 3)


def test_env_allowlist_preserves_only_documented_names():
    keep = {k: "value" for k in ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
                               "TERM", "TMPDIR", "TZ", "SSH_AUTH_SOCK", "HTTP_PROXY", "https_proxy", "No_PrOxY",
                               "ALL_PROXY", "XDG_CONFIG_HOME", "__CF_USER_TEXT_ENCODING")}
    assert child_env({**keep, **LEAKY, "FAKE_CLAUDE_LOG": "not-allowed", "MCP_TOOL_TIMEOUT": "1"}) == {
        **keep, "MCP_TOOL_TIMEOUT": str(24 * 3600 * 1000)}


@pytest.mark.parametrize("sources", ["", "user", "project,local", "user,project,local", " user, project "])
def test_settings_isolation_flags(tmp_path, sources):
    argv = ccm.build_argv("fake", session_id="12345678-1234-1234-1234-123456789abc", resume=None,
                          model="m", effort=None, mode="ask", mcp_config=tmp_path / "m.json", add_dirs=[],
                          system_prompt=None, setting_sources=sources, strict_mcp=True)
    assert ("--safe-mode" in argv) == (not sources)
    assert _opt(argv, "--setting-sources") == (sources.replace(" ", "") if sources else None)
    assert "--strict-mcp-config" in argv and "--restricted" not in argv
    with pytest.raises(ValueError, match="setting sources"):
        ccm.build_argv("fake", session_id="12345678-1234-1234-1234-123456789abc", resume=None,
                       model="m", effort=None, mode="ask", mcp_config=tmp_path / "m.json", add_dirs=[],
                       system_prompt=None, setting_sources="user,evil", strict_mcp=False)


@pytest.mark.parametrize("init", [{"hooks": ["hook"]}, {"plugins": [{"name": "plugin"}]},
                                 {"mcp_servers": [{"name": "foreign", "status": "connected"}]},
                                 {"mcp_servers": ["foreign"]}])
@pytest.mark.parametrize("sources", ["", "user,project"])
async def test_init_customizations_fail_closed(rig, init, sources):
    rig.app.config.claude_code["setting_sources"] = sources
    rig.configure(init=init)
    await rig.send()
    await _eventually(lambda: rig.sid not in rig.cc.procs)
    errors = [m for m in rig.app.store.messages(rig.sid) if m.meta.get("error")]
    assert len(errors) == 1 and "settings isolation failed" in errors[0].text()
    assert not rig.cc.mcp._tokens
    assert not list((data_dir() / "claude_code" / rig.sid).glob("*.json"))
    assert not [m for m in rig.app.store.messages(rig.sid) if m.meta.get("harness")]


async def test_init_accepts_missing_fields_and_explicit_customization_opt_in(rig):
    rig.configure(init={"hooks": None, "plugins": None, "mcp_servers": None})
    await rig.send()
    p = rig.cc.procs[rig.sid]
    p._on_system({"subtype": "init"}, None)
    assert p.inited and not p.fatal_error
    await rig.cc.close_session(rig.sid)
    rig.app.config.claude_code.update(setting_sources="user,project", load_user_mcp=True)
    rig.configure(init={"mcp_servers": [{"name": "allowed"}]})
    await rig.send()
    assert not rig.cc.procs[rig.sid].fatal_error
    argv = [e["argv"] for e in rig.entries() if "argv" in e][-1]
    assert "--safe-mode" not in argv and "--strict-mcp-config" not in argv
    assert _opt(argv, "--setting-sources") == "user,project"


@pytest.mark.parametrize("failure", ["error", "timeout", "cancel"])
async def test_hook_initialization_failure_cleans_everything(rig, monkeypatch, failure):
    rig.configure(hook="timeout" if failure == "cancel" else failure)
    monkeypatch.setattr(ccm, "INIT_TIMEOUT_S", 0.1 if failure == "timeout" else 2)
    seen = []
    original = ccm.Proc.request

    async def capture(p, *args, **kwargs):
        seen.append(p)
        return await original(p, *args, **kwargs)

    monkeypatch.setattr(ccm.Proc, "request", capture)
    if failure == "cancel":
        task = asyncio.create_task(rig.send())
        await _eventually(lambda: seen)
        assert seen[0].starting and not seen[0].hook_ok
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await rig.send()
    (p,) = seen
    assert p.proc.returncode is not None and not p.hook_ok
    assert rig.sid not in rig.cc.procs and not p.mcp_file.exists()
    assert rig.cc.mcp.session_for(p.token) is None
    assert "hook registration failed" in rig.app.store.messages(rig.sid)[-1].text()
    assert not [e for e in rig.entries() if e.get("event") == "user"]


async def test_ensure_never_reuses_a_process_without_its_hook(rig, monkeypatch):
    await rig.send()
    old = rig.cc.procs[rig.sid]
    assert old.hook_ok and not old.starting
    old.hook_ok = False
    new = await rig.cc._ensure(rig.app.store.get(rig.sid), old.signature[1], "low", old.cc_session)
    assert new is not old and new.hook_ok and not new.starting
    assert old.proc.returncode is not None and not old.mcp_file.exists()
    assert rig.cc.mcp.session_for(new.token) == rig.sid


async def test_process_eof_revokes_token_unlinks_config_and_terminates_group(rig, monkeypatch):
    await rig.send()
    p = rig.cc.procs[rig.sid]
    actions = []
    killpg, release = os.killpg, ccm.CHILDREN.release

    def signal_group(pid, sig):
        if pid == p.proc.pid and sig == signal.SIGTERM:
            actions.append("term")
        return killpg(pid, sig)

    def release_group(pid):
        if pid == p.proc.pid:
            actions.append("release")
        return release(pid)

    monkeypatch.setattr(ccm.os, "killpg", signal_group)
    monkeypatch.setattr(ccm.CHILDREN, "release", release_group)
    await rig.send("hello exit")
    await asyncio.wait_for(p.reader, 3)
    assert actions == ["term", "release"]
    assert rig.sid not in rig.cc.procs and not p.mcp_file.exists()
    assert rig.cc.mcp.session_for(p.token) is None


@pytest.mark.parametrize("error", [ProcessLookupError, PermissionError])
async def test_eof_ignores_expected_process_group_signal_errors(rig, monkeypatch, error):
    await rig.send()
    p = rig.cc.procs[rig.sid]
    original = os.killpg

    def killpg(pid, sig):
        if pid == p.proc.pid and sig == signal.SIGTERM:
            raise error()
        return original(pid, sig)

    monkeypatch.setattr(ccm.os, "killpg", killpg)
    await rig.send("hello exit")
    await asyncio.wait_for(p.reader, 3)
    assert rig.sid not in rig.cc.procs and not p.mcp_file.exists()
    assert rig.cc.mcp.session_for(p.token) is None


async def test_old_process_cleanup_preserves_replacement_registration_and_token(rig):
    await rig.send()
    old = rig.cc.procs[rig.sid]
    token = rig.cc.mcp.issue(rig.sid)
    replacement = object()
    rig.cc.procs[rig.sid] = replacement
    try:
        await old.kill()
        assert rig.cc.procs[rig.sid] is replacement
        assert rig.cc.mcp.session_for(token) == rig.sid
        assert not old.mcp_file.exists()
    finally:
        rig.cc.procs.pop(rig.sid, None)
        rig.cc.mcp.revoke(rig.sid)


@pytest.mark.parametrize("failure", ["path", "write", "config", "prompt", "E2BIG"])
async def test_spawn_failures_revoke_and_unlink(rig, monkeypatch, failure):
    await rig.cc.probe.status()
    if failure == "path":
        def fail():
            raise OSError("bad data dir")
        monkeypatch.setattr(ccm, "data_dir", fail)
    elif failure == "write":
        original = os.open

        def fail(path, *args, **kwargs):
            if "claude_code" in str(path):
                raise PermissionError("can't write config")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(ccm.os, "open", fail)
    elif failure == "config":
        def fail(*_):
            raise ValueError("bad MCP config")
        monkeypatch.setattr(rig.cc.mcp, "config_json", fail)
    elif failure == "prompt":
        def fail(*_):
            raise ValueError("bad prompt")
        monkeypatch.setattr(rig.cc, "_system_prompt", fail)
    else:
        monkeypatch.setattr(ccm.asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError(errno.E2BIG, "too large")))
    await rig.send()
    assert not rig.cc.procs and not rig.cc.mcp._tokens
    assert not list((data_dir() / "claude_code" / rig.sid).glob("*.json"))
    error = rig.app.store.messages(rig.sid)[-1]
    assert error.meta["error"]
    if failure == "E2BIG":
        assert "command line too large (E2BIG)" in error.text()


async def test_session_purge_removes_only_its_resolved_folder(rig, tmp_path):
    from gamedevworkstation.features.sessions_mgmt import purge_session

    await rig.send()
    root = data_dir() / "claude_code"
    own = root / rig.sid
    (own / "leftover").write_text("test data")
    sibling = root / "other-session"
    sibling.mkdir()
    outside = data_dir() / "outside"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    await rig.cc.purge_session("../outside")
    await rig.cc.purge_session("escape")
    assert (outside / "keep").exists()
    await purge_session(rig.app, rig.sid)
    assert not own.exists() and sibling.exists() and (outside / "keep").exists()


async def test_make_room_protects_starting_and_active_turns(rig, monkeypatch):
    rig.app.config.claude_code["max_processes"] = 1
    procs = {
        "starting": SimpleNamespace(sid="starting", alive=True, starting=True, turn=None, last_used=0),
        "busy": SimpleNamespace(sid="busy", alive=True, starting=False, turn=object(), last_used=1),
        "idle": SimpleNamespace(sid="idle", alive=True, starting=False, turn=None, last_used=2),
    }
    rig.cc.procs.update(procs)
    closed = []

    async def close(sid, **_):
        closed.append(sid)
        rig.cc.procs.pop(sid)

    monkeypatch.setattr(rig.cc, "close_session", close)
    await rig.cc._make_room("new")
    assert closed == ["idle"] and set(rig.cc.procs) == {"starting", "busy"}
    rig.cc.procs.clear()


async def test_make_room_during_hook_startup_keeps_process(rig, monkeypatch):
    rig.app.config.claude_code["max_processes"] = 1
    entered, finish = asyncio.Event(), asyncio.Event()
    request = ccm.Proc.request

    async def pause(p, *args, **kwargs):
        entered.set()
        await finish.wait()
        return await request(p, *args, **kwargs)

    monkeypatch.setattr(ccm.Proc, "request", pause)
    task = asyncio.create_task(rig.send())
    await asyncio.wait_for(entered.wait(), 3)
    p = rig.cc.procs[rig.sid]
    assert p.starting
    await rig.cc._make_room("another-session")
    assert rig.cc.procs[rig.sid] is p and p.alive
    finish.set()
    await task
    assert not p.starting and p.hook_ok


@pytest.mark.parametrize("error", ["unknown option --something", "Not logged in", "temporary network error"])
@pytest.mark.parametrize("hook_enabled", [True, False])
async def test_pre_init_exit_preserves_resume_and_totals(rig, error, hook_enabled):
    rig.app.config.claude_code["pre_tool_hook"] = hook_enabled
    await rig.send()
    settings = rig.app.store.get(rig.sid)["settings"]
    await rig.cc.close_session(rig.sid)
    rig.configure(startup_error=error)
    await rig.send()
    saved = rig.app.store.get(rig.sid)["settings"]
    assert saved["claude_code_session"] == settings["claude_code_session"]
    assert saved["claude_code_totals"] == settings["claude_code_totals"]
    starts = [e for e in rig.entries() if "argv" in e]
    assert len(starts) == 2 and _opt(starts[-1]["argv"], "--resume") == settings["claude_code_session"]
    assert rig.app.store.messages(rig.sid)[-1].meta.get("error")


async def test_only_matching_resume_error_starts_fresh(rig):
    await rig.send()
    old = rig.app.store.get(rig.sid)["settings"]["claude_code_session"]
    await rig.cc.close_session(rig.sid)
    (rig.state / f"{old}.json").unlink()
    await rig.send()
    new = rig.app.store.get(rig.sid)["settings"]["claude_code_session"]
    assert old != new
    assert len([e for e in rig.entries() if "argv" in e]) == 3
    assert rig.app.store.messages(rig.sid)[-1].text() == "Hello from fake claude (turn 1)."


async def test_system_prompt_has_utf8_byte_cap_and_truncation_note(rig):
    rig.app.prompt_notes.append(lambda _: "Context: " + "😀" * 70000)
    (rig.folder / "CLAUDE.md").write_text("Project instructions " * 10000)
    prompt = rig.cc._system_prompt(rig.app.store.get(rig.sid), rig.folder)
    assert len(prompt.encode("utf-8")) <= 64 * 1024
    assert prompt.startswith(ccm.CONTEXT_HEAD) and prompt.endswith(ccm.PROMPT_TRUNCATED)
    await rig.send()
    argv = next(e["argv"] for e in rig.entries() if "argv" in e)
    assert len(_opt(argv, "--append-system-prompt").encode("utf-8")) <= 64 * 1024
    assert not any("append-system-prompt-file" in a for a in argv)


@pytest.mark.parametrize("location", ["stderr", "result"])
async def test_cli_diagnostics_redact_all_secret_shapes(rig, location):
    secret = "sk-test_1234567890-secret"
    text = f"Not logged in: $TOKEN Bearer arbitrary-secret {secret}"
    if location == "result":
        rig.configure(result_error=text)
    else:
        rig.configure(stderr=text)
    await rig.send()
    p = rig.cc.procs[rig.sid]
    if location == "stderr":
        await _eventually(lambda: p.stderr)
        assert p.token not in p.stderr and secret not in p.stderr and "arbitrary-secret" not in p.stderr
        rig.cc._error(rig.sid, p.stderr)
    stored = json.dumps([m.model_dump(mode="json") for m in rig.app.store.messages(rig.sid)])
    assert p.token not in stored and secret not in stored and "arbitrary-secret" not in stored
    assert "[REDACTED]" in stored


async def test_malformed_cli_events_cannot_leak_secrets_in_error_logs(rig, caplog):
    await rig.send()
    p = rig.cc.procs[rig.sid]
    # A malformed numeric total raises inside event handling; its exception must also be scrubbed.
    p.proc.stdout.feed_data((json.dumps({"type": "result", "total_cost_usd": p.token}) + "\n").encode())
    await _eventually(lambda: [r for r in caplog.records if "event result failed" in r.message])
    assert p.token not in caplog.text and "[REDACTED]" in caplog.text


async def test_api_login_usage_and_spend_limit_path(rig):
    from gamedevworkstation.usage import BudgetExceeded

    rig.configure(auth={"loggedIn": True, "authMethod": "api_key"})
    rig.app.config.limits.update(global_daily_usd=0.005, session_usd=0.005)
    await rig.send()
    row = rig.app.db.one("SELECT * FROM usage_records WHERE session_id=?", [rig.sid])
    assert row["billing"] == "api" and row["cost_usd"] == pytest.approx(0.01)
    reply = [m for m in rig.app.store.messages(rig.sid) if m.meta.get("harness")][-1]
    assert reply.meta["billing"] == "api"
    assert rig.app.usage.spent_session(rig.sid) == pytest.approx(0.01)
    with pytest.raises(BudgetExceeded):
        await rig.send()
    assert len([e for e in rig.entries() if e.get("event") == "user"]) == 1


async def test_api_login_already_over_limit_never_spawns(rig):
    from gamedevworkstation.usage import BudgetExceeded

    rig.configure(auth={"loggedIn": True, "authMethod": "api_key"})
    rig.app.config.limits["session_usd"] = 0.005
    rig.app.usage.record(provider="anthropic", model="m", session_id=rig.sid, usage=Usage(cost_usd=0.01))
    with pytest.raises(BudgetExceeded):
        await rig.send()
    assert not rig.cc.procs and not [e for e in rig.entries() if "argv" in e]


async def test_subscription_rows_excluded_from_campaigns_and_context(rig):
    from gamedevworkstation.features.campaigns import Campaigns
    from gamedevworkstation.features.session_routes import context_breakdown

    app, sid = rig.app, rig.sid
    mgr = Campaigns(app)
    app.db.insert("campaign_sessions", {"campaign_id": "test-campaign", "session_id": sid, "started_at": 0})
    baseline = context_breakdown(app, sid)
    tokens = max(baseline["total"], 10)
    app.usage.record(provider="anthropic", model=app.store.get(sid)["model"], session_id=sid,
                     usage=Usage(input_tokens=tokens, cost_usd=0.1), billing="api")
    before = context_breakdown(app, sid)
    app.usage.record(provider="anthropic", model=app.store.get(sid)["model"], session_id=sid,
                     usage=Usage(input_tokens=int(tokens * 1.5), cost_usd=99), billing="subscription")
    assert mgr.spend("test-campaign") == pytest.approx(0.1)
    assert mgr._last_request_tokens(sid) == tokens
    assert context_breakdown(app, sid) == before


async def test_subscription_rows_do_not_consume_subagent_job_budget(rig, monkeypatch):
    from gamedevworkstation.agent.tools import ToolContext
    from gamedevworkstation.features.subagents import SubagentManager

    app = rig.app
    app.config.limits.update(global_daily_usd=0, session_usd=0)
    app.config.delegation["job_budget_usd"] = 0.5
    mgr = SubagentManager(app)
    monkeypatch.setattr(mgr, "_run", AsyncMock())  # Test budget gate without a provider call.
    ctx = ToolContext(app=app, session=app.store.get(rig.sid), run_id=f"main:{rig.sid}")
    app.usage.record(provider="anthropic", model="m", session_id=rig.sid, usage=Usage(cost_usd=10), billing="subscription")
    sub = await mgr.spawn(ctx, {"tier": "claude.fast", "effort": "low", "instructions": "read only"})
    await sub.task
    app.usage.record(provider="anthropic", model="m", session_id=rig.sid, usage=Usage(cost_usd=0.6), billing="api")
    with pytest.raises(ValueError, match="job_budget_usd"):
        await mgr.spawn(ctx, {"tier": "claude.fast", "effort": "low", "instructions": "read only"})


@pytest.mark.parametrize("bad", ["abc", "$(echo unsafe)", "a" * 35, "g" * 36, 123, ["not-a-uuid"]])
async def test_invalid_cli_session_ids_are_dropped_from_events_and_info(rig, bad):
    await rig.send()
    p = rig.cc.procs[rig.sid]
    good = p.cc_session
    p._on_system({"subtype": "init", "session_id": bad}, None)
    rig.cc.record_usage(rig.sid, {"session_id": bad, "total_cost_usd": 0.02}, None)
    assert rig.app.store.get(rig.sid)["settings"]["claude_code_session"] == good
    # Legacy corrupt rows also cannot produce terminal commands.
    rig.app.db.update("sessions", "id", rig.sid, {"settings": json.dumps({"claude_code_session": bad})})
    assert rig.cc.info(rig.sid)["resume_command"] is None


async def test_session_patch_rejects_invalid_uuid_and_store_drops_it(rig):
    app = create_app("t", rig.app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=H) as client:
        r = await client.patch(f"/api/sessions/{rig.sid}", json={"settings": {"claude_code_session": "abc; echo x"}})
        assert r.status_code == 400
        good = "12345678-1234-1234-1234-123456789ABC"
        r = await client.patch(f"/api/sessions/{rig.sid}", json={"settings": {"claude_code_session": good}})
        assert r.status_code == 200 and r.json()["settings"]["claude_code_session"] == good
        info = await client.get(f"/api/claude-code/sessions/{rig.sid}")
        assert info.json()["resume_command"] == f"claude --resume {good}"
    rig.app.store.update(rig.sid, settings={"claude_code_session": "invalid"})
    assert rig.app.store.get(rig.sid)["settings"]["claude_code_session"] == good
    created = rig.app.store.create(claude_code_session="invalid")
    assert "claude_code_session" not in created["settings"]


async def test_usage_per_turn_tokens_with_increasing_cumulative_cost(rig):
    session_id = "12345678-1234-1234-1234-123456789abc"
    for cost in (0.01, 0.02):
        rig.cc.record_usage(rig.sid, {"session_id": session_id, "total_cost_usd": cost,
                                     "usage": {"input_tokens": 1000, "output_tokens": 800}}, None)

    rows = rig.app.db.all("SELECT * FROM usage_records WHERE session_id=? ORDER BY id", [rig.sid])
    assert len(rows) == 2
    for row in rows:
        assert (row["input_tokens"], row["output_tokens"]) == (1000, 800)
        assert row["cost_usd"] == pytest.approx(0.01)


@pytest.mark.parametrize("process_totals", [False, True])
async def test_usage_totals_track_conversation_and_pid_across_restart(rig, process_totals):
    rig.configure(process_totals=process_totals)
    await rig.send()
    await rig.send()
    old = rig.cc.procs[rig.sid]
    saved = rig.app.store.get(rig.sid)["settings"]
    assert saved["claude_code_totals"]["session_id"] == old.cc_session
    assert saved["claude_code_totals"]["pid"] == old.proc.pid
    await rig.cc.close_session(rig.sid)
    await rig.send()
    new = rig.cc.procs[rig.sid]
    assert new.proc.pid != old.proc.pid
    assert rig.app.store.get(rig.sid)["settings"]["claude_code_totals"]["pid"] == new.proc.pid
    rows = rig.app.db.all("SELECT * FROM usage_records WHERE session_id=? ORDER BY id", [rig.sid])
    assert len(rows) == 3
    for row in rows:
        assert row["cost_usd"] == pytest.approx(0.01)
        assert (row["input_tokens"], row["output_tokens"]) == (1000, 800)
    # A different conversation contributes its first total in full, even if larger than the old one.
    fresh = "12345678-1234-1234-1234-123456789abc"
    rig.cc.record_usage(rig.sid, {"session_id": fresh, "total_cost_usd": 0.1,
                                 "usage": {"input_tokens": 10000, "output_tokens": 8000}}, None)
    assert rig.app.db.all("SELECT cost_usd FROM usage_records WHERE session_id=? ORDER BY id", [rig.sid])[-1]["cost_usd"] == pytest.approx(0.1)


@pytest.mark.parametrize("text,is_login", [("website authentication failed", False), ("authentication_failed", False),
                                         ("claude auth login", True), ("Not logged in", True),
                                         ("Invalid API key", True), ("OAuth expired", True)])
async def test_login_text_only_matches_cli_auth_diagnostics(rig, text, is_login):
    rig.configure(result_error=text)
    await rig.send()
    assert (rig.app.store.messages(rig.sid)[-1].meta.get("error_kind") == "claude_login") == is_login


async def test_unknown_non_gdw_tool_in_plan_mode_shows_approval_card(rig):
    rig.app.store.update(rig.sid, mode="plan")
    task = asyncio.create_task(rig.cc.decide(rig.sid, "UnknownTool", {"x": 1}))
    (card,) = await _eventually(lambda: rig.app.approvals.pending(rig.sid))
    assert card["kind"] == "command" and "UnknownTool" in card["payload"]["command"]
    rig.app.approvals.resolve(card["id"], "deny")
    assert (await task)["behavior"] == "deny"


def test_claude_code_docs_describe_experimental_isolation_and_billing():
    root = Path(__file__).resolve().parents[1]
    for path in (root / "README.md", root / "docs" / "GUIDE.md"):
        text = " ".join(path.read_text().lower().split())
        for phrase in ("experimental: not yet verified against a live logged-in cli", "env allowlist",
                       "--safe-mode", "hooks, plugins and settings files are ignored", "token",
                       "revoked", "hook registration failure", "approval card", "billing='api'", "spend limits"):
            assert phrase in text, (path, phrase)


async def test_tool_results_are_redacted_before_storage_and_events(rig):
    await rig.send("toolsecret")
    p = rig.cc.procs[rig.sid]
    stored = json.dumps([m.model_dump(mode="json") for m in rig.app.store.messages(rig.sid)])
    events = json.dumps([dict(r) for r in rig.app.db.all("SELECT type, data FROM events WHERE session_id=?", [rig.sid])],
                        default=str)
    assert "tool.finished" in events and "[REDACTED]" in stored
    for blob in (stored, events):
        assert p.token not in blob and "Bearer xyz" not in blob and "sk-test_1234567890-secret" not in blob


async def test_purge_expired_removes_claude_code_folder(rig):
    await rig.send()
    folder = data_dir() / "claude_code" / rig.sid
    assert folder.is_dir()
    rig.app.store.trash(rig.sid)
    rig.app.db.execute("UPDATE sessions SET deleted_at=? WHERE id=?", [time.time() - 40 * 86400, rig.sid])
    from gamedevworkstation.features.sessions_mgmt import TrashJanitor

    assert await TrashJanitor(rig.app).run_once_async() == [rig.sid]
    assert not folder.exists() and rig.sid not in rig.cc.procs
