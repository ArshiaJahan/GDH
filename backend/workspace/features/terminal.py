"""Terminal drawer: PTY tabs running the user's login shell (zsh on macOS).

Over the single WebSocket the UI sends
  {"op": "term.open", "tab", "cwd", "cols", "rows"} · {"op": "term.input", "tab", "data"}
  {"op": "term.resize", "tab", "cols", "rows"} · {"op": "term.close", "tab"}
and receives "terminal.output" / "terminal.exit" events. Agent commands stream into
their own read-only tabs ("agent:<job id>") from services.Commands.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, FastAPI

from ..children import CHILDREN
from ..services import default_shell

if TYPE_CHECKING:
    from ..app import AppState

MAX_TABS = 12


class PtyManager:
    def __init__(self, app: "AppState"):
        self.app = app
        self.ptys: dict[str, object] = {}
        self.scrollback: dict[str, str] = {}

    def open(self, tab: str, cwd: str | None, cols: int = 100, rows: int = 30) -> None:
        if tab in self.ptys:
            return
        if len(self.ptys) >= MAX_TABS:
            self.app.bus.publish("terminal.output", {"tab": tab, "data": "\r\n[too many terminal tabs open]\r\n"})
            return
        from ptyprocess import PtyProcess

        d = Path(cwd).expanduser() if cwd else Path.home()
        if not d.is_dir():
            d = Path.home()
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor", "TERM_PROGRAM": "Workspace"}
        shell = default_shell()
        proc = PtyProcess.spawn([shell, "-l"], cwd=str(d), env=env, dimensions=(rows, cols))
        self.ptys[tab] = proc
        CHILDREN.track(proc.pid, "pty")  # its own session (setsid): quitting must end it explicitly
        loop = asyncio.get_running_loop()
        loop.add_reader(proc.fd, self._on_readable, tab)

    def _on_readable(self, tab: str) -> None:
        proc = self.ptys.get(tab)
        if proc is None:
            return
        try:
            data = os.read(proc.fd, 65536)  # type: ignore[attr-defined]
        except OSError:
            data = b""
        if not data:
            self._closed(tab)
            return
        text = data.decode(errors="replace")
        self.scrollback[tab] = (self.scrollback.get(tab, "") + text)[-200_000:]
        self.app.bus.publish("terminal.output", {"tab": tab, "data": text})

    def _closed(self, tab: str) -> None:
        proc = self.ptys.pop(tab, None)
        if proc is None:
            return
        try:
            asyncio.get_running_loop().remove_reader(proc.fd)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            proc.terminate(force=True)  # type: ignore[attr-defined]
        except Exception:
            pass
        CHILDREN.release(proc.pid)  # type: ignore[attr-defined]
        self.app.bus.publish("terminal.exit", {"tab": tab})

    def write(self, tab: str, data: str) -> None:
        proc = self.ptys.get(tab)
        if proc is not None:
            proc.write(data.encode())  # type: ignore[attr-defined]

    def resize(self, tab: str, cols: int, rows: int) -> None:
        proc = self.ptys.get(tab)
        if proc is not None and cols > 0 and rows > 0:
            proc.setwinsize(rows, cols)  # type: ignore[attr-defined]

    def close(self, tab: str) -> None:
        self._closed(tab)
        self.scrollback.pop(tab, None)

    async def handle(self, msg: dict) -> None:
        op, tab = msg.get("op", ""), str(msg.get("tab", ""))
        if not op.startswith("term.") or not tab or tab.startswith("agent:"):
            return
        if op == "term.open":
            self.open(tab, msg.get("cwd"), int(msg.get("cols", 100)), int(msg.get("rows", 30)))
        elif op == "term.input":
            self.write(tab, str(msg.get("data", "")))
        elif op == "term.resize":
            self.resize(tab, int(msg.get("cols", 0)), int(msg.get("rows", 0)))
        elif op == "term.close":
            self.close(tab)

    async def aclose(self) -> None:
        for tab in list(self.ptys):
            self._closed(tab)


def register(app_: FastAPI, api: APIRouter, S: "AppState") -> None:
    mgr = PtyManager(S)
    S.extensions["ws_handler"] = mgr
    S.extensions["terminal"] = mgr

    @api.get("/terminal/tabs")
    async def tabs() -> list[dict]:
        return [{"tab": t, "scrollback": mgr.scrollback.get(t, "")[-50_000:]} for t in mgr.ptys]
