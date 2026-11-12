#!/usr/bin/env python3
"""A stand-in for the `claude` CLI in tests (never the real one, never ~/.claude).

Every line it writes is a redacted line captured from the real claude 2.1.308, logged in with a
claude.ai subscription and driven with GameDevWorkstation's own argv and env (tests/fixtures/
claude_stream/*.jsonl); only ids, text, tool inputs and the usage numbers are changed per turn.
The captures show the real behaviour this fake copies:
  - `auth status` → {"loggedIn": true, "authMethod": "claude.ai", ...} (auth_status.jsonl)
  - `initialize` (with hooks) → commands, models, account, hooks_applied: true (initialize.jsonl)
  - one `system/init` after every user line (init.jsonl: --setting-sources= variant)
  - a reply: status, message_start, block start/delta/stop, assistant, message_delta/stop,
    rate_limit_event, result (hello.jsonl). One `assistant` event per content block, with the same
    message id as message_start (tools.jsonl, plan_e2e.jsonl).
  - each tool call: a PreToolUse hook_callback control request when a hook is registered; the hook's
    `{}` leaves it to the CLI's own rules (ToolSearch, read-only `echo`, acceptEdits writes, the plan
    file in plan mode are accepted) and then to the --permission-prompt-tool over MCP (tools.jsonl,
    prompt_tool.jsonl, ask_user_question.jsonl, plan_e2e.jsonl). MCP tools are loaded with ToolSearch.
  - `result.usage` is the turn's tokens; `total_cost_usd` and modelUsage are conversation totals that
    survive --resume (prompt_tool.jsonl).
  - interrupt → {"still_queued": []}, an aborted_streaming result, the process stays (interrupt.jsonl);
    SIGINT → the same result, then the process exits 0 (sigint.jsonl).
  - --resume of an unknown id → "No conversation found with session ID: <id>" on stderr, a result with
    num_turns 0, exit 1, initialize never answered (resume_failed.jsonl).
  - at start it speaks MCP to the --mcp-config server like the real CLI (mcp_handshake.jsonl):
    server/discover, initialize, notifications/initialized, GET, tools/list. Simplification: init
    always reports the gdw server "connected" (the regression rig has no listening server).

Scenarios, chosen by a keyword in the prompt:
    hello      a reply ("Hello from fake claude (turn N).")
    tool       ToolSearch, then mcp__gdw__task_boards called for real over the GDW MCP server
    prompt     Bash `touch hi.txt`: the hook, else the permission prompt tool (mcp__gdw__approve)
    hook       a Write of plan.txt through the hook
    exitplan   Plan mode: the plan file Write, then ExitPlanMode {plan, planFilePath}
    askq       AskUserQuestion (Red/Blue)
    slow       waits for an interrupt control request (or SIGINT)
    toolsecret tool_results (string, nested text blocks, error) carrying the MCP token, a Bearer and an sk- key
    nologin    a result saying it isn't logged in
    exit       answers, then exits (the process dies between turns)
Controls live only in the isolated HOME's fake_claude.json. Decisions and MCP replies are appended
to the configured log as {"event": ...} lines.
"""
import copy
import json
import os
import queue
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

settings_file = Path.home() / "fake_claude.json"
settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
LOG = settings.get("log")
STATE = settings.get("state")
FIX = Path(settings.get("fixtures") or Path(__file__).parent / "claude_stream")
args = sys.argv[1:]


def log(obj):
    if LOG:
        with open(LOG, "a") as f:
            f.write(json.dumps(obj) + "\n")


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def rows(name):
    return [json.loads(x) for x in (FIX / name).read_text().splitlines() if x.strip()]


def outs(name):
    return [r["ev"] for r in rows(name) if r.get("dir") == "out"]


def find(evs, pred):
    return copy.deepcopy(next(e for e in evs if pred(e)))


