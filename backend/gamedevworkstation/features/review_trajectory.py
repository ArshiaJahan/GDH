"""Review Desk: turn an agent CLI log into trajectory steps (Claude Code stream-json or Codex JSONL)."""
from __future__ import annotations

import json
from typing import Any

_STEP_KEYS = ("i", "kind", "tool", "title", "input", "output", "is_error", "ts")


def _step(i: int, kind: str, title: str, *, tool: str | None = None,
          inp: str | None = None, out: str | None = None,
          is_error: bool = False, ts: str | None = None) -> dict:
    return {
        "i": i,
        "kind": kind,
        "tool": tool,
        "title": title,
        "input": inp,
        "output": out,
        "is_error": is_error,
        "ts": ts,
    }


def _truncate(s: str | None, limit: int) -> str | None:
    if s is None:
        return None
    if len(s) <= limit:
        return s
    cut = s[:limit]
    more = len(s) - limit
    return cut + f"\n… ({more} more characters)"


def _first_line(s: str, maxlen: int = 120) -> str:
    line = s.splitlines()[0] if s else ""
    if len(line) > maxlen:
        line = line[:maxlen]
    return line


def _tool_title(name: str, inp: dict) -> str:
    if name == "Bash":
        cmd = inp.get("command", "")
        return _first_line(str(cmd)) or name
    if name in ("Read", "Edit", "Write"):
        return str(inp.get("file_path", name))
    if name in ("Grep", "Glob"):
        return str(inp.get("pattern", name))
    return name


def _relative(title: str, cwds: list[str]) -> str:
    for cwd in cwds:  # macOS reports /var/... and /private/var/... for the same folder
        forms = {cwd, cwd.removeprefix("/private"), "/private" + cwd if cwd.startswith("/var/") else cwd}
        for c in sorted(forms, key=len, reverse=True):  # longest first, or /var/... eats into /private/var/...
            title = title.replace(c, "")
    return title


def _result_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "image":
                    parts.append("[image]")
                else:
                    parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def claude_steps(log: str, limit: int = 4000) -> list[dict]:
    steps: list[dict] = []
    cwds: list[str] = []  # the agent's working folder: titles show paths relative to it
    by_tool_id: dict[str, dict] = {}
    n = 0

    def add(**kw: Any) -> dict:
        nonlocal n
        kw["i"] = n
        step = _step(n, kw["kind"], kw["title"], tool=kw.get("tool"),
                     inp=kw.get("inp"), out=kw.get("out"),
                     is_error=kw.get("is_error", False), ts=kw.get("ts"))
        step["input"] = _truncate(step["input"], limit)
        step["output"] = _truncate(step["output"], limit)
        steps.append(step)
        n += 1
        return step

    for line in log.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue

        ts = obj.get("timestamp")
        etype = obj.get("type")

        if etype == "system":
            subtype = obj.get("subtype")
            if subtype == "init":
                if obj.get("cwd"):
                    cwds.append(str(obj["cwd"]).rstrip("/") + "/")
                model = obj.get("model", "unknown")
                add(kind="system", title=f"Started on {model}", ts=ts)
            elif subtype in ("ui_status", "thinking_tokens",
                             "hook_started", "hook_response"):
                continue
            else:
                add(kind="system", title=str(subtype or "system"), ts=ts)
        elif etype == "rate_limit_event":
            continue
        elif etype == "assistant":
            msg = obj.get("message", {})
            for block in msg.get("content", []):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = str(block.get("text", ""))
                    if text.strip():
                        add(kind="text", title=_first_line(text),
                            out=text, ts=ts)
                elif btype == "thinking":
                    text = str(block.get("thinking", ""))
                    if text.strip():  # print mode redacts thinking to a signature; an empty step is noise
                        add(kind="thinking", title="Thinking", out=text, ts=ts)
                elif btype == "tool_use":
                    name = str(block.get("name", "tool"))
                    inp = block.get("input", {}) or {}
                    compact = json.dumps(inp, ensure_ascii=False)
                    step = add(kind="tool", tool=name,
                               title=_relative(_tool_title(name, inp), cwds),
                               inp=compact, ts=ts)
                    tid = block.get("id")
                    if tid:
                        by_tool_id[tid] = step
        elif etype == "user":
            msg = obj.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, dict):
                content = [content]
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tid = block.get("tool_use_id")
                text = _result_text(block.get("content"))
                is_err = bool(block.get("is_error", False))
                target = by_tool_id.get(tid)
                if target is not None:
                    target["output"] = _truncate(text, limit)
                    target["is_error"] = is_err
                else:
                    add(kind="tool", title="Tool result", out=text,
                        is_error=is_err, ts=ts)
        elif etype == "result":
            is_err = bool(obj.get("is_error", False))
            turns = obj.get("num_turns", 0)
            cost = obj.get("total_cost_usd", 0.0)
            title = f"Failed: {turns} turns, ${cost:.4f}" if is_err else \
                f"Finished: {turns} turns, ${cost:.4f}"
            add(kind="system", title=title,
                out=str(obj.get("result", "")), is_error=is_err, ts=ts)

    return steps


