import json
from unittest.mock import AsyncMock, call

import pytest

from gamedevworkstation.app import AppState
from gamedevworkstation.core.types import Message
from gamedevworkstation.features import claude_code, harnesses
from gamedevworkstation.server import create_app


@pytest.fixture
def auto_session(tmp_path):
    app = AppState(db_path=tmp_path / "auto.db")
    folder = tmp_path / "project"
    folder.mkdir()
    session = app.store.create(folder=str(folder), mode="auto")
    return app, session, folder


def test_auto_mode_passes_cli_auto_but_never_bypass(tmp_path, monkeypatch):
    args = dict(session_id="00000000-0000-0000-0000-000000000000", resume=None, model="m", effort="high",
                mcp_config=tmp_path / "m.json", add_dirs=[], system_prompt=None, setting_sources="", strict_mcp=True)
    assert "--permission-mode=auto" in claude_code.build_argv("claude", mode="auto", **args)
    assert claude_code.FORBIDDEN_MODES == {"bypassPermissions", "dontAsk"}
    for forbidden in claude_code.FORBIDDEN_MODES:
        monkeypatch.setitem(claude_code.CLI_MODE, "auto", forbidden)
        with pytest.raises(ValueError, match=f"permission mode {forbidden} is never used"):
            claude_code.build_argv("claude", mode="auto", **args)


async def test_auto_gate_keeps_hard_checks_and_defers(auto_session, monkeypatch):
    app, session, folder = auto_session
    approvals = AsyncMock()
    monkeypatch.setattr(app.approvals, "ask", approvals)
    app.config.data_policy["sensitive_allowed"] = []
    app.items.add(kind="file", source="test", path=str(folder / "private.txt"), meta={"sensitive": True})
    target = folder / "notes.md"
    target.write_text("before", encoding="utf-8")
    proposed_edits = {}
    gate = harnesses.make_gate(app, lambda: session, folder, proposed_edits)

    assert "outside the session folder" in await gate("Write", {"file_path": "../outside.txt"}, "outside")
    assert "git metadata" in await gate("Write", {"file_path": ".git/config"}, "git")
    assert await gate("Read", {"file_path": "private.txt"}, "read") == "That file is marked sensitive."
    assert await gate("WebFetch", {"url": "file:///etc/passwd"}, "fetch") == "WebFetch: only http or https URLs."
    assert await gate("Edit", {"file_path": "notes.md", "new_string": "after"}, "edit") == harnesses.DEFER
    assert proposed_edits == {"edit": target.resolve()}
    assert app.db.one("SELECT path, content FROM snapshots WHERE session_id=?", [session["id"]]) == {
        "path": str(target.resolve()), "content": b"before"}
    assert await gate("Bash", {"command": "ls"}, "bash") == harnesses.DEFER
    assert await gate("OtherTool", {}, "other") == harnesses.DEFER
    approvals.assert_not_called()


async def test_pre_tool_use_defers_to_cli_in_auto(auto_session, monkeypatch):
    app, session, folder = auto_session
    cc = claude_code.ClaudeCode(app)
    sid = session["id"]
    approvals = AsyncMock(return_value={"status": "denied"})
    monkeypatch.setattr(app.approvals, "ask", approvals)
    bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}

    assert await cc.pre_tool_use(sid, bash) == {}
    outside = str(folder.parent / "outside.txt")
    denied = await cc.pre_tool_use(sid, {"tool_name": "Write", "tool_input": {"file_path": outside}})
    assert denied == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": f"{outside} is outside the session folder."}}
    approvals.assert_not_called()

    assert await cc.approve(sid, bash) == {"behavior": "deny", "message": "The user declined."}
    approvals.assert_awaited_once_with(sid, "command", {"subject": "ls", "command": "ls", "cwd": str(folder)})


async def test_sdk_auto_mode_maps_and_defers(auto_session, monkeypatch):
    import claude_agent_sdk as sdk

    app, session, folder = auto_session
    sid = session["id"]
    approvals = AsyncMock(return_value={"status": "approved"})
    monkeypatch.setattr(app.approvals, "ask", approvals)
    app.store.add_message(sid, Message.user("Check the project"))

    async def fake_query(*, prompt, options):
        assert options.permission_mode == "auto"
        hook, = options.hooks["PreToolUse"][0].hooks
        bash = {"command": "ls"}
        write = {"file_path": ".git/config"}
        assert await hook({"tool_name": "Bash", "tool_input": bash}, None, None) == {}
        denied = await hook({"tool_name": "Write", "tool_input": write}, None, None)
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "git metadata" in denied["hookSpecificOutput"]["permissionDecisionReason"]
        assert (await options.can_use_tool("Write", write, None)).behavior == "deny"
        approvals.assert_not_called()

        assert (await options.can_use_tool("Bash", bash, None)).behavior == "allow"
        approvals.assert_awaited_once_with(sid, "command", {"subject": "ls", "command": "ls", "cwd": str(folder)})
        yield sdk.ResultMessage(subtype="success", duration_ms=10, duration_api_ms=10, is_error=False,
                                num_turns=1, session_id="sdk_auto", total_cost_usd=0, usage={})

    monkeypatch.setattr(sdk, "query", fake_query)
    await harnesses.Harnesses(app)._agent_sdk(session)
    assert len(app.db.all("SELECT id FROM usage_records WHERE session_id=?", [sid])) == 1


