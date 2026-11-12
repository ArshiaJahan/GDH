"""`make app-test`: launch the built app, check the backend, providers, one message on
claude.fast, then quit and confirm nothing is left running: neither the backend nor any process
it started (commands, Codex CLI, terminals and MCP servers run in their own process groups, so the
shell's group kill alone wouldn't reach them). Prints a pass/fail summary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dist" / "Workspace.app"
RUNTIME = Path.home() / "Library" / "Application Support" / "Workspace" / "runtime.json"
BACKEND_MARK = "Workspace.app/Contents/Resources/backend/workspace-backend"
results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{f' — {detail}' if detail else ''}", flush=True)
    return ok


def call(rt: dict, path: str, body: dict | None = None, method: str | None = None, timeout: float = 30):
    req = urllib.request.Request(f"http://127.0.0.1:{rt['port']}{path}", method=method or ("POST" if body is not None else "GET"),
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {rt['token']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def backend_pids() -> list[str]:
    out = subprocess.run(["pgrep", "-f", BACKEND_MARK], capture_output=True, text=True).stdout
    return [p for p in out.split() if p]


def process_rows() -> dict[int, tuple[int, int, str, str]]:
    """pid → (ppid, pgid, stat, command) for every process."""
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,pgid=,stat=,command="], capture_output=True, text=True).stdout
    rows = {}
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            rows[int(parts[0])] = (int(parts[1]), int(parts[2]), parts[3], parts[4])
    return rows


def backend_children(roots: list[int]) -> dict[int, str]:
    """Every live process the backend started: its descendants, plus everything in the process groups
    those descendants lead (a command's `server &` stays in its group after the shell exits). Only
    processes tied to the backend this way are recorded, so unrelated ones are never flagged."""
    rows = process_rows()
    kids: dict[int, list[int]] = {}
    for pid, (ppid, *_rest) in rows.items():
        kids.setdefault(ppid, []).append(pid)
    found: set[int] = set()
    todo = list(roots)
    while todo:
        for k in kids.get(todo.pop(), []):
            if k not in found:
                found.add(k)
                todo.append(k)
    leaders = {p for p in found if rows[p][1] == p}
    found |= {pid for pid, (_, pgid, _, _) in rows.items() if pgid in leaders}
    return {p: rows[p][3] for p in found - set(roots) if p in rows and not rows[p][2].startswith("Z")}


def still_running(snapshot: dict[int, str]) -> list[str]:
    rows = process_rows()
    return [f"{p} {cmd[:60]}" for p, cmd in snapshot.items()
            if p in rows and rows[p][3] == cmd and not rows[p][2].startswith("Z")]  # same command: not a reused pid


def main() -> int:
    print("Workspace smoke test")
    if not step("app bundle exists", APP.exists(), str(APP)):
        return summary()
    if backend_pids():
        subprocess.run(["osascript", "-e", 'tell application "Workspace" to quit'], capture_output=True)
        time.sleep(3)
    RUNTIME.unlink(missing_ok=True)
    subprocess.run(["open", str(APP)], check=True)

    rt = None
    t0 = time.time()
    while time.time() - t0 < 90:
        if RUNTIME.exists():
            try:
                rt = json.loads(RUNTIME.read_text())
                break
            except json.JSONDecodeError:
                pass
        time.sleep(0.5)
    if not step("app launched and wrote its runtime file", rt is not None):
        return summary()

    healthy = False
    while time.time() - t0 < 120:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{rt['port']}/health", timeout=2) as r:
                healthy = r.status == 200
                break
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.5)
    step("backend health check", healthy, f"port {rt['port']}, {time.time() - t0:.1f}s after launch")
    if not healthy:
        return finish()

    try:
        snap = call(rt, "/api/status/refresh", {}, timeout=60)
        for p in snap["providers"]:
            ok = p["status"] in ("online", "no_key")
            step(f"auth check {p['provider']} ({p['profile']})", ok, p["status"] + (f": {p['error']}" if p.get("error") and p["status"] != "no_key" else ""))
        anthropic_online = any(p["provider"] == "anthropic" and p["status"] == "online" for p in snap["providers"])
    except Exception as e:  # noqa: BLE001
        step("auth checks", False, str(e))
        anthropic_online = False

    try:
        s = call(rt, "/api/sessions", {"title": "Smoke test", "model": "claude.fast", "effort": "low"})
        call(rt, f"/api/sessions/{s['id']}", {"model": "claude.fast", "effort": "low"}, method="PATCH")
        step("open a session", True, s["id"])
        if not anthropic_online:
            step("message on claude.fast", False, "no working Anthropic key — add one in Settings → Accounts")
        else:
            call(rt, f"/api/sessions/{s['id']}/messages", {"text": "Reply with exactly: pong"})
            reply = ""
            while time.time() - t0 < 240:
                if not call(rt, f"/api/sessions/{s['id']}")["running"]:
                    msgs = call(rt, f"/api/sessions/{s['id']}/messages")
                    reply = " ".join(b.get("text", "") for m in msgs if m["role"] == "assistant" for b in m["content"])
                    break
                time.sleep(0.5)
            step("message on claude.fast", "pong" in reply.lower(), reply[:80] or "no reply")
        call(rt, f"/api/sessions/{s['id']}", method="DELETE")
    except Exception as e:  # noqa: BLE001
        step("session and message", False, str(e))
    return finish()


def finish() -> int:
    children = backend_children([int(p) for p in backend_pids()])  # recorded before quitting
    subprocess.run(["osascript", "-e", 'tell application "Workspace" to quit'], capture_output=True)
    t = time.time()
    while time.time() - t < 15 and backend_pids():
        time.sleep(0.5)
    left = backend_pids()
    step("quit leaves no backend processes", not left, f"still running: {' '.join(left)}" if left else "")
    t = time.time()
    while time.time() - t < 3 and still_running(children):
        time.sleep(0.2)
    orphans = still_running(children)
    step("quit leaves no child processes of the backend", not orphans,
         f"still running: {'; '.join(orphans)}" if orphans else f"{len(children)} checked")
    return summary()


def summary() -> int:
    passed = sum(1 for _, ok, _ in results if ok)
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{passed}/{len(results)} passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    print("RESULT: " + ("PASS" if not failed else "FAIL"))
    return 0 if not failed else 1


if __name__ == "__main__":
    if sys.platform != "darwin":
        print("make app-test runs on macOS.")
        sys.exit(1)
    sys.exit(main())
