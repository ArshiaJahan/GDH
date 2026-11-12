"""WP2 hooks engine: hook files (TOML) and their validation, trust by hash, consent, actions
(block / note / command / mcp / builtin), Plan mode, crash handling, the always-on built-ins
(tool-failure breaker, scars first touch, context pack) and the REST routes."""
import asyncio
import json
import time

import pytest

from workspace.agent.tools import ToolContext
from workspace.app import AppState
from workspace.core.types import Message, ToolResultBlock
from workspace.features import hooks as H
from workspace.features.hookbus import HookEvent, HookResult, TurnState
from workspace.providers.fake import FakeProvider, text_response, tool_response

from .conftest import untrusted


@pytest.fixture
def app(tmp_path):
    a = AppState(db_path=tmp_path / "h.db")
    a.fake = FakeProvider()
    a.providers.override("anthropic", "default", a.fake)
    H.install(a)
    return a


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "proj"
    (d / ".workspace").mkdir(parents=True)
    (d / "a.txt").write_text("alpha\n")
    return d


def session(app, folder=None, mode="accept_edits", **settings):
    return app.store.create(folder=str(folder) if folder else None, mode=mode, **settings)


async def turn(app, sid, text="hi"):
    app.store.add_message(sid, Message.user(text))
    await app.runner.start(sid)


def results(app, sid):
    return [b for m in app.store.messages(sid) if m.meta.get("tool_results") for b in m.content
            if isinstance(b, ToolResultBlock)]


def eng(app) -> H.HooksEngine:
    return H.get_engine(app)


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out waiting"
        await asyncio.sleep(0.01)


BLOCK_SECRET = """version = 1
[[hook]]
id = "no-secrets"
event = "pre_tool"
tools = ["write_file"]
paths = ["secret/**"]
action = "block"
reason = "secret/ is off limits."
"""


# ------------------------------------------------------------------ parsing


def test_builtin_preset_parses_cleanly(app):
    e = eng(app)
    entries, errors = H.parse_hooks_toml(H.HooksEngine.preset_path().read_text(), e.builtins)
    assert errors == []
    ids = {x.id: x for x in entries}
    assert ids["cs-compile"].gate_id() == "unity.compile" and ids["cs-compile"].level == "L1"
    assert ids["cs-compile"].changed[0] == "Assets/**/*.cs" and ids["cs-compile"].on_fail == "block"
    assert ids["block-generated"].fail == "closed" and ids["verify-tests"].phases == ["verify"]
    assert ids["backlog-lint"].on_fail == "note"


def test_validation_reports_problems_and_skips_bad_entries(app):
    text = """version = 1
extra = 1
[[hook]]
id = "ok"
event = "post_tool"
action = "note"
note = "hello"
[[hook]]
id = "ok"
event = "post_tool"
action = "note"
note = "dup"
[[hook]]
id = "bad event"
event = "pre_toool"
action = "block"
[[hook]]
id = "noreason"
event = "pre_tool"
action = "block"
colour = "red"
[[hook]]
id = "cmd"
event = "pre_complete"
action = "command"
run = "lint {projekt}"
timeout_s = 99999
[[hook]]
id = "bi"
event = "post_tool"
action = "builtin"
name = "unity.compile"
[[hook]]
id = "nb"
event = "post_tool"
action = "builtin"
name = "nope"
[[hook]]
id = "note-pre"
event = "pre_complete"
action = "note"
note = "x"
on_fail = "maybe"
"""
    entries, errors = H.parse_hooks_toml(text, eng(app).builtins)
    assert [e.id for e in entries] == ["ok"]
    joined = "\n".join(errors)
    for frag in ("unknown top-level key(s): extra", "duplicate id 'ok'", "event must be one of",
                 "block needs a reason", "unknown key(s): colour", "unknown placeholder {projekt}", "timeout_s: 1-1800",
                 "builtin unity.compile runs on pre_complete, post_merge, not post_tool", "unknown builtin 'nope'",
                 "action note only works for post_tool and post_merge", "on_fail must be block or note"):
        assert frag in joined, frag
    assert H.parse_hooks_toml("not = [toml", {})[1][0].startswith("not valid TOML")
    assert H.parse_hooks_toml("version = 2", {})[1] == ["version must be 1"]