async def test_denied_auto_edit_is_not_reported_as_changed_sdk(auto_session, monkeypatch):
    import claude_agent_sdk as sdk
    from claude_agent_sdk.types import ToolPermissionContext

    app, session, folder = auto_session
    sid = session["id"]
    create_app("t", app)
    denied = folder / "denied.md"
    written = folder / "written.md"
    denied.write_text("original", encoding="utf-8")
    approvals = AsyncMock(return_value={"status": "denied"})
    monkeypatch.setattr(app.approvals, "ask", approvals)
    app.store.add_message(sid, Message.user("Write the notes"))

    async def fake_query(*, prompt, options):
        hook, = options.hooks["PreToolUse"][0].hooks
        for call_id, target in (("denied", denied), ("written", written)):
            inp = {"file_path": str(target), "content": "new"}
            data = {"tool_name": "Write", "tool_input": inp, "tool_use_id": call_id}
            assert await hook(data, call_id, None) == {}
            if target == denied:
                ctx = ToolPermissionContext(tool_use_id=call_id)
                assert (await options.can_use_tool("Write", inp, ctx)).behavior == "deny"
            else:
                target.write_text("new", encoding="utf-8")
        yield sdk.UserMessage(content=[
            sdk.ToolResultBlock(tool_use_id="written", content="Written."),
            sdk.ToolResultBlock(tool_use_id="denied", content="Denied.", is_error=True),
        ])
        yield sdk.ResultMessage(subtype="success", duration_ms=10, duration_api_ms=10, is_error=False,
                                num_turns=1, session_id="sdk_auto", total_cost_usd=0, usage={})

    monkeypatch.setattr(sdk, "query", fake_query)
    await harnesses.Harnesses(app)._agent_sdk(session)
    approvals.assert_awaited_once()
    assert denied.read_text(encoding="utf-8") == "original"
    assert app.db.one("SELECT content FROM snapshots WHERE session_id=? AND path=?",
                      [sid, str(denied)]) == {"content": b"original"}
    assert [json.loads(row["data"])["path"] for row in app.db.all(
        "SELECT data FROM events WHERE session_id=? AND type='file.changed'", [sid])] == [str(written)]
    assert app.db.all("SELECT path FROM items WHERE session_id=? AND path IS NOT NULL",
                      [sid]) == [{"path": str(written)}]


async def test_codex_harness_auto_still_asks_per_turn(auto_session, monkeypatch):
    app, session, folder = auto_session
    sid = session["id"]
    monkeypatch.setattr(harnesses.shutil, "which", lambda _: "fake-codex")
    approvals = AsyncMock(return_value={"status": "approved"})
    monkeypatch.setattr(app.approvals, "ask", approvals)
    h = harnesses.Harnesses(app)
    turn = AsyncMock(return_value=(0, None, ""))
    monkeypatch.setattr(h, "_codex_turn", turn)

    for count in (1, 2):
        app.store.add_message(sid, Message.user("Check the project"))
        await h._codex_cli(session)
        assert approvals.await_count == count
        assert turn.await_count == count
    card = call(sid, "command", {"subject": "Codex CLI turn",
                               "command": f"codex exec (sandbox: workspace-write) in {folder}", "cwd": str(folder)})
    assert approvals.await_args_list == [card, card]


async def test_auto_bulk_delete_asks_and_decline_denies(auto_session, monkeypatch):
    app, session, folder = auto_session
    approvals = AsyncMock(return_value={"status": "approved"})
    monkeypatch.setattr(app.approvals, "ask", approvals)
    gate = harnesses.make_gate(app, lambda: session, folder, {})
    cmd = "cd sub && rm -rf keep"

    assert await gate("Bash", {"command": cmd}, "b1") is None
    approvals.assert_awaited_once_with(session["id"], "command", {
        "subject": cmd, "command": cmd, "cwd": str(folder),
        "reason": "Auto mode always asks for this: bulk delete"})

    approvals.reset_mock(return_value=True)
    approvals.return_value = {"status": "denied"}
    assert await gate("Bash", {"command": "rm -rf keep"}, "b2") == "The user declined."
    approvals.assert_awaited_once()

    approvals.reset_mock()
    assert await gate("Bash", {"command": "rm keep.txt"}, "b3") == harnesses.DEFER
    assert await gate("Bash", {"command": "pytest -q"}, "b4") == harnesses.DEFER
    approvals.assert_not_called()


async def test_pre_tool_use_bulk_delete_in_auto_shows_card(auto_session, monkeypatch):
    app, session, folder = auto_session
    cc = claude_code.ClaudeCode(app)
    approvals = AsyncMock(return_value={"status": "denied"})
    monkeypatch.setattr(app.approvals, "ask", approvals)
    out = await cc.pre_tool_use(session["id"], {"tool_name": "Bash", "tool_input": {"command": "rm -rf keep"}})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    approvals.assert_awaited_once()


async def test_auto_git_history_rewrite_asks_and_decline_denies(auto_session, monkeypatch):
    app, session, folder = auto_session
    approvals = AsyncMock(return_value={"status": "approved"})
    monkeypatch.setattr(app.approvals, "ask", approvals)
    gate = harnesses.make_gate(app, lambda: session, folder, {})
    cmd = "git push --force origin main"

    assert await gate("Bash", {"command": cmd}, "g1") is None
    approvals.assert_awaited_once_with(session["id"], "command", {
        "subject": cmd, "command": cmd, "cwd": str(folder),
        "reason": "Auto mode always asks for this: git history rewrite"})

    approvals.return_value = {"status": "denied"}
    assert await gate("Bash", {"command": cmd}, "g2") == "The user declined."
    approvals.reset_mock()
    for ok in ("git push origin main", "git status", "git pull", "ls"):
        assert await gate("Bash", {"command": ok}, "g3") == harnesses.DEFER
    approvals.assert_not_called()
