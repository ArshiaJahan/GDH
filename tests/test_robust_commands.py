"""Commands.run: bounded memory, output in a file, coalesced events; Jobs.log without a DB hit per call."""
import asyncio
import sys
from pathlib import Path

from workspace.app import AppState


def make(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/sh")
    s = AppState(db_path=tmp_path / "r.db")
    events: list[tuple[str, dict]] = []
    orig = s.bus.publish

    def spy(type, data=None, session_id=None):
        events.append((type, data))
        return orig(type, data, session_id)

    monkeypatch.setattr(s.bus, "publish", spy)
    sid = s.store.create(folder=str(tmp_path))["id"]
    return s, sid, events


async def test_big_output_is_bounded_and_kept_in_a_file(tmp_path, monkeypatch):
    s, sid, events = make(tmp_path, monkeypatch)
    jid = s.jobs.start(sid, "command", "big")
    py = "import sys; [sys.stdout.write('x'*1000+'\\n') for _ in range(5000)]"
    code, text = await s.commands.run(jid, f'{sys.executable} -c "{py}"', tmp_path)
    assert code == 0
    assert len(text) < 300_000 and "omitted; full output in" in text
    path = Path(s.jobs.get(jid)["meta"]["log_path"])
    assert str(path) in text
    assert path.stat().st_size == 5000 * 1001
    outs = [d for t, d in events if t == "terminal.output"]
    assert 0 < len(outs) < 100  # ~1200 raw 4 KB chunks, coalesced
    assert all(len(d["data"]) < 70_000 for d in outs)
    assert s.jobs.get(jid)["status"] == "done"


async def test_small_output_order_and_nothing_lost(tmp_path, monkeypatch):
    s, sid, events = make(tmp_path, monkeypatch)
    jid = s.jobs.start(sid, "command", "small")
    code, text = await s.commands.run(jid, "printf 'a\\nb\\nc\\n'", tmp_path)
    assert (code, text) == (0, "a\nb\nc\n")
    assert "".join(d["data"] for t, d in events if t == "terminal.output") == "a\nb\nc\n"
    assert "".join(d["text"] for t, d in events if t == "job.log") == "a\nb\nc\n"
    kinds = [t for t, _ in events]
    assert kinds.index("terminal.output") < kinds.index("terminal.agent_exit")
    assert s.jobs.get(jid)["log_tail"] == "a\nb\nc\n"


async def test_cancel_flushes_and_marks_cancelled(tmp_path, monkeypatch):
    s, sid, events = make(tmp_path, monkeypatch)
    jid = s.jobs.start(sid, "command", "slow")
    task = asyncio.create_task(s.commands.run(jid, "echo hello; sleep 30", tmp_path, timeout=60))
    s.jobs.attach(jid, task)
    for _ in range(100):
        if s.jobs.procs.get(jid):
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.03)  # output arrives; the 100 ms flush has not fired yet
    await s.jobs.cancel(jid)
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert s.jobs.get(jid)["status"] == "cancelled"
    assert "".join(d["data"] for t, d in events if t == "terminal.output") == "hello\n"
    assert jid not in s.jobs.procs and jid not in s.jobs._tails


async def test_jobs_log_does_not_query_the_db_per_call(tmp_path, monkeypatch):
    s, sid, _ = make(tmp_path, monkeypatch)
    jid = s.jobs.start(sid, "command", "x")
    calls = []
    orig = s.db.one
    monkeypatch.setattr(s.db, "one", lambda *a, **k: (calls.append(a), orig(*a, **k))[1])
    for _ in range(20):
        s.jobs.log(jid, "line\n")
    assert calls == []
    s.jobs.finish(jid)
    s.jobs.log(jid, "late\n")  # after finish: one fallback lookup, then cached again
    s.jobs.log(jid, "late\n")
    assert sum("session_id FROM jobs" in str(c) for c in calls) == 1
