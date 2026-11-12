"""Context-window handling: auto-compact before the window fills (also inside one long autonomous
turn), overflow retry, stop reasons, the turn limit, and Compact keeping the original goal."""
import json

import pytest

from workspace.agent import context as cx
from workspace.agent import loop as loop_mod
from workspace.app import AppState
from workspace.core.types import ChatRequest, Message, Response, TextBlock, ToolResultBlock, ToolUseBlock, Usage
from workspace.providers.base import ProviderError
from workspace.providers.fake import FakeProvider, text_response, tool_response


class Fake(FakeProvider):
    """Main-loop calls follow the script; compaction calls (run_id compact:*) get a canned summary.
    Usage reports no input tokens so the loop's calibration stays at 1.0."""

    def __init__(self, script):
        super().__init__("anthropic", script)
        self.main: list[ChatRequest] = []
        self.compactions: list[ChatRequest] = []

    def _next(self, req):
        if str(req.metadata.get("run_id", "")).startswith("compact:"):
            self.compactions.append(req)
            return text_response("- SUMMARY of earlier work", model=req.model, usage=Usage(output_tokens=5))
        self.main.append(req)
        r = super()._next(req)
        return r.model_copy(update={"usage": Usage(output_tokens=5)})


@pytest.fixture
def app(tmp_path):
    from fastapi import APIRouter, FastAPI

    from workspace.routes import register_routes

    a = AppState(db_path=tmp_path / "c.db")
    register_routes(FastAPI(), APIRouter(), a)
    return a


def use(app, script):
    f = Fake(script)
    app.providers.override("anthropic", "default", f)
    return f


def overhead(app, s) -> int:
    r = app.runner
    return cx.est("\n".join(r.system_segments(s))) + cx.est(json.dumps([t.model_dump() for t in r.tool_specs(s)]))


def pairs_valid(req: ChatRequest) -> bool:
    calls = set()
    for m in req.messages:
        for b in m.content:
            if isinstance(b, ToolUseBlock):
                calls.add(b.id)
            if isinstance(b, ToolResultBlock) and b.tool_use_id not in calls:
                return False
    return True


async def run(app, sid):
    await app.runner.start(sid)


async def test_auto_compacts_inside_one_long_turn_and_keeps_pairs(app, tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "big.txt").write_text("lorem ipsum dolor sit amet, consectetur\n" * 280)  # ~3k tokens per read
    s = app.store.create(folder=str(folder), model="claude.deep", effort="low")
    app.config.orchestrator["max_tokens"] = 1000
    m = app.config.model(s["model"])
    m.context_window = overhead(app, s) + 14_000
    reads = [tool_response("read_file", {"path": "big.txt"}) for _ in range(8)]
    fake = use(app, [*reads, text_response("all done")])
    app.store.add_message(s["id"], Message.user("Read big.txt eight times and report the GOAL-XYZ"))
    await run(app, s["id"])
    msgs = app.store.messages(s["id"])
    summaries = [x for x in msgs if x.meta.get("summary")]
    assert summaries and summaries[0].meta.get("auto")
    assert fake.compactions, "claude.fast summarizer was called through the adapter"
    assert fake.compactions[0].effort == "low"
    # The user's turn was summarized away mid-turn, so the summary quotes it verbatim.
    assert "GOAL-XYZ" in summaries[-1].text()
    # Every request after compaction is still a valid tool_use/tool_result sequence.
    assert all(pairs_valid(r) for r in fake.main)
    win = m.context_window
    assert all(cx.messages_tokens(r.messages) + overhead(app, s) <= win for r in fake.main)
    assert msgs[-1].text() == "all done"
    roles = {r["role"] for r in app.db.all("SELECT role FROM usage_records WHERE session_id=?", [s["id"]])}
    assert "compact" in roles


async def test_overflow_error_compacts_and_retries_once(app):
    s = app.store.create(effort="low")
    for i in range(5):
        app.store.add_message(s["id"], Message.user(f"question {i}"))
        app.store.add_message(s["id"], Message.assistant(f"answer {i}"))
    app.store.add_message(s["id"], Message.user("final question"))

    def too_long(req):
        raise ProviderError("Error code: 400 - prompt is too long: 1200000 tokens > 1000000 maximum", status=400)

    fake = use(app, [too_long, text_response("fits now")])
    await run(app, s["id"])
    msgs = app.store.messages(s["id"], include_compacted=False)
    assert any(x.meta.get("summary") for x in msgs) and msgs[-1].text() == "fits now"
    assert len(fake.main) == 2 and not any(x.meta.get("error") for x in msgs)


