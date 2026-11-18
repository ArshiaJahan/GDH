"""Process groups on POSIX, process trees on Windows.

The backend runs every child (agent commands, Codex and Claude CLI runs, Unity CLI jobs, MCP
servers) in a group of its own so a cancel or quit can end the whole tree. On macOS and Linux
that's a new session (`start_new_session=True`) ended with `os.killpg`. Windows has no process
groups in that sense: children start in a new process group without a console window, and a
tree is ended with `taskkill /T /F` (console programs ignore a polite close, so it is always
forced).

On POSIX every helper here is exactly the os call it stands for.
"""
from __future__ import annotations

import os
import signal
import subprocess

WINDOWS = os.name == "nt"

SIGTERM = signal.SIGTERM
SIGKILL = getattr(signal, "SIGKILL", 9)

#: kwargs for subprocess.Popen / asyncio.create_subprocess_exec: a group of the child's own.
NEW_GROUP: dict = (
    {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}  # type: ignore[attr-defined]
    if WINDOWS else {"start_new_session": True}
)
#: kwargs that only hide the console window of a short-lived helper on Windows.
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}  # type: ignore[attr-defined]

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def pid_exists(pid: int) -> bool:
    """Is a process with this pid running? (Never `os.kill(pid, 0)` on Windows: there signal 0 is
    CTRL_C_EVENT, sent to a whole console group.)"""
    if pid <= 0:
        return False
    if WINDOWS:
        import ctypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return k32.GetLastError() == 5  # ERROR_ACCESS_DENIED: exists, not ours
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == _STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def getpgid(pid: int) -> int:
    """The child's group id; on Windows the child itself leads its tree."""
    return pid if WINDOWS else os.getpgid(pid)


def kill_group(pgid: int, sig: int) -> None:
    """`os.killpg(pgid, sig)` on POSIX. On Windows: sig 0 checks the leader exists (raising
    ProcessLookupError like killpg), anything else ends the leader's whole tree with taskkill."""
    if not WINDOWS:
        os.killpg(pgid, sig)
        return
    if sig == 0:
        if not pid_exists(pgid):
            raise ProcessLookupError(pgid)
        return
    r = subprocess.run(["taskkill", "/PID", str(pgid), "/T", "/F"], capture_output=True, **NO_WINDOW)
    if r.returncode != 0 and not pid_exists(pgid):
        raise ProcessLookupError(pgid)


def shell_argv(cmd: str, shell: str) -> list[str]:
    """Run `cmd` through the user's shell: a login shell on POSIX, PowerShell on Windows."""
    if WINDOWS:
        return [shell, "-NoProfile", "-NonInteractive", "-Command", cmd]
    return [shell, "-lc", cmd]