def test_helpers():
    assert H.rel_path("mcpforunity://path/Assets/A.cs") == "Assets/A.cs"
    assert H.rel_path("./Assets/../Assets/B.cs") == "Assets/B.cs"
    assert H.error_signature("exit code 1\nError: '/tmp/x/a.txt' not found at line 12") == \
        H.error_signature("exit code 1\nError: '/other/b.txt' not found at line 99")
    pms = H.parse_postmortems("# Postmortems\n### PM-007 Hit flash stuck (2026-11-12)\n- Rule: Reset feedback.\n"
                              "- Applies to: Assets/**/Feel/**, `Assets/**/*Pool*.cs`\n### PM-008 Other\n- Rule: x\n"
                              "- Applies to: none\n")
    assert pms[0] == {"id": "PM-007", "num": 7, "title": "Hit flash stuck", "rule": "Reset feedback.",
                      "globs": ["Assets/**/Feel/**", "Assets/**/*Pool*.cs"]}
    assert pms[1]["globs"] == []


# ---------------------------------------------------------------- trust


async def test_untrusted_file_is_ignored_and_raises_a_card(app, folder):
    (folder / ".workspace/hooks.toml").write_text(BLOCK_SECRET)
    s = session(app, folder)
    app.fake.script = [tool_response("write_file", {"path": "secret/a.txt", "content": "x"}), text_response("ok")]
    await turn(app, s["id"])
    assert (folder / "secret/a.txt").exists()  # ignored while untrusted
    cards = app.approvals.pending(s["id"])
    assert [c["kind"] for c in cards] == ["hook_trust"]
    p = cards[0]["payload"]
    assert "secret/ is off limits." in p["markdown"] and "```toml" in p["markdown"]
    assert {b["id"] for b in p["buttons"]} == {"trust_all", "trust_ask", "ignore"}
    assert [e["type"] for e in app.bus.replay(0, s["id"]) if e["type"] == "hooks.trust_needed"]
    # Asking again while the card is open doesn't add a second one.
    await turn(app, s["id"], "again")
    assert len(app.approvals.pending(s["id"])) == 1

    app.approvals.resolve(cards[0]["id"], "approve", choice="trust_all")
    await settle()
    src = next(x for x in eng(app).sources(s) if x.kind == "project")
    assert src.state == "trusted" and src.mode == "trust_all"
    (folder / "secret/a.txt").unlink()
    app.fake.script = [tool_response("write_file", {"path": "secret/a.txt", "content": "x"}), text_response("ok")]
    await turn(app, s["id"], "write it")
    assert not (folder / "secret/a.txt").exists()
    assert results(app, s["id"])[-1].content[0].text == "Blocked by no-secrets: secret/ is off limits."

    # A changed file (the agent may write it) is a new, untrusted version: ignored, card again.
    (folder / ".workspace/hooks.toml").write_text(BLOCK_SECRET.replace("off limits", "private"))
    src = next(x for x in eng(app).sources(s) if x.kind == "project")
    assert src.state == "changed" and not src.active
    app.fake.script = [tool_response("write_file", {"path": "secret/a.txt", "content": "x"}), text_response("ok")]
    await turn(app, s["id"], "and now")
    assert (folder / "secret/a.txt").exists()
    card = app.approvals.pending(s["id"])[0]
    assert card["kind"] == "hook_trust" and card["payload"]["sha256"] == src.sha

    # "Ignore this version": no more cards for it; a further change asks again.
    app.approvals.resolve(card["id"], "deny", choice="ignore")
    await settle()
    assert next(x for x in eng(app).sources(s) if x.kind == "project").state == "declined"
    await turn(app, s["id"], "more")
    assert app.approvals.pending(s["id"]) == []


async def test_card_left_open_by_a_stopped_run_is_asked_again(app, folder):
    (folder / ".workspace/hooks.toml").write_text(BLOCK_SECRET)
    s = session(app, folder)
    await turn(app, s["id"])
    aid = app.approvals.pending(s["id"])[0]["id"]
    app.approvals.expire_session(s["id"])
    await settle()
    assert next(x for x in eng(app).sources(s) if x.kind == "project").state == "untrusted"  # not declined
    await turn(app, s["id"], "again")
    assert [c["id"] != aid for c in app.approvals.pending(s["id"])] == [True]


# ---------------------------------------------------------- actions & consent


def trust_file(app, folder, text, mode="trust_all"):
    (folder / ".workspace/hooks.toml").write_text(text)
    e = eng(app)
    src = next(x for x in e.sources(project=folder.resolve()) if x.kind == "project")
    e.trust(src, folder.resolve(), mode)
    return src


