"""procs: process groups on POSIX, process trees on Windows (this file also runs on the Windows CI job)."""
import os
import subprocess
import sys
import time

from gamedevworkstation import procs


def _wait_gone(pid: int, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not procs.pid_exists(pid):
            return True
        time.sleep(0.05)
    return False


def test_pid_exists():
    assert procs.pid_exists(os.getpid())
    assert not procs.pid_exists(0) and not procs.pid_exists(-1)


def test_kill_group_ends_the_child_and_its_children():
    # A child that starts a grandchild, both sleeping: ending the group/tree ends both.
    code = ("import subprocess, sys, time; "
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "print(g.pid, flush=True); time.sleep(60)")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, **procs.NEW_GROUP)
    grandchild = int(p.stdout.readline())
    assert procs.pid_exists(p.pid) and procs.pid_exists(grandchild)
    assert procs.getpgid(p.pid) == p.pid
    procs.kill_group(procs.getpgid(p.pid), procs.SIGKILL)
    p.wait(timeout=10)
    assert _wait_gone(grandchild)


def test_kill_group_on_a_finished_process_raises_lookup_error():
    p = subprocess.Popen([sys.executable, "-c", "pass"], **procs.NEW_GROUP)
    p.wait(timeout=10)
    time.sleep(0.1)
    try:
        procs.kill_group(p.pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("expected ProcessLookupError")


def test_shell_argv():
    argv = procs.shell_argv("echo hi", "sh")
    if procs.WINDOWS:
        assert argv == ["sh", "-NoProfile", "-NonInteractive", "-Command", "echo hi"]
    else:
        assert argv == ["sh", "-lc", "echo hi"]
