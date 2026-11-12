import asyncio
import time

import pytest

from workspace.agent import builtin_tools as bt
from workspace.agent.tools import ToolContext
from workspace.app import AppState
from workspace.providers.fake import FakeProvider


@pytest.fixture
def env(tmp_path):
    app = AppState(db_path=tmp_path / "r.db")
    app.providers.override("anthropic", "default", FakeProvider("anthropic"))
    folder = tmp_path / "proj"
    folder.mkdir()
    s = app.store.create(folder=str(folder))
    ctx = ToolContext(app=app, session=s, run_id="main:x")

    async def run(name, args):
        return await app.tools.run(ctx, name, args)
    return folder, run


async def test_read_binary_file_refused(env):
    folder, run = env
    (folder / "blob.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00data")
    out = await run("read_file", {"path": "blob.png"})
    assert out.is_error and "binary file" in out.text and "image/png" in out.text and "get_item" in out.text


async def test_read_offset_limit_on_large_file(env, monkeypatch):
    folder, run = env
    (folder / "big.txt").write_text("\n".join(f"line{i}" for i in range(1, 50_001)) + "\n")
    out = await run("read_file", {"path": "big.txt", "offset": 40_001, "limit": 10})
    lines = out.text.split("\n")
    assert lines[0] == "40001\tline40001" and lines[9] == "40010\tline40010"
    assert lines[10] == "… 9990 more lines" and len(lines) == 11
    tail = await run("read_file", {"path": "big.txt", "offset": 49_999})
    assert tail.text == "49999\tline49999\n50000\tline50000"
    # limit is clamped to 5000 (lift the central tool-output cap so the whole result comes back)
    monkeypatch.setattr("workspace.agent.tools.output_limits", lambda ctx: (10_000_000, 4))
    assert (await run("read_file", {"path": "big.txt", "limit": 999_999})).text.count("\n") == 5000  # 5000 lines + note


async def test_read_truncates_long_lines_and_size(env, monkeypatch):
    folder, run = env
    (folder / "min.js").write_text("x" * 10_000 + "\nshort\n")
    out = await run("read_file", {"path": "min.js"})
    first, second = out.text.split("\n")
    assert first.endswith("…[line truncated]") and len(first) < 2100 and second == "2\tshort"
    # Past the size cap the remaining lines are not counted.
    monkeypatch.setattr(bt, "COUNT_CAP", 1)
    (folder / "m.txt").write_text("a\nb\nc\n")
    out = await run("read_file", {"path": "m.txt", "limit": 1})
    assert out.text == "1\ta\n… more lines after line 1 (file is 0.0 MB)"


async def test_search_invalid_regex_falls_back_to_literal(env):
    folder, run = env
    (folder / "a.txt").write_text("call foo(\nother\n")
    out = await run("search", {"pattern": "foo("})
    first = out.text.split("\n")[0]
    assert first.startswith("Invalid regex (") and "searched for the literal text instead." in first
    assert "a.txt:1: call foo(" in out.text


async def test_search_nested_quantifier_falls_back_fast(env):
    folder, run = env
    (folder / "a.txt").write_text("a" * 40 + "!\n(a+)+ literal\n")
    for pat in ("(a+)+$", "(x*)*", "(.*a){10}"):
        t0 = time.monotonic()
        out = await run("search", {"pattern": pat})
        assert time.monotonic() - t0 < 2
        assert out.text.startswith("Unsafe regex (") and "literal text" in out.text
    assert "a.txt:2:" in (await run("search", {"pattern": "(a+)+"})).text
    long = await run("search", {"pattern": "z" * 600})
    assert long.text.startswith("Unsafe regex (pattern longer than 500")


async def test_search_skips_binary_and_oversized(env, monkeypatch):
    folder, run = env
    (folder / "bin.dat").write_bytes(b"needle\x00needle")
    (folder / "huge.txt").write_text("needle\n" + "x" * 3_000_000)
    (folder / "ok.txt").write_text("a needle here\n")
    out = await run("search", {"pattern": "needle"})
    assert out.text == "ok.txt:1: a needle here"
    # Only the first 4000 chars of a line are matched.
    (folder / "min.js").write_text("y" * 5000 + "tail\n")
    assert (await run("search", {"pattern": "tail"})).text == "No matches."


async def test_search_runs_off_event_loop(env, monkeypatch):
    folder, run = env
    (folder / "a.txt").write_text("hello\n")
    real = bt._search_tree

    def slow(*a, **k):
        time.sleep(0.3)
        return real(*a, **k)
    monkeypatch.setattr(bt, "_search_tree", slow)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1
    t = asyncio.create_task(ticker())
    out = await run("search", {"pattern": "hello"})
    t.cancel()
    assert "a.txt:1: hello" in out.text and ticks >= 5  # loop kept running during the blocking walk


async def test_search_time_budget_note(env, monkeypatch):
    folder, run = env
    for i in range(3):
        (folder / f"f{i}.txt").write_text("needle\n")
    monkeypatch.setattr(bt, "SEARCH_BUDGET_S", -1.0)
    out = await run("search", {"pattern": "needle"})
    assert "…stopped after" in out.text and "narrow path or glob" in out.text