CMD_HOOK = """version = 1
[[hook]]
id = "echo-check"
event = "post_tool"
tools = ["write_file"]
action = "command"
run = "echo checked {changed} && exit 3"
ok_exit = [0]
"""


def post_tool_event(app, s, path="notes.md"):
    ctx = ToolContext(app=app, session=app.store.get(s["id"]), run_id="main:x", role="main")
    from workspace.agent.tools import ToolOutput

    return HookEvent("post_tool", ctx, tool="write_file", args={"path": path, "content": "x"},
                     output=ToolOutput("Wrote notes.md"), turn=TurnState(s["id"], time.time(), folder=ctx.folder))


async def test_trusted_command_runs_without_card_and_failure_is_noted_untrusted(app, folder):
    trust_file(app, folder, CMD_HOOK)
    s = session(app, folder, mode="ask")
    res = await eng(app).dispatch(post_tool_event(app, s))
    assert app.approvals.pending() == []  # the trusted file listed this command template
    (r,) = res
    assert r.action == "note" and r.status == "fail" and r.hook == "echo-check"
    head, body = r.note.split("\n", 1)
    assert head.startswith("[echo-check] echo-check failed (exit 3)")
    src, inner = untrusted(body)
    assert src == "command:echo-check" and "checked notes.md" in inner


async def test_trust_ask_commands_follow_the_allowlist_or_a_card(app, folder):
    trust_file(app, folder, CMD_HOOK.replace(" && exit 3", ""), mode="trust_ask")
    s = session(app, folder, mode="ask")
    task = asyncio.create_task(eng(app).dispatch(post_tool_event(app, s)))
    await until(lambda: app.approvals.pending(s["id"]))
    (card,) = app.approvals.pending(s["id"])
    assert card["kind"] == "command" and card["payload"]["command"] == "echo checked notes.md"
    assert card["payload"]["role"] == "hook"
    app.approvals.resolve(card["id"], "deny")
    (r,) = await task
    assert r.status == "skipped" and "didn't run" in r.reason and r.action == "allow"
    # An allowlist rule lets it through without a card.
    app.config.modes = {**app.config.modes, "allowlist": ["run_command:echo checked *"]}
    assert await eng(app).dispatch(post_tool_event(app, s)) == []  # passed: nothing to add
    assert app.approvals.pending() == []


async def test_plan_mode_runs_only_block_and_note(app, folder):
    trust_file(app, folder, CMD_HOOK + """
[[hook]]
id = "remind"
event = "post_tool"
action = "note"
note = "Remember the changelog."
""")
    s = session(app, folder, mode="plan")
    res = await eng(app).dispatch(post_tool_event(app, s))
    assert [(r.hook, r.note) for r in res] == [("remind", "Remember the changelog.")]
    assert app.db.one("SELECT COUNT(*) n FROM jobs")["n"] == 0  # the command never ran


async def test_crashing_block_hook_denies_the_call(app, folder):
    def boom(engine, entry, ev, ac):
        raise RuntimeError("guard exploded")

    eng(app).add_builtin("test.guard", boom, ("pre_tool",))
    trust_file(app, folder, """version = 1
[[hook]]
id = "guard"
event = "pre_tool"
tools = ["write_file"]
action = "builtin"
name = "test.guard"
""")
    s = session(app, folder)
    app.fake.script = [tool_response("write_file", {"path": "b.txt", "content": "x"}), text_response("ok")]
    await turn(app, s["id"])
    out = results(app, s["id"])[0]
    assert out.is_error and out.content[0].text.startswith("Blocked by guard: the check guard failed (RuntimeError: guard exploded)")
    assert not (folder / "b.txt").exists()
    errs = [e["data"] for e in app.bus.replay(0, s["id"]) if e["type"] == "hooks.error"]
    assert errs and errs[0]["hook"] == "guard" and errs[0]["fail"] == "closed"
    # fail = "open": the same crash lets the call through (and still reports it).
    trust_file(app, folder, (folder / ".workspace/hooks.toml").read_text() + 'fail = "open"\n')
    app.fake.script = [tool_response("write_file", {"path": "b.txt", "content": "x"}), text_response("ok")]
    await turn(app, s["id"], "again")
    assert (folder / "b.txt").exists()