def codex_steps(log: str, limit: int = 4000) -> list[dict]:
    steps: list[dict] = []
    n = 0

    def add(kind: str, title: str, *, tool: str | None = None,
            inp: str | None = None, out: str | None = None,
            is_error: bool = False, ts: str | None = None) -> dict:
        nonlocal n
        step = _step(n, kind, title, tool=tool, inp=inp, out=out,
                     is_error=is_error, ts=ts)
        step["input"] = _truncate(step["input"], limit)
        step["output"] = _truncate(step["output"], limit)
        steps.append(step)
        n += 1
        return step

    for line in log.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue

        ts = obj.get("timestamp")
        etype = obj.get("type", "")

        if etype in ("thread.started", "turn.started"):
            continue
        elif etype == "item.completed":
            item = obj.get("item", {}) or {}
            itype = item.get("type")
            if itype == "agent_message":
                text = str(item.get("text", ""))
                add("text", _first_line(text), out=text, ts=ts)
            elif itype == "reasoning":
                text = str(item.get("text", ""))
                add("thinking", "Thinking", out=text, ts=ts)
            elif itype == "command_execution":
                cmd = str(item.get("command", ""))
                out = str(item.get("aggregated_output", ""))
                code = item.get("exit_code")
                add("tool", _first_line(cmd), tool="shell", inp=cmd,
                    out=out, is_error=code not in (0, None), ts=ts)
            elif itype == "file_change":
                changes = item.get("changes", []) or []
                paths = ", ".join(str(c.get("path", "")) for c in changes)
                add("tool", paths, tool="apply_patch", ts=ts)
            elif itype == "mcp_tool_call":
                server = str(item.get("server", ""))
                tool = str(item.get("tool", ""))
                args = item.get("arguments", {}) or {}
                result = item.get("result", "")
                add("tool", f"{server}.{tool}",
                    tool=f"{server}.{tool}",
                    inp=json.dumps(args, ensure_ascii=False),
                    out=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                    is_error=bool(item.get("is_error", False)), ts=ts)
        elif etype == "turn.completed":
            usage = obj.get("usage", {}) or {}
            add("system",
                f"Turn finished: {usage.get('input_tokens', 0)} in, "
                f"{usage.get('output_tokens', 0)} out", ts=ts)
        elif etype == "error":
            add("system", _first_line(str(obj.get("message", "error"))),
                is_error=True, ts=ts)

    return steps


def steps(log: str, limit: int = 4000) -> list[dict]:
    for line in log.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            t = str(obj.get("type", ""))
            if t.startswith(("item.", "thread.", "turn.")):
                return codex_steps(log, limit)
    return claude_steps(log, limit)