async def test_overflow_twice_gives_a_clear_message(app):
    s = app.store.create(effort="low")
    for i in range(5):
        app.store.add_message(s["id"], Message.user(f"q{i}"))
        app.store.add_message(s["id"], Message.assistant(f"a{i}"))
    app.store.add_message(s["id"], Message.user("last"))

    def too_long(req):
        raise ProviderError("prompt is too long", status=400)

    use(app, [too_long, too_long, too_long])
    await run(app, s["id"])
    last = app.store.messages(s["id"])[-1]
    assert last.meta.get("error") and "no longer fits" in last.text() and "ProviderError" not in last.text()


async def test_context_window_stop_reason_retries_after_compacting(app):
    s = app.store.create(effort="low")
    for i in range(5):
        app.store.add_message(s["id"], Message.user(f"q{i}"))
        app.store.add_message(s["id"], Message.assistant(f"a{i}"))
    app.store.add_message(s["id"], Message.user("go on"))
    partial = Response(id="r1", provider="anthropic", model="x", content=[TextBlock(text="half a rep")],
                       stop_reason="context_window")
    fake = use(app, [partial, text_response("complete reply")])
    await run(app, s["id"])
    texts = [x.text() for x in app.store.messages(s["id"], include_compacted=False)]
    assert "half a rep" not in texts and texts[-1] == "complete reply" and len(fake.main) == 2


async def test_max_tokens_and_turn_limit_leave_notices_the_model_never_sees(app, monkeypatch):
    s = app.store.create(effort="low")
    cut = Response(id="r", provider="anthropic", model="x", content=[TextBlock(text="long answ")],
                   stop_reason="max_tokens")
    fake = use(app, [cut, text_response("ok")])
    app.store.add_message(s["id"], Message.user("write a lot"))
    await run(app, s["id"])
    note = app.store.messages(s["id"])[-1]
    assert note.meta.get("notice") == "max_tokens" and "continue" in note.text()
    app.store.add_message(s["id"], Message.user("continue"))
    await run(app, s["id"])
    assert not any("output limit" in x.text() for x in fake.main[-1].messages)

    monkeypatch.setattr(loop_mod, "MAX_MAIN_TURNS", 3)
    use(app, [tool_response("list_items", {}) for _ in range(5)])
    app.store.add_message(s["id"], Message.user("loop forever"))
    await run(app, s["id"])
    note = app.store.messages(s["id"])[-1]
    assert note.meta.get("notice") == "turn_limit" and "continue" in note.text().lower()


def test_cut_candidates_never_orphan_tool_results():
    a = Message.assistant(ToolUseBlock(id="t1", name="x"))
    msgs = [Message.user("one"), Message.assistant("a"), Message.user("two"), Message.assistant("b"), a,
            Message.user("three"),  # the run was stopped; the repaired result lands after the next user turn
            Message(role="user", content=[ToolResultBlock.text("t1", "interrupted")], meta={"tool_results": True}),
            Message.assistant("c")]
    for c in cx.cut_candidates(msgs):
        assert cx._pairs_intact(msgs[c:])
    assert 5 not in cx.cut_candidates(msgs)


def test_stub_tool_results_shrinks_oldest_first():
    big = "x" * 36_000  # ~10k tokens
    msgs = [Message.user("go")]
    for i in range(4):
        msgs.append(Message.assistant(ToolUseBlock(id=f"t{i}", name="read_file")))
        msgs.append(Message(role="user", content=[ToolResultBlock.text(f"t{i}", big)], meta={"tool_results": True}))
    out, n = cx.stub_tool_results(msgs, cx.messages_tokens, 25_000)
    assert n >= 2 and cx.messages_tokens(out) <= 25_000
    assert out[-1].content[0].content[0].text == big  # the latest result is kept
    assert "removed to fit" in out[2].content[0].content[0].text
    assert msgs[2].content[0].content[0].text == big  # the input wasn't changed


async def test_manual_compact_keeps_goal_head_and_tail(app, monkeypatch):
    from workspace.features import session_routes

    s = app.store.create(effort="low")
    monkeypatch.setattr(cx, "TRANSCRIPT_MAX", 2000)
    monkeypatch.setattr(cx, "TRANSCRIPT_HEAD", 500)
    app.store.add_message(s["id"], Message.user("ORIGINAL-GOAL: build the thing"))
    for i in range(8):
        app.store.add_message(s["id"], Message.assistant("filler " * 60 + f"step {i}"))
        app.store.add_message(s["id"], Message.user(f"next {i}"))
    fake = use(app, [])
    r = await session_routes.compact(app, s["id"])
    assert r["compacted"] > 0
    sent = fake.compactions[0].messages[0].text()
    assert "ORIGINAL-GOAL" in sent and "omitted" in sent and "step 4" in sent


