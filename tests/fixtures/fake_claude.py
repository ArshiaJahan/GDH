#!/usr/bin/env python3
"""A stand-in for the `claude` CLI in tests (never the real one, never ~/.claude).

- `claude --version`, `claude auth status` (JSON from the isolated HOME's fake_claude.json).
- `claude -p --input-format stream-json ...`: records argv and env to the configured log (one JSON line
  per start), keeps "transcripts" in the configured state directory (a resume of an unknown id fails like the
  real CLI), answers control requests (initialize, interrupt), and for each user line replays
  stream-json chosen by a keyword in the prompt:
    hello     init, partial text deltas, an assistant message, a result
    tool      a tool_use of mcp__gdw__task_boards, called for real over the GDW MCP server
    prompt    a permission prompt round trip: calls mcp__gdw__approve for Bash `echo hi`
    hook      a PreToolUse hook_callback control request for a Write
    slow      waits for an interrupt control request (or SIGINT), then an aborted result
    toolsecret a tool_result (string, nested text blocks, error) carrying the MCP token, a Bearer string and an sk- key
    nologin   a result saying it isn't logged in
    exit      answers, then exits (the process dies between turns)
  Decisions and MCP replies are appended to the log as {"event": ...} lines.
"""
import json
import os
import queue
import signal
import sys
import threading
import time
import urllib.request

from pathlib import Path

# Test controls live only under the fixture's isolated HOME, never in the child env allowlist.
settings_file = Path.home() / "fake_claude.json"
settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
LOG = settings.get("log")
STATE = settings.get("state")
args = sys.argv[1:]


def log(obj):
    if LOG:
        with open(LOG, "a") as f:
            f.write(json.dumps(obj) + "\n")


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


