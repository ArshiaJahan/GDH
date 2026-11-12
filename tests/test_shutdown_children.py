"""Quitting ends every child process group the backend started (they run in their own sessions,
out of reach of the desktop shell's group kill)."""
import asyncio
import os
import subprocess
import sys
import textwrap
import time

from fastapi import APIRouter, FastAPI

from workspace.app import AppState
from workspace.children import CHILDREN, process_table

from .conftest import FIXTURES


def live_in_group(pgid: int) -> list[int]:
    return [pid for pid, (_, g, stat) in process_table().items() if g == pgid and not stat.startswith("Z")]


def alive(pid: int) -> bool:
    row = process_table().get(pid)
    return bool(row) and not row[2].startswith("Z")


async def wait_for(cond, timeout=15.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        if r := cond():
            return r
        await asyncio.sleep(0.05)
    raise AssertionError("timed out")


async def test_shutdown_ends_commands_ptys_and_stdio_servers(tmp_path, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/sh")  # no login-shell startup files in the test
    s = AppState(db_path=tmp_path / "q.db")
    from workspace.features import mcp_feature, terminal

    mcp_feature.register(FastAPI(), APIRouter(), s)
    terminal.register(FastAPI(), APIRouter(), s)
    sid = s.store.create(folder=str(tmp_path))["id"]
    try:
        await _start_children_and_shut_down(s, sid, tmp_path)
    finally:
        await s.shutdown()  # idempotent; a failed assertion must not leak processes into the next tests


async def _start_children_and_shut_down(s, sid, tmp_path):
    # 1. A command that ignores SIGTERM (so only the SIGKILL escalation ends it).
    j1 = s.jobs.start(sid, "command", "stubborn")
    t1 = asyncio.create_task(s.commands.run(j1, "trap '' TERM HUP; sleep 300", tmp_path, timeout=600))
    s.jobs.attach(j1, t1)
    p1 = (await wait_for(lambda: s.jobs.procs.get(j1))).pid
    await wait_for(lambda: len(live_in_group(p1)) >= 2)  # sh + sleep
    # 2. A command that finished but left a background process in its group.
    before = set(CHILDREN.groups())
    j2 = s.jobs.start(sid, "command", "leaves a server running")
    code, out = await s.commands.run(j2, "sleep 301 > /dev/null 2>&1 & echo started", tmp_path)
    assert code == 0 and "started" in out
    (p2,) = set(CHILDREN.groups()) - before  # still registered: its group isn't empty
    assert live_in_group(p2), "the background sleep should still be running"
    # 3. A terminal tab (an interactive shell ignores SIGTERM).
    pty = s.extensions["terminal"]
    pty.open("t1", str(tmp_path))
    p3 = pty.ptys["t1"].pid
    # 4. An MCP stdio server.
    s.db.insert("mcp_servers", {"name": "demo", "transport": "stdio", "command": sys.executable,
                                "args": [str(FIXTURES / "mcp" / "demo_server.py")], "env": {}, "headers": {},
                                "enabled_default": 1, "shared": 0})
    conn = await s.mcp.connect("demo")
    assert conn.pids, "the stdio server's process should be tracked"
    p4 = conn.pids[0]

    groups = CHILDREN.groups()
    for p in (p1, p2, p3, p4):
        assert p in groups, (p, groups)
        assert live_in_group(p)

    t0 = time.monotonic()
    await s.shutdown()
    took = time.monotonic() - t0
    for p in (p1, p2, p3, p4):
        assert not live_in_group(p), f"process group {p} survived shutdown: {live_in_group(p)}"
    assert took < 8, f"shutdown took {took:.1f}s; the desktop shell kills the backend after 12s"
    assert not ({p1, p2, p3, p4} & set(CHILDREN.groups()))


def test_never_signals_a_group_that_is_not_ours(tmp_path):
    """A pgid whose leader is alive but isn't our descendant (PID reuse) is left alone."""
    out = subprocess.run([sys.executable, "-c", textwrap.dedent("""
        import subprocess
        p = subprocess.Popen(["sleep", "300"], start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(p.pid)
    """)], capture_output=True, text=True, check=True).stdout
    stranger = int(out.split()[0])  # reparented to init: not ours any more
    try:
        assert alive(stranger)
        CHILDREN.track(stranger, "job")
        CHILDREN.terminate_all(grace=0.2, kill_wait=0.2)
        assert alive(stranger)
        # Our own group is never registered.
        CHILDREN.track(os.getpid(), "job")
        assert os.getpgrp() not in CHILDREN.groups()
    finally:
        os.kill(stranger, 9)


def test_parent_watchdog_ends_children_when_shutdown_hangs(tmp_path):
    """--parent-pid: the shell is gone and the clean shutdown hangs: the watchdog still ends the
    children and exits."""
    script = tmp_path / "hung_backend.py"
    script.write_text(textwrap.dedent("""
        import signal, subprocess, sys, time
        import workspace.__main__ as m
        from workspace.children import CHILDREN

        m.WATCHDOG_POLL_S = 0.1
        m.WATCHDOG_DEADLINE_S = 0.5
        signal.signal(signal.SIGTERM, lambda *a: None)  # a backend whose shutdown never finishes
        parent = subprocess.Popen(["sleep", "0.5"])
        child = subprocess.Popen(["sleep", "300"], start_new_session=True, stdout=subprocess.DEVNULL)
        CHILDREN.track(child.pid, "job")
        print(child.pid, flush=True)
        m._watch_parent(parent.pid)
        while True:
            parent.poll()  # reap it, so it's really gone
            time.sleep(0.05)
    """))
    p = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE, text=True)
    try:
        child = int(p.stdout.readline())
        assert p.wait(timeout=20) == 1
        t = time.monotonic()
        while alive(child) and time.monotonic() - t < 5:
            time.sleep(0.05)
        assert not alive(child)
    finally:
        if p.poll() is None:
            p.kill()


def _orphan_group() -> tuple[int, int]:
    """A group whose leader exited, leaving a member reparented to init: (pgid, member pid)."""
    out = subprocess.run([sys.executable, "-c", textwrap.dedent("""
        import subprocess
        p = subprocess.Popen(["sh", "-c", "sleep 300 & echo $!"], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        print(p.pid, p.stdout.readline().strip())
        p.wait()
    """)], capture_output=True, text=True, check=True).stdout
    pgid, member = map(int, out.split())
    return pgid, member


def test_reused_group_number_with_its_leader_gone_is_left_alone():
    """Our group ended and its number came back as somebody else's group whose leader has exited too:
    the members aren't ours (they started after we saw our leader exit), so they're never signalled."""
    from workspace.children import ChildProcesses, _Group, start_time

    pgid, member = _orphan_group()
    try:
        assert alive(member) and not alive(pgid)
        reg = ChildProcesses()
        # What we'd have recorded for our own (long gone) group with this number.
        reg._groups[pgid] = _Group("job", start=time.time() - 120, sid=pgid, leader_gone=start_time(member) - 60)
        reg.terminate_all(grace=0.2, kill_wait=0.2)
        assert alive(member) and pgid not in reg.groups()  # left alone, and the stale entry is pruned
        # A different session than the one our child created: not ours either.
        reg._groups[pgid] = _Group("job", start=None, sid=pgid + 1)
        reg.terminate_all(grace=0.2, kill_wait=0.2)
        assert alive(member)
        # Same session, and the member was running when the leader was seen to exit: ours, ended.
        reg._groups[pgid] = _Group("job", start=None, sid=pgid, leader_gone=time.time())
        res = reg.terminate_all(grace=1.0, kill_wait=1.0)
        assert res["terminated"] == [pgid]
        t = time.monotonic()
        while alive(member) and time.monotonic() - t < 3:
            time.sleep(0.05)
        assert not alive(member)
    finally:
        try:
            os.kill(member, 9)
        except ProcessLookupError:
            pass


def test_live_leader_with_another_start_time_is_left_alone():
    from workspace.children import ChildProcesses, start_time

    p = subprocess.Popen(["sleep", "300"], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        reg = ChildProcesses()
        reg.track(p.pid, "job")
        g = reg._groups[p.pid]
        assert g.sid == p.pid and abs(g.start - start_time(p.pid)) < 0.01 and abs(g.start - time.time()) < 5
        g.start -= 30  # as if the number now belonged to a process started later than ours
        reg.terminate_all(grace=0.2, kill_wait=0.2)
        assert p.poll() is None and p.pid not in reg.groups()
        reg.track(p.pid, "job")
        assert reg.terminate_all(grace=1.0, kill_wait=1.0)["terminated"] == [p.pid]
        assert p.wait(timeout=5) is not None
    finally:
        p.kill()
        p.wait()


def test_release_notes_the_leader_exit_and_prunes_ended_groups():
    from workspace.children import ChildProcesses

    reg = ChildProcesses()
    a = subprocess.Popen(["sh", "-c", "sleep 300 > /dev/null 2>&1 &"], start_new_session=True,
                         stdin=subprocess.DEVNULL)
    b = subprocess.Popen(["true"], start_new_session=True, stdin=subprocess.DEVNULL)
    reg.track(a.pid, "job")
    reg.track(b.pid, "job")
    a.wait()
    b.wait()
    try:
        before = time.time()
        reg.release(a.pid)  # its background sleep is still in the group
        assert reg._groups[a.pid].leader_gone >= before
        assert b.pid not in reg.groups()  # ended: pruned even without its own release()
        assert reg.terminate_all(grace=1.0, kill_wait=1.0)["terminated"] == [a.pid]
        assert not live_in_group(a.pid)
    finally:
        for pid in live_in_group(a.pid):
            os.kill(pid, 9)


def test_tracks_a_group_whose_leader_already_exited():
    """`server &` can exit before track() runs (macOS can't read a zombie's pgid): its group, with
    the server still in it, is registered all the same, and quitting ends it."""
    from workspace.children import ChildProcesses

    reg = ChildProcesses()
    a = subprocess.Popen(["sh", "-c", "sleep 300 > /dev/null 2>&1 &"], start_new_session=True,
                         stdin=subprocess.DEVNULL)
    try:
        t = time.monotonic()  # wait for the leader to exit (a zombie until we reap it)
        while (row := process_table().get(a.pid)) and not row[2].startswith("Z") and time.monotonic() - t < 10:
            time.sleep(0.02)
        assert row and row[2].startswith("Z"), row
        assert live_in_group(a.pid), "the background sleep should still be running"
        reg.track(a.pid, "job")
        assert a.pid in reg.groups()
        a.wait()
        reg.release(a.pid)
        assert reg._groups[a.pid].leader_gone is not None
        assert reg.terminate_all(grace=1.0, kill_wait=1.0)["terminated"] == [a.pid]
        assert not live_in_group(a.pid)
    finally:
        a.wait()
        for pid in live_in_group(a.pid):
            os.kill(pid, 9)