async def test_mcp_action_uses_consent(app, folder):
    calls = []

    class FakeMCP:
        def owns(self, name):
            return name == "mcp__lint__check"

        async def call(self, ctx, name, args):
            from workspace.agent.tools import ToolOutput, wrap_untrusted

            calls.append((name, args, ctx.role, ctx.consented("mcp", "lint__check")))
            return ToolOutput(wrap_untrusted("2 problems", "mcp:lint.check"), is_error=True)

    app.mcp = FakeMCP()
    trust_file(app, folder, """version = 1
[[hook]]
id = "lint"
event = "post_tool"
action = "mcp"
tool = "lint__check"
args = { strict = true }
""")
    s = session(app, folder)
    (r,) = await eng(app).dispatch(post_tool_event(app, s))
    assert calls == [("mcp__lint__check", {"strict": True}, "hook", True)]
    assert r.note.startswith("[lint] lint: lint.check failed") and untrusted(r.note.split("\n", 1)[1])[1] == "2 problems"


# ------------------------------------------------------- always-on built-ins


async def test_tool_failure_breaker_notes_then_stops(app, folder):
    s = session(app, folder)
    app.fake.script = [tool_response("read_file", {"path": f"missing{i}.txt"}) for i in range(6)] + [text_response("x")]
    await turn(app, s["id"])
    texts = [r.content[0].text for r in results(app, s["id"])]
    assert len(texts) == 5 and len(app.fake.calls) == 5
    assert "change approach" not in texts[1] and "failed 3 times in a row" in texts[2] and "failed 4 times" in texts[3]
    assert "the turn stops here" in texts[4]
    last = app.store.messages(s["id"])[-1]
    assert last.meta.get("notice") == "tool_failure_breaker" and "failed 5 times" in last.content[0].text


async def test_breaker_resets_on_success(app, folder):
    s = session(app, folder)
    script = [tool_response("read_file", {"path": "nope.txt"})] * 2 + [tool_response("read_file", {"path": "a.txt"})]
    app.fake.script = script + [tool_response("read_file", {"path": "nope.txt"})] * 2 + [text_response("ok")]
    await turn(app, s["id"])
    assert not any("change approach" in r.content[0].text for r in results(app, s["id"]))


async def test_scars_first_touch_once_per_session(app, folder):
    (folder / "POSTMORTEMS.md").write_text(
        "# Postmortems\n\n### PM-007 Hit flash stayed on after pooling (2026-11-12)\n- What broke: x\n"
        "- Rule: Pooled objects reset every feedback component in OnDisable.\n"
        "- Applies to: Assets/**/Feel/**, Assets/**/*Pool*.cs\n")
    (folder / "Assets/Game").mkdir(parents=True)
    (folder / "Assets/Game/BulletPool.cs").write_text("class P {}\n")
    s = session(app, folder)
    app.fake.script = [tool_response("read_file", {"path": "Assets/Game/BulletPool.cs"}),
                       tool_response("read_file", {"path": str(folder / "Assets/Game/BulletPool.cs")}),
                       tool_response("read_file", {"path": "a.txt"}), text_response("ok")]
    await turn(app, s["id"])
    texts = [r.content[0].text for r in results(app, s["id"])]
    note = "[Project rule PM-007 (POSTMORTEMS.md): Pooled objects reset every feedback component in OnDisable.]"
    assert texts[0].endswith("\n\n" + note) and note not in texts[1] and note not in texts[2]
    s2 = session(app, folder)  # a new session gets it again
    app.fake.script = [tool_response("read_file", {"path": "Assets/Game/BulletPool.cs"}), text_response("ok")]
    await turn(app, s2["id"])
    assert results(app, s2["id"])[0].content[0].text.endswith(note)