async def test_manual_compact_inside_one_long_turn(app):
    from workspace.features import session_routes

    s = app.store.create(effort="low")
    app.store.add_message(s["id"], Message.user("one long job"))
    for i in range(8):
        app.store.add_message(s["id"], Message.assistant(ToolUseBlock(id=f"t{i}", name="list_items")))
        app.store.add_message(s["id"], Message(role="user", content=[ToolResultBlock.text(f"t{i}", "r")],
                                               meta={"tool_results": True}))
    use(app, [])
    assert (await session_routes.compact(app, s["id"]))["compacted"] > 0
    kept = app.runner.model_history(s["id"])
    assert kept[0].meta.get("summary") and "one long job" in kept[0].text()
    assert cx._pairs_intact(kept)
    ctx = session_routes.context_breakdown(app, s["id"])
    assert ctx["level"] == "ok" and "auto_compact_at" in ctx


async def test_cut_off_tool_call_is_answered_before_the_next_user_turn(app):
    from workspace.providers.anthropic_provider import messages_to_wire

    s = app.store.create(effort="low")
    cut = Response(id="r", provider="anthropic", model="x", stop_reason="max_tokens",
                   content=[ToolUseBlock(id="toolu_cut", name="write_file", input={"path": "a"})])
    fake = use(app, [cut, text_response("resumed")])
    app.store.add_message(s["id"], Message.user("write it"))
    await run(app, s["id"])
    hist = app.runner.model_history(s["id"])
    assert hist[-1].meta.get("tool_results") and hist[-1].content[0].tool_use_id == "toolu_cut"
    app.store.add_message(s["id"], Message.user("continue"))
    await run(app, s["id"])
    wire = messages_to_wire(fake.main[-1].messages)
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]
    assert wire[2]["content"][0]["type"] == "tool_result"  # results lead the user turn


def test_merged_user_turn_puts_tool_results_first():
    from workspace.providers.anthropic_provider import messages_to_wire

    msgs = [Message.user("go"), Message.assistant(ToolUseBlock(id="t1", name="x")), Message.user("continue"),
            Message(role="user", content=[ToolResultBlock.text("t1", "interrupted")], meta={"tool_results": True})]
    wire = messages_to_wire(msgs)
    assert [b["type"] for b in wire[2]["content"]] == ["tool_result", "text"]


async def test_failed_auto_compact_isnt_retried_every_call(app, tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "big.txt").write_text("lorem ipsum dolor sit amet, consectetur\n" * 280)
    s = app.store.create(folder=str(folder), model="claude.deep", effort="low")
    app.config.orchestrator["max_tokens"] = 1000
    app.config.model(s["model"]).context_window = overhead(app, s) + 14_000

    class NoSummarizer(Fake):
        def _next(self, req):
            if str(req.metadata.get("run_id", "")).startswith("compact:"):
                self.compactions.append(req)
                raise ProviderError("No Anthropic key for profile 'default'", auth=True)
            return super()._next(req)

    fake = NoSummarizer([*(tool_response("read_file", {"path": "big.txt"}) for _ in range(8)), text_response("ok")])
    app.providers.override("anthropic", "default", fake)
    app.store.add_message(s["id"], Message.user("go"))
    await run(app, s["id"])
    assert len(fake.compactions) == 1  # tried once, then old tool output is stubbed instead
    assert app.store.messages(s["id"])[-1].text() == "ok"
    assert any("removed to fit" in json.dumps([m.model_dump() for m in r.messages]) for r in fake.main)


async def test_no_cut_point_yet_doesnt_disable_auto_compaction_for_the_turn(app, tmp_path):
    """The window fills before there is anywhere to cut (the first tool exchanges of a turn); once a cut
    point exists later in the same turn, auto-compaction still runs (only a failed summarizer latches)."""
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "big.txt").write_text("lorem ipsum dolor sit amet, consectetur\n" * 280)  # ~3k tokens per read
    s = app.store.create(folder=str(folder), model="claude.deep", effort="low")
    app.config.orchestrator["max_tokens"] = 1000
    app.config.model(s["model"]).context_window = overhead(app, s) + 4_000  # full after the first read
    fake = use(app, [*(tool_response("read_file", {"path": "big.txt"}) for _ in range(5)), text_response("done")])
    app.store.add_message(s["id"], Message.user("go"))
    await run(app, s["id"])
    assert fake.compactions, "compacted once a cut point appeared"
    assert any(x.meta.get("summary") for x in app.store.messages(s["id"]))
    assert app.store.messages(s["id"])[-1].text() == "done"
