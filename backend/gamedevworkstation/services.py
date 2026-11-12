"""Background jobs, command execution, login-shell environment and file-change tracking."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .children import CHILDREN
from .config import data_dir
from .core.types import new_id
from .db import DB, now
from .events import EventBus

# ------------------------------------------------------------------ environment


def default_shell() -> str:
    return os.environ.get("SHELL") or ("/bin/zsh" if sys.platform == "darwin" else "/bin/bash")


def login_shell_path() -> str | None:
    """GUI apps on macOS don't inherit the shell's PATH; ask the login shell for it."""
    shell = default_shell()
    try:
        out = subprocess.run([shell, "-lic", 'echo "__PATH__=$PATH"'], capture_output=True, text=True,
                             timeout=10, stdin=subprocess.DEVNULL)
        for line in out.stdout.splitlines():
            if line.startswith("__PATH__="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


def fix_path() -> str:
    """Merge the login shell's PATH (and Homebrew) into this process's PATH."""
    parts: list[str] = []
    for src in ((login_shell_path() or ""), os.environ.get("PATH", ""),
                "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"):
        for p in src.split(":"):
            if p and p not in parts:
                parts.append(p)
    os.environ["PATH"] = ":".join(parts)
    return os.environ["PATH"]


def tool_available(name: str) -> str | None:
    return shutil.which(name)


# ------------------------------------------------------------------------- jobs


class _ProcTable(dict):
    """jobs.procs: every process put here (commands, Codex CLI units and turns) has its process
    group registered with CHILDREN, so quitting ends it even if its job never finished."""

    def __setitem__(self, jid: str, proc: asyncio.subprocess.Process) -> None:
        CHILDREN.track(proc.pid, "job")
        super().__setitem__(jid, proc)

    def pop(self, jid: str, *default: Any) -> Any:
        proc = super().pop(jid, *default)
        if proc is not None:
            CHILDREN.release(proc.pid)
        return proc


class Jobs:
    """Background tasks shown in the side panel: subagents, commands, Codex CLI, ElevenLabs."""

    def __init__(self, db: DB, bus: EventBus):
        self.db, self.bus = db, bus
        self.tasks: dict[str, asyncio.Task] = {}
        self.procs: dict[str, asyncio.subprocess.Process] = _ProcTable()
        self._tails: dict[str, str] = {}
        self._sids: dict[str, str | None] = {}

    def start(self, session_id: str | None, kind: str, title: str, meta: dict[str, Any] | None = None,
              status: str = "running") -> str:
        jid = new_id("job_")
        row = {"id": jid, "session_id": session_id, "kind": kind, "title": title[:300], "status": status,
               "started_at": now(), "meta": json.dumps(meta or {}, default=str)}
        self.db.insert("jobs", row)
        self._sids[jid] = session_id
        self.bus.publish("job.updated", self.get(jid), session_id)
        return jid

    def attach(self, jid: str, task: asyncio.Task) -> None:
        self.tasks[jid] = task
        task.add_done_callback(lambda t: self.tasks.pop(jid, None))

    def get(self, jid: str) -> dict | None:
        r = self.db.one("SELECT * FROM jobs WHERE id=?", [jid])
        if r:
            r["meta"] = json.loads(r["meta"])
            r["elapsed_s"] = (r["ended_at"] or time.time()) - r["started_at"]
        return r

    def update(self, jid: str, **fields: Any) -> None:
        if "meta" in fields:
            cur = (self.get(jid) or {}).get("meta", {})
            fields["meta"] = {**cur, **fields["meta"]}
        self.db.update("jobs", "id", jid, fields)
        j = self.get(jid)
        if j:
            self.bus.publish("job.updated", j, j["session_id"])

    def log(self, jid: str, text: str) -> None:
        tail = (self._tails.get(jid, "") + text)[-4000:]
        self._tails[jid] = tail
        if jid not in self._sids:  # looked up once per job, not per chunk
            self._sids[jid] = (self.db.one("SELECT session_id FROM jobs WHERE id=?", [jid]) or {}).get("session_id")
        self.bus.publish("job.log", {"id": jid, "text": text}, self._sids[jid])

    def finish(self, jid: str, status: str = "done", **meta: Any) -> None:
        self._sids.pop(jid, None)
        fields: dict[str, Any] = {"status": status, "ended_at": now(), "log_tail": self._tails.pop(jid, "")[-4000:]}
        if meta:
            fields["meta"] = meta
        self.update(jid, **fields)

    async def cancel(self, jid: str) -> bool:
        p = self.procs.get(jid)
        if p and p.returncode is None:
            _kill_tree(p)
        t = self.tasks.get(jid)
        if t and not t.done():
            t.cancel()
        j = self.get(jid)
        if j and j["status"] in ("running", "queued"):
            self.finish(jid, "cancelled")
            return True
        return False

    def list(self, session_id: str | None = None, limit: int = 50) -> list[dict]:
        sql, p = "SELECT id FROM jobs", []
        if session_id:
            sql += " WHERE session_id=?"
            p = [session_id]
        rows = self.db.all(sql + " ORDER BY started_at DESC LIMIT ?", [*p, limit])
        return [j for r in rows if (j := self.get(r["id"]))]

    def mark_orphans(self) -> None:
        """On startup, anything still 'running' died with the previous process."""
        self.db.execute("UPDATE jobs SET status='failed', ended_at=?, log_tail=log_tail || '\n[app restarted]' "
                        "WHERE status IN ('running','queued')", [now()])

    async def shutdown(self) -> None:
        for jid in list(self.procs):
            p = self.procs[jid]
            if p.returncode is None:
                _kill_tree(p)
        for t in list(self.tasks.values()):
            t.cancel()


def _kill_tree(p: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(p.pid, 15)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            p.terminate()
        except ProcessLookupError:
            pass


# --------------------------------------------------------------------- commands


_HEAD_CAP, _TAIL_CAP, _EVENT_CAP, _FLUSH_S = 16_000, 256_000, 64_000, 0.1
KEEP_LOGS = 200  # full command logs kept in data_dir/jobs (oldest removed first)


def _prune_logs(d: Path) -> None:
    try:
        for f in sorted(d.glob("job_*.log"), key=lambda f: f.stat().st_mtime)[:-KEEP_LOGS]:
            f.unlink(missing_ok=True)
    except OSError:
        pass


class Commands:
    """Runs agent shell commands; output streams to the job log and the agent's terminal tab."""

    def __init__(self, jobs: Jobs, bus: EventBus):
        self.jobs, self.bus = jobs, bus

    async def run(self, jid: str, cmd: str, cwd: Path, timeout: int = 120) -> tuple[int, str]:
        code, text, _ = await self.run_exec(jid, [default_shell(), "-lc", cmd], cwd, timeout, display=cmd)
        return code, text

    async def run_exec(self, jid: str, argv: list[str], cwd: Path, timeout: float = 120, *,
                       env: dict[str, str] | None = None, display: str | None = None,
                       capture_stdout: bool = False, on_start: Any = None) -> tuple[int, str, str]:
        """Run argv (no shell) as job `jid` in its own process group; the output streams to the job
        log and the agent's terminal tab (head + bounded tail kept in memory, the full log in
        data_dir/jobs). capture_stdout: stdout is kept apart (returned as the third value, not
        streamed; e.g. a JSON envelope) and only stderr streams. on_start(proc) is called once the
        process exists. Returns (exit code, streamed text, captured stdout); 124 = timed out."""
        j = self.jobs.get(jid) or {}
        sid = j.get("session_id")
        self.bus.publish("terminal.agent_command", {"job_id": jid, "command": display or " ".join(argv),
                                                    "cwd": str(cwd), "kind": j.get("kind")}, sid)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=str(cwd), stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE if capture_stdout else asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
                env=env if env is not None else {**os.environ, "TERM": "dumb", "NO_COLOR": "1"})
        except OSError as e:  # the program or the folder is gone: the job must not stay "running"
            self.jobs.finish(jid, "failed", error=str(e)[:300])
            self.bus.publish("terminal.agent_exit", {"job_id": jid, "exit_code": 127}, sid)
            raise
        self.jobs.procs[jid] = proc
        if on_start is not None:
            on_start(proc)
        captured: list[bytes] = []
        # The full output goes to a file; memory keeps only the head and a bounded tail, so a chatty
        # command (a build printing 500 MB) can't exhaust memory or flood the WebSocket.
        path = data_dir() / "jobs" / f"{jid}.log"
        fh = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _prune_logs(path.parent)
            fh = path.open("wb")
            self.jobs.update(jid, meta={"log_path": str(path)})
        except OSError:
            fh = None
        st = {"head": "", "tail": "", "total": 0, "pending": "", "dropped": 0}

        def feed(s: str) -> None:
            st["total"] += len(s)
            if len(st["head"]) < _HEAD_CAP:
                st["head"] += s[:_HEAD_CAP - len(st["head"])]
            st["tail"] += s
            if len(st["tail"]) > 2 * _TAIL_CAP:
                st["tail"] = st["tail"][-_TAIL_CAP:]
            if fh and not fh.closed:  # the timeout note is fed after the file is closed
                fh.write(s.encode())

        def flush() -> None:
            """One terminal.output + job.log event per flush; a huge burst sends only its last 64 KB."""
            s, st["pending"] = st["pending"], ""
            if not s:
                return
            if len(s) > _EVENT_CAP:
                s = f"…[skipped {len(s) - _EVENT_CAP} chars]…\n" + s[-_EVENT_CAP:]
            self.jobs.log(jid, s)
            self.bus.publish("terminal.output", {"tab": f"agent:{jid}", "data": s}, sid)

        async def flusher() -> None:
            while True:
                await asyncio.sleep(_FLUSH_S)
                flush()

        async def pump() -> None:
            src = proc.stderr if capture_stdout else proc.stdout
            assert src
            while data := await src.read(65536):
                s = data.decode(errors="replace")
                feed(s)
                st["pending"] += s
                if len(st["pending"]) > _EVENT_CAP:
                    flush()

        async def grab() -> None:
            if not capture_stdout:
                return
            assert proc.stdout
            size = 0
            while data := await proc.stdout.read(65536):
                if size < 8 * _TAIL_CAP:  # an envelope is small; never hold an unbounded stdout
                    captured.append(data)
                    size += len(data)

        ftask = asyncio.ensure_future(flusher())

        def end() -> None:
            """Stop the flusher, send what is pending, close the file. Safe to call twice."""
            ftask.cancel()
            flush()
            if fh and not fh.closed:
                fh.close()

        try:
            await asyncio.wait_for(asyncio.gather(pump(), grab(), proc.wait()), timeout)
            code = proc.returncode or 0
            end()
            self.jobs.finish(jid, "done" if code == 0 else "failed", exit_code=code)
        except asyncio.TimeoutError:
            _kill_tree(proc)
            end()
            feed(f"\n[timed out after {timeout}s]")
            code = 124
            self.jobs.finish(jid, "failed", exit_code=code)
        except asyncio.CancelledError:
            _kill_tree(proc)
            end()
            self.jobs.finish(jid, "cancelled")
            raise
        finally:
            end()
            self.jobs.procs.pop(jid, None)
        self.bus.publish("terminal.agent_exit", {"job_id": jid, "exit_code": code}, sid)
        out = b"".join(captured).decode(errors="replace")
        tail, total = st["tail"], st["total"]
        if len(tail) == total:  # never trimmed: the whole output is here
            return code, tail, out
        tail = tail[-_TAIL_CAP:]
        note = f"\n…[{total - len(st['head']) - len(tail)} chars omitted; full output in {path}]…\n"
        text = st["head"] + note + tail
        return code, text, out


# ---------------------------------------------------------------------- changes


SNAPSHOT_MAX_BYTES = 5 * 1024 * 1024  # larger files are noted as "too large to snapshot" (no revert)


class Changes:
    """Snapshots files before each agent write so the Changes card can diff and revert."""

    def __init__(self, db: DB, bus: EventBus):
        self.db, self.bus = db, bus

    def snapshot(self, session_id: str, path: Path) -> None:
        # Keep only the first snapshot per path: that's the "before" state for the session.
        if self.db.one("SELECT id FROM snapshots WHERE session_id=? AND path=?", [session_id, str(path)]):
            return
        too_large = path.is_file() and path.stat().st_size > SNAPSHOT_MAX_BYTES
        content = path.read_bytes() if path.is_file() and not too_large else None
        self.db.insert("snapshots", {"session_id": session_id, "path": str(path), "content": content, "ts": now(),
                                     "too_large": int(too_large)})

    def notify(self, session_id: str, path: Path, provider: str | None = None, model: str | None = None) -> None:
        self.bus.publish("file.changed", {"path": str(path)}, session_id)