if args[:1] == ["--version"]:
    print("9.9.9 (Claude Code)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    log({"auth_status_env": {k: v for k, v in os.environ.items() if k.startswith(("ANTHROPIC", "CLAUDE"))}})
    print(json.dumps(settings.get("auth") or {"loggedIn": True, "authMethod": "claude.ai",
                                              "apiProvider": "firstParty"}))
    sys.exit(0)


def opt(name):
    for i, a in enumerate(args):
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return None


log({"argv": args, "env": dict(os.environ), "cwd": os.getcwd()})
if settings.get("startup_error"):
    sys.stderr.write(settings["startup_error"] + "\n")
    sys.exit(1)
resume = opt("--resume")
sid = resume or opt("--session-id")
state_file = os.path.join(STATE, f"{sid}.json") if STATE and sid else None
if resume and (not state_file or not os.path.exists(state_file)):
    sys.stderr.write(f"No conversation found with session ID: {resume}\n")
    sys.exit(1)
state = json.load(open(state_file)) if resume else {"turns": 0, "cost": 0.0, "in": 0, "out": 0}
if settings.get("process_totals"):
    state.update(cost=0.0, **{"in": 0, "out": 0})
mcp = json.load(open(opt("--mcp-config")))["mcpServers"]["gdw"]
model = opt("--model") or "claude-sonnet-5-5"


def save():
    if state_file:
        json.dump(state, open(state_file, "w"))


def rpc(method, params=None, rid=1):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(mcp["url"], data=body, method="POST",
                                 headers={**mcp.get("headers", {}), "Content-Type": "application/json",
                                          "Accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


lines: "queue.Queue[dict | None]" = queue.Queue()
interrupted = threading.Event()
signal.signal(signal.SIGINT, lambda *_: interrupted.set())


def reader():
    for raw in sys.stdin:
        raw = raw.strip()
        if raw:
            lines.put(json.loads(raw))
    lines.put(None)


threading.Thread(target=reader, daemon=True).start()
pending = []  # user messages that arrived while a control request was being waited on
responses = {}


def control_reply(msg):
    rid = msg["request_id"]
    sub = (msg.get("request") or {}).get("subtype")
    log({"event": "control_request", "subtype": sub, "request": msg.get("request")})
    if sub == "initialize":
        if settings.get("hook") == "timeout":
            return
        if settings.get("hook") == "error":
            emit({"type": "control_response", "response": {"subtype": "error", "request_id": rid,
                                                            "error": "hook registration refused"}})
            return
    if sub == "interrupt":
        interrupted.set()
    emit({"type": "control_response", "response": {"subtype": "success", "request_id": rid, "response": {}}})


def next_line(timeout=None):
    """The next stdin message that isn't a control request (those are answered here)."""
    while True:
        try:
            m = lines.get(timeout=timeout)
        except queue.Empty:
            return "timeout"
        if m is None:
            return None
        if m.get("type") == "control_request":
            control_reply(m)
            continue
        if m.get("type") == "control_response":
            responses[m["response"]["request_id"]] = m["response"]
            return "control_response"
        return m


def ask_host(request, rid):
    emit({"type": "control_request", "request_id": rid, "request": request})
    while rid not in responses:
        m = next_line(timeout=60)
        if m in (None, "timeout"):
            return None
        if m != "control_response":
            pending.append(m)
    return responses.pop(rid)


def result(text, *, is_error=False, subtype="success", **extra):
    state["turns"] += 1
    state["cost"] = round(state["cost"] + 0.01, 6)
    state["in"] += 1000  # 1000 in + 800 out at Sonnet 5.5's $2/$10 per million = $0.01 a turn
    state["out"] += 800
    save()
    emit({"type": "result", "subtype": subtype, "is_error": is_error, "result": text, "session_id": sid,
          "duration_ms": 50, "num_turns": state["turns"], "total_cost_usd": state["cost"],
          "usage": {"input_tokens": state["in"], "output_tokens": state["out"], "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0}, **extra})


def say(text, mid):
    emit({"type": "stream_event", "event": {"type": "message_start", "message": {"id": mid, "model": model}}})
    for part in (text[: len(text) // 2], text[len(text) // 2:]):
        emit({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                                "delta": {"type": "text_delta", "text": part}}})
    emit({"type": "assistant", "message": {"id": mid, "model": model, "role": "assistant",
                                           "content": [{"type": "text", "text": text}]}, "parent_tool_use_id": None})


def turn(prompt):
    emit({"type": "system", "subtype": "init", "session_id": sid, "model": model, "claude_code_version": "9.9.9",
          "mcp_servers": [{"name": "gdw", "status": "connected"}], "tools": [], **settings.get("init", {})})
    n = state["turns"] + 1
    if settings.get("result_error"):
        result(settings["result_error"].replace("$TOKEN", mcp["headers"]["Authorization"][7:]), is_error=True)
        return
    if settings.get("stderr"):
        sys.stderr.write(settings["stderr"].replace("$TOKEN", mcp["headers"]["Authorization"][7:]) + "\n")
        sys.stderr.flush()
    if "nologin" in prompt:
        result("Not logged in · Please run /login", is_error=True)
        return
    if "toolsecret" in prompt:
        tok = mcp["headers"]["Authorization"][7:]
        leak = f"token={tok} Authorization: Bearer xyz sk-test_1234567890-secret"
        for i, (content, err) in enumerate([(leak, False), ([{"type": "text", "text": leak}], True)]):
            emit({"type": "assistant", "message": {"id": f"m{n}a{i}", "model": model, "role": "assistant", "content": [
                {"type": "tool_use", "id": f"toolu_s{i}", "name": "Bash", "input": {}}]}})
            emit({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"toolu_s{i}", "content": content, "is_error": err}]}})
        say("Done.", f"m{n}b")
        result("Done.")
        return
    if "tool" in prompt:
        listed = rpc("tools/list")
        log({"event": "tools_list", "names": [t["name"] for t in listed["result"]["tools"]]})
        emit({"type": "assistant", "message": {"id": f"m{n}a", "model": model, "role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "mcp__gdw__task_boards", "input": {}}]}})
        out = rpc("tools/call", {"name": "task_boards", "arguments": {}}, rid=2)
        log({"event": "tool_result", "result": out})
        emit({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": out["result"]["content"],
             "is_error": out["result"]["isError"]}]}})
        say("Boards listed.", f"m{n}b")
        result("Boards listed.")
        return
    if "prompt" in prompt:
        out = rpc("tools/call", {"name": "approve", "arguments": {
            "tool_name": "Bash", "input": {"command": "echo hi"}, "tool_use_id": "toolu_b"}}, rid=3)
        decision = json.loads(out["result"]["content"][0]["text"])
        log({"event": "decision", "decision": decision})
        say(f"Permission: {decision['behavior']}", f"m{n}")
        result(f"Permission: {decision['behavior']}")
        return
    if "hook" in prompt:
        resp = ask_host({"subtype": "hook_callback", "callback_id": "gdw_pre_tool_use", "tool_use_id": "toolu_h",
                         "input": {"hook_event_name": "PreToolUse", "tool_name": "Write",
                                   "tool_input": {"file_path": "plan.txt", "content": "x"}}}, "cli_req_1")
        log({"event": "hook", "response": resp})
        say("Hook answered.", f"m{n}")
        result("Hook answered.")
        return
    if "slow" in prompt:
        emit({"type": "stream_event", "event": {"type": "message_start", "message": {"id": f"m{n}", "model": model}}})
        deadline = time.time() + 30
        while not interrupted.is_set() and time.time() < deadline:
            m = next_line(timeout=0.05)
            if m is None:
                return
            if m not in ("timeout", "control_response"):
                pending.append(m)
        log({"event": "interrupted", "how": "yes" if interrupted.is_set() else "timeout"})
        result("", is_error=True, subtype="error_during_execution", terminal_reason="aborted_streaming")
        interrupted.clear()
        return
    say(f"Hello from fake claude (turn {n}).", f"m{n}")
    result(f"Hello from fake claude (turn {n}).")
    if "exit" in prompt:
        sys.stdout.flush()
        os._exit(0)


while True:
    m = pending.pop(0) if pending else next_line()
    if m is None:
        break
    if m in ("timeout", "control_response"):
        continue
    if m.get("type") == "user":
        content = m["message"]["content"]
        text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content)
        log({"event": "user", "text": text})
        turn(text.split("Now: ")[-1])  # after a recap: the keyword is in the new message