def unity_project(folder):
    (folder / "ProjectSettings").mkdir(exist_ok=True)
    (folder / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.21f1\n")


async def test_context_pack_is_built_once_and_stays_frozen(app, folder):
    unity_project(folder)
    (folder / "PROJECT.md").write_text("# Game\n\n## Current milestone\nM3 Boss rush: three bosses.\n\n## ADRs\n- x\n")
    (folder / "TASTE.md").write_text("# Taste\n## Three words\ncrunchy, readable, cozy\n## Ranked heuristics\n"
                                     "1. threat readability\n2. feedback < 100 ms\n## Anti-patterns\n- no screen shake\n")
    (folder / "POSTMORTEMS.md").write_text("### PM-001 Old\n- Rule: a\n### PM-002 New\n- Rule: b\n")
    s = session(app, folder)
    await turn(app, s["id"])
    pack = app.store.get(s["id"])["settings"]["context_pack"]
    sys1 = app.fake.calls[0].system[-1]
    assert sys1 == pack["text"] and pack["sources"] == ["PROJECT.md", "TASTE.md", "POSTMORTEMS.md"]
    assert "M3 Boss rush" in sys1 and "crunchy" in sys1 and "no screen shake" in sys1
    assert sys1.index("PM-002") < sys1.index("PM-001") and len(sys1) <= H.CONTEXT_PACK_MAX
    (folder / "PROJECT.md").write_text("## Current milestone\nM4 Something else\n")
    await turn(app, s["id"], "next")
    assert app.fake.calls[-1].system == app.fake.calls[0].system  # frozen: the cache stays valid
    new = eng(app).refresh_context_pack(s["id"])
    assert "M4 Something else" in new["text"]
    # A plain folder (no Unity project, no PROJECT.md) gets no pack.
    other = session(app, folder.parent)
    await turn(app, other["id"])
    assert "context_pack" not in app.store.get(other["id"])["settings"]


async def test_backlog_lint_note_after_write(app, folder):
    unity_project(folder)
    e = eng(app)
    e.enable_preset(folder.resolve())
    s = session(app, folder)
    app.fake.script = [tool_response("write_file", {"path": "BACKLOG.md", "content": "# Backlog\n\nnothing here\n"}),
                       text_response("ok")]
    await turn(app, s["id"])
    text = results(app, s["id"])[0].content[0].text
    head, rest = text.split("\n\n", 1)
    assert head.startswith("Wrote") or head
    assert "[backlog.lint] BACKLOG.md has" in rest
    src, body = untrusted(rest.split("\n", 1)[1])
    assert src == "backlog_lint" and body.startswith("ERROR BACKLOG.md:")


# ------------------------------------------------------------------- routes


def test_routes(tmp_path, folder):
    from fastapi.testclient import TestClient

    from workspace.server import create_app

    unity_project(folder)
    (folder / ".workspace/hooks.toml").write_text(BLOCK_SECRET)
    st = AppState(db_path=tmp_path / "t.db")
    h = {"Authorization": "Bearer t"}
    with TestClient(create_app("t", st)) as c:
        s = st.store.create(folder=str(folder), mode="ask")
        r = c.get("/api/hooks", params={"session_id": s["id"]}, headers=h).json()
        kinds = {x["kind"]: x for x in r["sources"]}
        assert r["unity_project"] and kinds["preset"]["state"] == "off" and kinds["project"]["state"] == "untrusted"
        assert "unity__refresh_unity" in kinds["preset"]["needs"]["tools"] and r["gates"] == []
        assert {"tool_failure_breaker", "unity.compile"} <= {b["name"] for b in r["builtins"]}
        # Turning the gates on goes through the consent card.
        r = c.post("/api/hooks/preset", json={"session_id": s["id"], "enabled": True}, headers=h).json()
        assert r["status"] == "pending"
        card = next(x for x in c.get("/api/approvals", headers=h).json() if x["id"] == r["approval_id"])
        assert card["kind"] == "hook_preset" and "refresh_unity" in card["payload"]["markdown"]
        c.post(f"/api/approvals/{r['approval_id']}", json={"decision": "approve", "choice": "enable"}, headers=h)
        for _ in range(50):
            got = c.get("/api/hooks", params={"session_id": s["id"]}, headers=h).json()
            if got["gates"]:
                break
            time.sleep(0.02)
        assert "unity.compile" in got["gates"]
        assert {x["kind"]: x["state"] for x in got["sources"]}["preset"] == "enabled"
        # The trust route raises the file's card; untrusting removes the row.
        r = c.post("/api/hooks/trust", json={"session_id": s["id"]}, headers=h).json()
        assert r["status"] == "pending" and len(r["approval_ids"]) == 1
        assert c.post("/api/hooks/preset", json={"session_id": s["id"], "enabled": False},
                      headers=h).json() == {"status": "disabled"}
        assert c.get("/api/hooks", params={"session_id": s["id"]}, headers=h).json()["gates"] == []
        assert c.post("/api/hooks/run", json={"session_id": s["id"], "gate": "nope"}, headers=h).status_code == 404
        assert c.get("/api/hooks", headers=h).status_code == 400
        assert c.get("/api/hooks/unity", params={"session_id": s["id"]}, headers=h).json()["unity_project"] is True
        r = c.post("/api/hooks/context_pack", json={"session_id": s["id"]}, headers=h).json()
        assert r["context_pack"] is None  # a Unity project with nothing to pack yet
    row = st.db.one("SELECT detail FROM hook_trust WHERE kind='preset'")
    assert row is None  # disabled again
