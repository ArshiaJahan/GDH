"""Entry point.

Development:  `uv run workspace`  → starts on 127.0.0.1 and opens the UI in a browser.
Desktop app:  the Tauri shell runs the bundled backend with
              --port <n> --no-browser --parent-pid <pid> and the session token in the
              WORKSPACE_TOKEN env var (not on the command line, where `ps` shows it to every
              user), and waits for the "WORKSPACE_READY port=<n>" line and /health.
              --token still works for development.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


WATCHDOG_POLL_S = 2
WATCHDOG_DEADLINE_S = 10  # after asking for a clean shutdown, how long before ending children ourselves


def _watch_parent(pid: int) -> None:
    """Exit when the desktop shell goes away (crash included).

    SIGTERM to ourselves runs the normal shutdown, which ends every child process group. Nobody
    is left to SIGKILL us if that hangs, so after WATCHDOG_DEADLINE_S the watchdog ends the
    children itself and exits hard."""
    def gone() -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        return os.getppid() == 1  # reparented to launchd: parent died

    def loop() -> None:
        while not gone():
            time.sleep(WATCHDOG_POLL_S)
        logging.getLogger("workspace").warning("parent %s is gone; shutting down", pid)
        os.kill(os.getpid(), 15)  # SIGTERM → uvicorn shuts down cleanly
        time.sleep(WATCHDOG_DEADLINE_S)
        from .children import CHILDREN

        CHILDREN.terminate_all(grace=1.0, kill_wait=1.0)
        os._exit(1)

    threading.Thread(target=loop, daemon=True).start()


def _setup_logging() -> None:
    from .config import logs_dir

    h = logging.handlers.RotatingFileHandler(logs_dir() / "backend.log", maxBytes=5_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    # SDK debug logs can include request headers; keep them quiet.
    for noisy in ("httpx", "httpx2", "anthropic", "openai", "elevenlabs"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> None:
    ap = argparse.ArgumentParser(prog="workspace")
    ap.add_argument("--port", type=int, default=int(os.environ.get("WORKSPACE_PORT", "8765")),
                    help="0 = pick a random free port")
    ap.add_argument("--token", help="session token (default: $WORKSPACE_TOKEN, else random)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--parent-pid", type=int)
    args = ap.parse_args()
    # Read once and drop it, so commands, terminals and MCP servers started later don't inherit it.
    env_token = os.environ.pop("WORKSPACE_TOKEN", None)

    from .services import fix_path

    fix_path()
    _setup_logging()

    port = args.port or _free_port()
    token = args.token or env_token or secrets.token_urlsafe(24)
    if args.parent_pid:
        os.environ["WORKSPACE_PARENT_PID"] = str(args.parent_pid)  # the app to quit when installing an update
        _watch_parent(args.parent_pid)

    import uvicorn

    from .server import create_app

    app = create_app(token)
    from .perms import harden_app_dirs

    harden_app_dirs()  # after create_app: the database and config exist by now
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws_ping_interval=20,
                            timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)

    url = f"http://127.0.0.1:{port}/?token={token}"
    print(f"WORKSPACE_READY port={port}", flush=True)
    if not args.no_browser:
        print(f"Workspace running at {url}", flush=True)

        def _open() -> None:
            time.sleep(1.0)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()
    try:
        asyncio.run(server.serve())
    finally:
        # A second Ctrl-C / SIGTERM makes uvicorn skip the lifespan shutdown; children must still go.
        from .children import CHILDREN

        CHILDREN.terminate_all(grace=1.0, kill_wait=1.0)
    sys.exit(0)


if __name__ == "__main__":
    main()
