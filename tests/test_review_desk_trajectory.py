"""Review Desk: trajectory parsing (drafted by GLM Flash, checked by hand)."""
from __future__ import annotations

import json

from gamedevworkstation.features.review_trajectory import claude_steps, codex_steps, steps


def _jl(*objs: dict) -> str:
    return "\n".join(json.dumps(o) for o in objs)


def _tool_result(tool_use_id: str, content, is_error: bool = False) -> dict:
    return {
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
            "is_error": is_error,
        }]},
    }


def test_tool_use_and_result_pairing():
    log = _jl(
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_1", "name": "Bash",
             "input": {"command": "ls -la\necho hi"}}]}},
        _tool_result("toolu_1", "file1.txt\nfile2.txt"),
    )
    st = claude_steps(log)
    assert len(st) == 1
    s = st[0]
    assert s["kind"] == "tool" and s["tool"] == "Bash"
    assert s["title"] == "ls -la"
    assert s["output"] == "file1.txt\nfile2.txt"
    assert s["is_error"] is False


def test_tool_result_with_image_list():
    log = _jl(
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_2", "name": "Read",
             "input": {"file_path": "/tmp/a.png"}}]}},
        _tool_result("toolu_2", [
            {"type": "text", "text": "here"},
            {"type": "image", "source": {}},
        ]),
    )
    st = claude_steps(log)
    assert st[0]["output"] == "here\n[image]"


def test_orphan_tool_result():
    log = _jl(_tool_result("toolu_x", "no pairing", is_error=True))
    st = claude_steps(log)
    assert len(st) == 1
    s = st[0]
    assert s["kind"] == "tool" and s["title"] == "Tool result"
    assert s["output"] == "no pairing" and s["is_error"] is True


def test_init_and_result_steps():
    log = _jl(
        {"type": "system", "subtype": "init", "model": "claude-opus-5-5",
         "cwd": "/x", "timestamp": "2025-01-01T00:00:00Z"},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": "done", "total_cost_usd": 0.0421, "num_turns": 12},
        {"type": "system", "subtype": "ui_status", "status": "busy"},
        {"type": "rate_limit_event"},
    )
    st = claude_steps(log)
    assert st[0]["title"] == "Started on claude-opus-5-5"
    assert st[0]["ts"] == "2025-01-01T00:00:00Z"
    assert st[-1]["kind"] == "system"
    assert st[-1]["title"] == "Finished: 12 turns, $0.0421"
    assert st[-1]["output"] == "done"
    assert len(st) == 2


def test_truncation():
    text = "x" * 5000
    log = _jl({"type": "assistant", "message": {"content": [
        {"type": "text", "text": text}]}})
    st = claude_steps(log, limit=100)
    out = st[0]["output"]
    assert out.startswith("x" * 100)
    assert out.endswith("(4900 more characters)")
    assert len(out.splitlines()[0]) <= 120


def test_non_json_lines_skipped():
    log = "not json\n{bad json\n" + _jl(
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "hello"}]}})
    st = claude_steps(log)
    assert len(st) == 1 and st[0]["kind"] == "text"


def test_claude_step_keys():
    log = _jl({"type": "system", "subtype": "init", "model": "m"})
    st = claude_steps(log)
    assert set(st[0]) == {"i", "kind", "tool", "title", "input", "output",
                          "is_error", "ts"}
    assert st[0]["i"] == 0


def test_codex_all_item_types():
    log = _jl(
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.completed", "item": {
            "type": "agent_message", "text": "answer\nline2"}},
        {"type": "item.completed", "item": {"type": "reasoning",
                                            "text": "hmm"}},
        {"type": "item.completed", "item": {
            "type": "command_execution", "command": "pwd\nls",
            "aggregated_output": "/home", "exit_code": 1}},
        {"type": "item.completed", "item": {
            "type": "file_change",
            "changes": [{"path": "a.py", "kind": "add"},
                        {"path": "b.py", "kind": "modify"}]}},
        {"type": "item.completed", "item": {
            "type": "mcp_tool_call", "server": "srv", "tool": "query",
            "arguments": {"q": 1}, "result": "ok"}},
        {"type": "turn.completed",
         "usage": {"input_tokens": 10, "output_tokens": 5}},
        {"type": "error", "message": "boom"},
    )
    st = codex_steps(log)
    kinds = [s["kind"] for s in st]
    assert kinds == ["text", "thinking", "tool", "tool", "tool",
                     "system", "system"]
    assert st[0]["output"] == "answer\nline2"
    assert st[2]["tool"] == "shell" and st[2]["input"] == "pwd\nls"
    assert st[2]["is_error"] is True and st[2]["output"] == "/home"
    assert st[3]["tool"] == "apply_patch" and st[3]["title"] == "a.py, b.py"
    assert st[4]["tool"] == "srv.query"
    assert st[5]["title"] == "Turn finished: 10 in, 5 out"
    assert st[6]["is_error"] is True


def test_format_detection():
    codex = _jl({"type": "thread.started"},
                {"type": "turn.completed", "usage": {"input_tokens": 1,
                                                     "output_tokens": 2}})
    claude = _jl({"type": "system", "subtype": "init", "model": "m"})
    assert steps(codex)[0]["kind"] == "system"
    assert steps(claude)[0]["title"] == "Started on m"
    assert len(steps(claude)) == 1


def test_tool_titles_are_relative_to_the_agents_folder():
    log = _jl({"type": "system", "subtype": "init", "model": "m", "cwd": "/private/var/folders/x/tree"},
              {"type": "assistant", "message": {"content": [
                  {"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/private/var/folders/x/tree/src/s.py"}},
                  {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "cd /var/folders/x/tree/src && ls"}}]}})
    assert [s["title"] for s in claude_steps(log)[1:]] == ["src/s.py", "cd src && ls"]
