"""Every child process group the backend starts, so quitting can end them all.

Agent commands, Codex CLI runs, terminal PTYs and MCP stdio servers each run in their own
session (so a cancel can kill a whole tree). That also puts them outside the backend's process
group, which is all the desktop shell kills when it quits. So the backend keeps a registry of
those groups and, on shutdown (and from the --parent-pid watchdog), sends each one SIGTERM,
waits briefly and SIGKILLs whatever is left.

Only groups registered here are signalled, never a blanket "all my children": the update
helper (features/updates.py) is a detached child that must outlive the backend.

PID reuse: a pgid can't be reused while its group exists, but once every member has exited the
number can come back as somebody else's group. So track() records the leader's start time and
session, and at shutdown a registered group is only signalled if a live member is still in that
session and either the leader is alive, a descendant of this process and started when recorded,
or (the leader gone) a member descends from this process or was already running when the leader
was seen to exit. Entries whose group has ended are pruned on every track/release and at shutdown.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass

log = logging.getLogger(__name__)

TERM_GRACE_S = 1.5  # SIGTERM → SIGKILL
KILL_WAIT_S = 1.0  # SIGKILL → give up (only an unkillable process runs this out)
POLL_S = 0.05


def process_table() -> dict[int, tuple[int, int, str]]:
    """pid → (ppid, pgid, stat) for every process on the machine (`ps`, macOS and Linux)."""
    try:
        p = subprocess.Popen(["ps", "-A", "-o", "pid=,ppid=,pgid=,stat="], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True)
        out, _ = p.communicate(timeout=5)
    except (OSError, subprocess.SubprocessError):
        return {}
    table: dict[int, tuple[int, int, str]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            table[int(parts[0])] = (int(parts[1]), int(parts[2]), parts[3])
    table.pop(p.pid, None)  # ps itself
    return table


class _BsdInfo(ctypes.Structure):  # struct proc_bsdinfo, <sys/proc_info.h>
    _fields_ = [("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32),
                ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
                ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32), ("rgid", ctypes.c_uint32),
                ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
                ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32), ("nfiles", ctypes.c_uint32),
                ("pgid", ctypes.c_uint32), ("pjobc", ctypes.c_uint32), ("tdev", ctypes.c_uint32),
                ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32), ("start_tvsec", ctypes.c_uint64),
                ("start_tvusec", ctypes.c_uint64)]


_libproc: ctypes.CDLL | None | bool = None


def _darwin_start(pid: int) -> float | None:
    global _libproc
    if _libproc is None:
        try:
            _libproc = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib", use_errno=True)
        except OSError:
            _libproc = False
    if not _libproc:
        return _ps_start(pid)
    info = _BsdInfo()
    n = _libproc.proc_pidinfo(pid, 3, ctypes.c_uint64(0), ctypes.byref(info), ctypes.sizeof(info))  # PROC_PIDTBSDINFO
    if n != ctypes.sizeof(info) or info.pid != pid:
        return None
    return info.start_tvsec + info.start_tvusec / 1e6


def _linux_start(pid: int) -> float | None:
    try:
        stat = open(f"/proc/{pid}/stat").read()
        ticks = int(stat[stat.rindex(")") + 2:].split()[19])  # field 22, starttime
        btime = next(int(ln.split()[1]) for ln in open("/proc/stat") if ln.startswith("btime "))
        return btime + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def _ps_start(pid: int) -> float | None:
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5,
                             stdin=subprocess.DEVNULL, env={**os.environ, "LC_ALL": "C"}).stdout.strip()
        return time.mktime(time.strptime(out, "%a %b %d %H:%M:%S %Y")) if out else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def start_time(pid: int) -> float | None:
    """When a process started (epoch seconds), or None if it's gone or can't be read."""
    if sys.platform == "darwin":
        return _darwin_start(pid)
    if sys.platform.startswith("linux"):
        return _linux_start(pid)
    return _ps_start(pid)


def _sid(pid: int) -> int | None:
    try:
        return os.getsid(pid)
    except OSError:
        return None


def _live(stat: str) -> bool:
    return not stat.startswith("Z")


def _descends_from(pid: int, ancestor: int, table: dict[int, tuple[int, int, str]]) -> bool:
    seen = 0
    while pid in table and seen < 256:
        ppid = table[pid][0]
        if ppid == ancestor:
            return True
        if ppid <= 1:
            return False
        pid, seen = ppid, seen + 1
    return False


def _exists(pid: int) -> bool:
    """The pid is taken (a zombie counts: its number can't be reused until it's reaped)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _protected() -> set[int]:
    """Groups never signalled: ours, our parent's, init's."""
    out = {0, 1}
    for f in (os.getpgrp, lambda: os.getpgid(os.getppid())):
        try:
            out.add(f())
        except OSError:
            pass
    return out


@dataclass
class _Group:
    label: str  # pty, job, mcp, …
    start: float | None  # the leader's start time
    sid: int | None  # the leader's session (its own: start_new_session / setsid)
    leader_gone: float | None = None  # when we saw the leader exit with members left in its group


START_SLOP_S = 0.01  # start times are read in µs (macOS), clock ticks (Linux) or seconds (ps)


