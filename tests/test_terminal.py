import asyncio

from workspace.app import AppState
from workspace.features.terminal import PtyManager


async def test_pty_roundtrip(tmp_path):
    app = AppState(db_path=tmp_path / "t.db")
    mgr = PtyManager(app)
    q = app.bus.subscribe()
    await mgr.handle({"op": "term.open", "tab": "t1", "cwd": str(tmp_path), "cols": 80, "rows": 24})
    await mgr.handle({"op": "term.input", "tab": "t1", "data": "echo pty-$((40+2))\n"})
    out = ""
    for _ in range(100):
        try:
            ev = await asyncio.wait_for(q.get(), 0.1)
        except asyncio.TimeoutError:
            continue
        if ev["type"] == "terminal.output":
            out += ev["data"]["data"]
        if "pty-42" in out:
            break
    assert "pty-42" in out
    # Agent tabs are read-only from the UI.
    await mgr.handle({"op": "term.input", "tab": "agent:job_x", "data": "rm -rf /\n"})
    await mgr.handle({"op": "term.close", "tab": "t1"})
    assert "t1" not in mgr.ptys
