"""AppState: wires every service together. One instance per backend process."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .agent.builtin_tools import register_builtin
from .agent.loop import AgentRunner
from .agent.tools import ToolRegistry
from .approvals import Approvals
from .children import CHILDREN
from .config import Config, data_dir, get_config
from .db import DB
from .events import EventBus
from .features.hookbus import HookBus
from .items import ItemIndex
from .policy import DataPolicy
from .providers.registry import ProviderRegistry
from .services import Changes, Commands, Jobs
from .store import SessionStore
from .usage import UsageTracker

log = logging.getLogger(__name__)


class AppState:
    def __init__(self, config: Config | None = None, db_path: str | Path | None = None):
        self.config = config or get_config()
        self.db = DB(db_path)
        self.bus = EventBus(self.db)
        self.store = SessionStore(self.db, self.bus, self.config)
        self.usage = UsageTracker(self.db, self.bus, self.config)
        self.approvals = Approvals(self.db, self.bus, self.config)
        self.providers = ProviderRegistry(self.config)
        self.jobs = Jobs(self.db, self.bus)
        self.commands = Commands(self.jobs, self.bus)
        self.changes = Changes(self.db, self.bus)
        self.items = ItemIndex(self.db, self.bus)
        self.policy = DataPolicy(self.db, self.config)
        self.turn_started: dict[str, float] = {}
        self.tools = ToolRegistry()
        register_builtin(self.tools)
        self.mcp = None  # set by the MCP manager once loaded
        self.session_tokens: dict[str, str] = {}  # approved above-high tokens for main sessions
        self.hooks = HookBus(self)  # lifecycle hooks (features/hookbus.py); none registered by default
        self.runner = AgentRunner(self)
        self.extensions: dict[str, object] = {}

    def worktrees_root(self, session_id: str) -> Path:
        return data_dir() / "worktrees" / session_id

    def on_startup(self) -> None:
        self.jobs.mark_orphans()
        self.approvals.expire_stale()
        for r in self.db.all("SELECT id FROM sessions WHERE status='running'"):
            self.store.repair_dangling_tool_calls(r["id"])
        self.db.execute("UPDATE sessions SET status='idle' WHERE status='running'")
        for tier, mid in self.config.tiers.items():  # older rows could hold a tier key instead of its model id
            self.db.execute("UPDATE sessions SET model=? WHERE model=?", [mid, tier])

    async def shutdown(self) -> None:
        """Quit: everything here has to finish well inside the desktop shell's 12 s before SIGKILL
        (uvicorn's graceful close takes up to 2 s of that first). Worst case about 6 s."""
        for sid in list(self.runner.running):
            await self.runner.stop(sid)
        await self.jobs.shutdown()
        # Child process groups (commands, Codex CLI, PTYs, MCP stdio servers) live in their own
        # sessions, out of reach of the shell's group kill: SIGTERM, ≤1.5 s, SIGKILL, ≤1 s.
        res = await asyncio.to_thread(CHILDREN.terminate_all)
        if res["terminated"]:
            log.info("shutdown ended child process groups: %s", res)

        async def close(ext: object) -> None:
            fn = getattr(ext, "aclose", None)
            if fn:
                try:
                    await asyncio.wait_for(fn(), 3)
                except Exception:  # noqa: BLE001 — a slow or broken extension must not block quitting
                    log.warning("shutdown: %s didn't close cleanly", type(ext).__name__, exc_info=True)

        await asyncio.gather(*(close(ext) for ext in list(self.extensions.values())))