def _same_start(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < (1.0 if a.is_integer() or b.is_integer()
                                                             else START_SLOP_S)


class ChildProcesses:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._groups: dict[int, _Group] = {}  # pgid → what we know about it

    def track(self, pid: int, label: str) -> None:
        """Register the process group of a child we just started (start_new_session=True / setsid)."""
        try:
            pgid = os.getpgid(pid)
        except OSError:
            # macOS answers ESRCH for a zombie, so a leader that already exited (`server &` returns at
            # once) can't be asked. Until we reap it its pid can't be reused, so a group numbered pid
            # that still has members is the one it created; its start time and session are unreadable.
            if not _exists(pid):
                return
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                return  # no group of its own, or nothing left in it
            except PermissionError:
                pass
            with self._lock:
                self._prune()
                self._groups[pid] = _Group(label, None, None)
            return
        if pgid in _protected():
            return  # in our own group: the shell's group kill already covers it
        entry = _Group(label, start_time(pgid), _sid(pgid))
        with self._lock:
            self._prune()
            self._groups[pgid] = entry

    def release(self, pid: int) -> None:
        """The child exited: forget its group once nothing is left in it. A command that started a
        background process (`server &`) keeps its group registered, so quitting still ends it."""
        with self._lock:
            self._prune()
            g = self._groups.get(pid)
            if g is not None and g.leader_gone is None and not _exists(pid):
                g.leader_gone = time.time()

    def _prune(self) -> None:
        """Drop groups that ended without a release(); note leaders that exited (lock held)."""
        now = time.time()
        for pgid, g in list(self._groups.items()):
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                self._groups.pop(pgid, None)
                continue
            except PermissionError:
                pass
            if g.leader_gone is None and not _exists(pgid):
                g.leader_gone = now

    def groups(self) -> dict[int, str]:
        with self._lock:
            return {pgid: g.label for pgid, g in self._groups.items()}

    # --------------------------------------------------------------- shutdown

    def _ours(self, pgid: int, g: _Group, members: list[int], table: dict[int, tuple[int, int, str]],
              me: int) -> bool:
        """Is the group numbered pgid still the one we registered (not a reused number)?"""
        if g.sid is not None:
            members = [m for m in members if _sid(m) == g.sid]
            if not members:
                return False  # nobody left in the session our child created
        leader = table.get(pgid)
        if leader and _live(leader[2]):
            # Our leader is our own child until it exits; a different start time means a new process.
            return _descends_from(pgid, me, table) and (g.start is None or _same_start(start_time(pgid), g.start))
        if any(_descends_from(m, me, table) for m in members):
            return True
        if g.leader_gone is not None:
            # Members of a reused group all started after ours ended, so after our leader exited.
            return any((t := start_time(m)) is not None and t <= g.leader_gone for m in members)
        return True  # the leader exited unnoticed (no track/release since); the session check above holds

    def _targets(self, table: dict[int, tuple[int, int, str]]) -> dict[int, str]:
        """Registered groups that are still ours, plus groups their members started (e.g. a Codex
        sandbox in a new session) found through the parent tree. Stale entries are dropped."""
        me, protected = os.getpid(), _protected()
        members: dict[int, list[int]] = defaultdict(list)
        for pid, (_, pgid, stat) in table.items():
            if _live(stat):
                members[pgid].append(pid)
        out: dict[int, str] = {}
        with self._lock:
            registered = dict(self._groups)
        for pgid, g in registered.items():
            if pgid in protected or not members.get(pgid):
                stale = True
            else:
                stale = not self._ours(pgid, g, members[pgid], table, me)
                if not stale:
                    out[pgid] = g.label
            if stale:
                with self._lock:
                    if self._groups.get(pgid) is g:
                        del self._groups[pgid]
        # Descendants of those groups that moved to groups of their own.
        roots = {pid for g in out for pid in members[g]}
        for pid, (_, pgid, stat) in table.items():
            if _live(stat) and pgid not in out and pgid not in protected \
                    and any(_descends_from(pid, r, table) for r in roots):
                out[pgid] = "descendant"
        return out

    @staticmethod
    def _alive(groups: dict[int, str]) -> dict[int, str]:
        table = process_table()
        live = {pgid for (_, pgid, stat) in table.values() if _live(stat)}
        return {g: label for g, label in groups.items() if g in live}

    @staticmethod
    def _signal(groups: dict[int, str], sig: int) -> None:
        for pgid, label in groups.items():
            try:
                if sig == signal.SIGTERM and label == "pty":
                    os.killpg(pgid, signal.SIGHUP)  # interactive shells ignore SIGTERM
                os.killpg(pgid, sig)
                if sig == signal.SIGTERM:
                    os.killpg(pgid, signal.SIGCONT)  # stopped jobs can't act on SIGTERM
            except (ProcessLookupError, PermissionError):
                pass

    def terminate_all(self, grace: float = TERM_GRACE_S, kill_wait: float = KILL_WAIT_S) -> dict:
        """SIGTERM every registered group, wait up to `grace`, SIGKILL the rest. Blocking; safe to
        call more than once (and from any thread). Returns what it did, for logs and tests."""
        groups = self._targets(process_table())
        if not groups:
            return {"terminated": [], "killed": [], "left": []}
        self._signal(groups, signal.SIGTERM)
        deadline = time.monotonic() + grace
        alive = self._alive(groups)
        while alive and time.monotonic() < deadline:
            time.sleep(POLL_S)
            alive = self._alive(alive)
        killed = dict(alive)
        if alive:
            self._signal(alive, signal.SIGKILL)
            deadline = time.monotonic() + kill_wait
            while alive and time.monotonic() < deadline:
                time.sleep(POLL_S)
                alive = self._alive(alive)
        if killed:
            log.warning("killed child process groups that ignored SIGTERM: %s",
                        ", ".join(f"{g} ({lbl})" for g, lbl in killed.items()))
        if alive:
            log.error("child process groups still alive after SIGKILL: %s", ", ".join(map(str, alive)))
        with self._lock:
            for g in groups:
                if g not in alive:
                    self._groups.pop(g, None)
        return {"terminated": sorted(groups), "killed": sorted(killed), "left": sorted(alive)}


CHILDREN = ChildProcesses()