def swap(obj, old, new):
    """Every string equal to (or containing) `old` gets `new` instead."""
    if isinstance(obj, dict):
        return {k: swap(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [swap(v, old, new) for v in obj]
    if isinstance(obj, str) and old and old in obj:
        return obj.replace(old, new)
    return obj


if args[:1] == ["--version"]:
    print("2.1.308 (Claude Code)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    log({"auth_status_env": {k: v for k, v in os.environ.items() if k.startswith(("ANTHROPIC", "CLAUDE"))}})
    print(json.dumps(settings.get("auth") or outs("auth_status.jsonl")[0]))
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

# ---------------------------------------------------------------- the captured lines
HELLO = outs("hello.jsonl")
TOOLS = outs("tools.jsonl")
PROMPT = outs("prompt_tool.jsonl")
PLAN = outs("plan_e2e.jsonl")
ASK = outs("ask_user_question.jsonl")
INIT = outs("init.jsonl")[0]  # --setting-sources= (GDW's default)
INITIALIZE = outs("initialize.jsonl")
RESULT = find(HELLO, lambda e: e.get("type") == "result")
ABORTED = find(outs("interrupt.jsonl"), lambda e: e.get("type") == "result")
REAL_SIDS = {e.get("session_id") for f in (HELLO, TOOLS, PROMPT, PLAN, ASK) for e in f if e.get("session_id")}
HOOK = find(TOOLS, lambda e: e.get("type") == "control_request")
TOOL_USE = find(TOOLS, lambda e: e.get("type") == "assistant" and e["message"]["content"][0]["type"] == "tool_use")
RESULT_OK = find(TOOLS, lambda e: e.get("type") == "user" and e["message"]["content"][0].get("is_error") is False)
HOOK_DENIED = find(TOOLS, lambda e: e.get("type") == "user" and "hook error" in json.dumps(e))
PROMPT_DENIED = find(PROMPT, lambda e: e.get("type") == "user" and "denied by the prompt tool" in json.dumps(e))
TOOL_REF = find(TOOLS, lambda e: e.get("type") == "user" and "tool_reference" in json.dumps(e))
PLAN_OK = find(PLAN, lambda e: e.get("type") == "user" and "approved your plan" in json.dumps(e))
MODE_STATUS = find(PLAN, lambda e: e.get("type") == "system" and "permissionMode" in e)
ASKED = find(ASK, lambda e: e.get("type") == "user" and "questions have been answered" in json.dumps(e))
RATE = find(HELLO, lambda e: e.get("type") == "rate_limit_event")

resume = opt("--resume")
sid = resume or opt("--session-id")
model = opt("--model") or "claude-sonnet-5-5"
cli_mode = {"manual": "default"}.get(opt("--permission-mode") or "default", opt("--permission-mode") or "default")
state_file = os.path.join(STATE, f"{sid}.json") if STATE and sid else None
if resume and (not state_file or not os.path.exists(state_file)):
    failed = outs("resume_failed.jsonl")
    sys.stderr.write(f"No conversation found with session ID: {resume}\n")
    sys.stderr.flush()
    emit(swap(find(failed, lambda e: e.get("type") == "result"), find(failed, lambda e: e.get("type") == "result")["session_id"], resume))
    sys.exit(1)
state = json.load(open(state_file)) if resume else {"turns": 0, "cost": 0.0, "in": 0, "out": 0}
mcp = json.load(open(opt("--mcp-config")))["mcpServers"]["gdw"]


def save():
    if state_file:
        json.dump(state, open(state_file, "w"))


def mine(ev):
    """A captured line with this run's conversation id and model."""
    for real in REAL_SIDS:
        ev = swap(ev, real, sid)
    return swap(ev, "claude-haiku-5-5", model)


def http(method, body=None, rid=None, timeout=60):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(mcp["url"], data=data, method=method, headers={
        **mcp.get("headers", {}), "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "User-Agent": "claude-code/2.1.308 (sdk-cli)", "mcp-protocol-version": "2025-11-25"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def rpc(method, params=None, rid=1):
    return http("POST", {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})[1]


def handshake():
    """What the real CLI sends the --mcp-config server at start (mcp_handshake.jsonl)."""
    seen = []
    try:
        for r in rows("mcp_handshake.jsonl"):
            if r.get("dir") != "mcp":
                continue
            body = r.get("body")
            if r["method"] == "GET":
                seen.append({"method": "GET", "status": http("GET", timeout=2)[0]})
            else:
                status, reply = http("POST", body, timeout=2)
                seen.append({"method": (body or {}).get("method"), "status": status, "reply": reply})
    except (OSError, ValueError) as e:  # no server (the regression rig): the real CLI would report "failed"
        seen.append({"error": type(e).__name__})
    log({"event": "mcp_handshake", "seen": seen})


handshake()
lines: "queue.Queue[dict | None]" = queue.Queue()
interrupted = threading.Event()
sigint = threading.Event()
signal.signal(signal.SIGINT, lambda *_: (sigint.set(), interrupted.set()))


def reader():
    for raw in sys.stdin:
        raw = raw.strip()
        if raw:
            lines.put(json.loads(raw))
    lines.put(None)


threading.Thread(target=reader, daemon=True).start()
pending = []  # user messages that arrived while a control request was being waited on
responses = {}
hooks = {"on": False}


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
        hooks["on"] = bool((msg["request"].get("hooks") or {}).get("PreToolUse"))
        resp = copy.deepcopy(find(INITIALIZE, lambda e: "commands" in json.dumps(e)))
        resp["response"]["request_id"] = rid
        resp["response"]["response"].update(current_permission_mode=cli_mode, pid=os.getpid(),
                                            hooks_applied=settings.get("hooks_applied", True))
        emit(resp)
        return
    if sub == "interrupt":
        interrupted.set()
        resp = copy.deepcopy(find(INITIALIZE, lambda e: "still_queued" in json.dumps(e)))
        resp["response"]["request_id"] = rid
        emit(resp)
        return
    emit({"type": "control_response", "response": {"subtype": "error", "request_id": rid,
                                                    "error": f"Unsupported control request subtype: {sub}"}})


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


def ask_host(request):
    rid = str(uuid.uuid4())
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
    state["cost"] = round(state["cost"] + 0.01, 6)  # 1000 in + 800 out at Sonnet 5.5's $2/$10 per million
    state["in"] += 1000
    state["out"] += 800
    save()
    ev = mine(copy.deepcopy(RESULT))
    ev.update(subtype=subtype, is_error=is_error, result=text, duration_ms=50, num_turns=state["turns"],
              total_cost_usd=state["cost"], **extra)
    ev["usage"].update(input_tokens=1000, output_tokens=800, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    ev["modelUsage"] = {model: {**next(iter(RESULT["modelUsage"].values())), "inputTokens": state["in"],
                                "outputTokens": state["out"], "cacheReadInputTokens": 0,
                                "cacheCreationInputTokens": 0, "costUSD": state["cost"], "canonicalModel": model}}
    emit(ev)


def aborted():
    ev = mine(copy.deepcopy(ABORTED))
    ev.update(total_cost_usd=state["cost"], duration_ms=50)
    emit(ev)


def say(text, mid):
    """hello.jsonl with this turn's text and message id."""
    real = find(HELLO, lambda e: e.get("type") == "assistant")
    real_mid, real_text = real["message"]["id"], real["message"]["content"][0]["text"]
    for ev in HELLO:
        if ev.get("type") in ("result", "rate_limit_event"):
            continue
        emit(swap(swap(mine(ev), real_mid, mid), real_text, text))
    emit(mine(RATE))


def tool_use(name, inp, tuid, mid):
    ev = mine(copy.deepcopy(TOOL_USE))
    block = {**ev["message"]["content"][0], "id": tuid, "name": name, "input": inp}
    ev["message"].update(id=mid, content=[block])
    ev.pop("wire_tool_inputs", None)
    emit({"type": "stream_event", "event": {"type": "message_start", "message": {"model": model, "id": mid, "type": "message",
          "role": "assistant", "content": []}}, "session_id": sid, "parent_tool_use_id": None})
    emit({"type": "stream_event", "event": {"type": "content_block_start", "index": 0, "content_block": {
        "type": "tool_use", "id": tuid, "name": name, "input": {}, "caller": {"type": "direct"}}}, "session_id": sid,
        "parent_tool_use_id": None})
    emit(ev)


def tool_result(template, tuid, content, is_error=None):
    ev = mine(copy.deepcopy(template))
    b = ev["message"]["content"][0]
    b.update(tool_use_id=tuid, content=content)
    if is_error is not None:
        b["is_error"] = is_error
    ev["tool_use_result"] = content if isinstance(content, str) else {"content": content}
    ev.pop("tool_result_meta", None)
    emit(ev)


AUTO = ("ToolSearch", "Read", "Glob", "Grep")


def permission(name, inp, tuid):
    """(allowed, input, how): the hook, the CLI's own rules, then the permission prompt tool."""
    if hooks["on"]:
        req = mine(copy.deepcopy(HOOK["request"]))
        req["input"].update(tool_name=name, tool_input=inp, tool_use_id=tuid, permission_mode=cli_mode, cwd=os.getcwd())
        req["tool_use_id"] = tuid
        resp = ask_host(req)
        log({"event": "hook", "tool": name, "response": resp})
        out = ((resp or {}).get("response") or {}).get("hookSpecificOutput") or {}
        if (resp or {}).get("subtype") != "success":
            tool_result(HOOK_DENIED, tuid, f"PreToolUse:{name} hook error: {(resp or {}).get('error')}", True)
            return False, inp, "hook_error"
        if out.get("permissionDecision") == "deny":
            tool_result(HOOK_DENIED, tuid, f"PreToolUse:{name} hook error: {out.get('permissionDecisionReason')}", True)
            return False, inp, "hook"
        if out.get("permissionDecision") == "allow":
            return True, out.get("updatedInput") or inp, "hook"
    plan_file = name == "Write" and str(inp.get("file_path", "")).startswith(str(Path.home() / ".claude" / "plans"))
    if name in AUTO or (name == "Bash" and str(inp.get("command", "")).startswith("echo ")) \
            or (cli_mode == "acceptEdits" and name in ("Write", "Edit")) or (cli_mode == "plan" and plan_file):
        return True, inp, "rules"
    out = rpc("tools/call", {"name": "approve", "arguments": {"tool_name": name, "input": inp, "tool_use_id": tuid},
                             "_meta": {"claudecode/toolUseId": tuid}}, rid=3)
    decision = json.loads(out["result"]["content"][0]["text"])
    log({"event": "decision", "tool": name, "decision": decision})
    if decision.get("behavior") == "allow":
        return True, decision.get("updatedInput") or inp, "prompt_tool"
    tool_result(PROMPT_DENIED, tuid, str(decision.get("message") or "Denied"), True)
    return False, inp, "prompt_tool"


def turn(prompt):
    init = mine(copy.deepcopy(INIT))
    init.update(cwd=os.getcwd(), permissionMode=cli_mode, claude_code_version="2.1.308",
                original_cwd=os.getcwd(), **settings.get("init", {}))
    emit(init)
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
            tool_use("Bash", {}, f"toolu_s{i}", f"msg_{n}a{i}")
            tool_result(RESULT_OK, f"toolu_s{i}", content, err)
        say("Done.", f"msg_{n}b")
        result("Done.")
        return
    if "tool" in prompt:
        listed = rpc("tools/list")
        log({"event": "tools_list", "names": [t["name"] for t in listed["result"]["tools"]]})
        tool_use("ToolSearch", {"query": "select:mcp__gdw__task_boards", "max_results": 1}, "toolu_ts", f"msg_{n}s")
        if permission("ToolSearch", {}, "toolu_ts")[0]:
            ref = copy.deepcopy(TOOL_REF["message"]["content"][0]["content"])
            tool_result(TOOL_REF, "toolu_ts", ref)
        tool_use("mcp__gdw__task_boards", {}, "toolu_1", f"msg_{n}a")
        ok, inp, _ = permission("mcp__gdw__task_boards", {}, "toolu_1")
        if ok:
            out = rpc("tools/call", {"name": "task_boards", "arguments": inp,
                                     "_meta": {"claudecode/toolUseId": "toolu_1", "progressToken": 2}}, rid=2)
            log({"event": "tool_result", "result": out})
            tool_result(RESULT_OK, "toolu_1", out["result"]["content"], out["result"]["isError"])
        say("Boards listed.", f"msg_{n}b")
        result("Boards listed.")
        return
    if "prompt" in prompt:
        inp = {"command": "touch hi.txt", "description": "Create hi.txt"}
        tool_use("Bash", inp, "toolu_b", f"msg_{n}a")
        ok, used, how = permission("Bash", inp, "toolu_b")
        if ok:
            log({"event": "ran", "input": used})
            tool_result(RESULT_OK, "toolu_b", "(Bash completed with no output)", False)
        say(f"Permission: {'allow' if ok else 'deny'} ({how})", f"msg_{n}")
        result(f"Permission: {'allow' if ok else 'deny'}")
        return
    if "hook" in prompt:
        inp = {"file_path": "plan.txt", "content": "x"}
        tool_use("Write", inp, "toolu_h", f"msg_{n}a")
        ok, _, _ = permission("Write", inp, "toolu_h")
        if ok:
            tool_result(RESULT_OK, "toolu_h", "File created successfully at: plan.txt", False)
        say("Hook answered.", f"msg_{n}")
        result("Hook answered.")
        return
    if "exitplan" in prompt:
        plan_text = "Create hello.txt containing hi.\n"
        plan_path = str(Path.home() / ".claude" / "plans" / "fake-plan.md")
        tool_use("Write", {"file_path": plan_path, "content": plan_text}, "toolu_pw", f"msg_{n}w")
        ok, _, how = permission("Write", {"file_path": plan_path, "content": plan_text}, "toolu_pw")
        log({"event": "plan_file", "allowed": ok, "how": how})
        if not ok:
            say("Plan file refused.", f"msg_{n}")
            result("Plan file refused.")
            return
        tool_result(RESULT_OK, "toolu_pw", f"File created successfully at: {plan_path}", False)
        inp = {"plan": plan_text, "planFilePath": plan_path}
        tool_use("ExitPlanMode", inp, "toolu_p", f"msg_{n}p")
        ok, _, how = permission("ExitPlanMode", inp, "toolu_p")
        if ok:
            emit(mine(MODE_STATUS))
            tool_result(PLAN_OK, "toolu_p", PLAN_OK["message"]["content"][0]["content"], None)
        say(f"Plan: {'allow' if ok else 'deny'} ({how})", f"msg_{n}")
        result(f"Plan: {'allow' if ok else 'deny'}")
        return
    if "askq" in prompt:
        q = {"question": "Which color?", "header": "Color", "multiSelect": False,
             "options": [{"label": "Red", "description": "Write red"}, {"label": "Blue", "description": "Write blue"}]}
        tool_use("AskUserQuestion", {"questions": [q]}, "toolu_q", f"msg_{n}q")
        ok, used, how = permission("AskUserQuestion", {"questions": [q]}, "toolu_q")
        answers = used.get("answers") or {}
        if ok:
            text = "Your questions have been answered: " + ", ".join(f'"{k}"="{v}"' for k, v in answers.items()) + \
                   ". You can now continue with these answers in mind."
            tool_result(ASKED, "toolu_q", text, None)
        log({"event": "answers", "allowed": ok, "answers": answers})
        say(f"Answers: {json.dumps(answers)}", f"msg_{n}")
        result(f"Answers: {json.dumps(answers)}")
        return
    if "slow" in prompt:
        emit({"type": "stream_event", "event": {"type": "message_start", "message": {"id": f"msg_{n}", "model": model}},
              "session_id": sid, "parent_tool_use_id": None})
        deadline = time.time() + 30
        while not interrupted.is_set() and time.time() < deadline:
            m = next_line(timeout=0.05)
            if m is None:
                return
            if m not in ("timeout", "control_response"):
                pending.append(m)
        log({"event": "interrupted", "how": ("sigint" if sigint.is_set() else "yes") if interrupted.is_set() else "timeout"})
        aborted()  # usage zero, totals unchanged (interrupt.jsonl)
        interrupted.clear()
        if sigint.is_set():  # SIGINT ends the process too (sigint.jsonl)
            sys.stdout.flush()
            os._exit(0)
        return
    say(f"Hello from fake claude (turn {n}).", f"msg_{n}")
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
