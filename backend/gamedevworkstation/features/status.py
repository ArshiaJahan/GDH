"""Provider auth checks: Online / Auth failed / Unreachable per provider and profile.

A model is online only if its provider's check passed for that profile AND the model
appears in that provider's model list. Runs on startup and every 15 minutes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from ..providers.base import AuthStatus

if TYPE_CHECKING:
    from ..app import AppState

log = logging.getLogger(__name__)
CHECK_EVERY_S = 15 * 60


class StatusChecker:
    def __init__(self, app: "AppState"):
        self.app = app
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def _checkers(self) -> list[tuple[str, str, object]]:
        app = self.app
        out = []
        for prov in ("anthropic", "openai"):
            for prof in app.config.profiles(prov):
                out.append((prov, prof, app.providers.chat(prov, prof)))
        el = app.extensions.get("elevenlabs")
        if el is not None:
            for prof in app.config.profiles("elevenlabs"):
                out.append(("elevenlabs", prof, el.client_for(prof)))  # type: ignore[attr-defined]
        return out

    async def check_all(self, only: str | None = None) -> list[dict]:
        """Check every provider and profile (or just `only`'s profiles) and publish the snapshot."""
        async with self._lock:
            checks = [c for c in self._checkers() if only is None or c[0] == only]

            async def one(prov: str, prof: str, c: object) -> AuthStatus:
                try:
                    st = await asyncio.wait_for(c.check_auth(), 20)  # type: ignore[attr-defined]
                except asyncio.TimeoutError:
                    st = AuthStatus(provider=prov, profile=prof, status="unreachable", error="timed out after 20s")
                except Exception as e:  # noqa: BLE001
                    st = AuthStatus(provider=prov, profile=prof, status="unreachable", error=str(e)[:300])
                st.provider, st.profile, st.checked_at = prov, prof, time.time()
                return st

            results = await asyncio.gather(*(one(*c) for c in checks))
            for st in results:
                self.app.db.insert("auth_status", {
                    "provider": st.provider, "profile": st.profile, "status": st.status, "error": st.error,
                    "models": json.dumps(st.models), "extra": json.dumps(st.extra, default=str),
                    "checked_at": st.checked_at}, replace=True)
            snapshot = self.snapshot()
            self.app.bus.publish("status.updated", snapshot)
            return snapshot["providers"]

    def snapshot(self) -> dict:
        rows = self.app.db.all("SELECT * FROM auth_status ORDER BY provider, profile")
        providers = []
        for r in rows:
            r["models"] = json.loads(r["models"])
            r["extra"] = json.loads(r["extra"])
            providers.append(r)
        return {"providers": providers, "models": self.model_status(providers)}

    def model_status(self, providers: list[dict] | None = None) -> dict[str, dict]:
        """Status per configured model (default profile of its provider)."""
        providers = providers if providers is not None else self.snapshot()["providers"]
        by = {(p["provider"], p["profile"]): p for p in providers}
        out: dict[str, dict] = {}
        for mid, m in self.app.config.models.items():
            prof = self.app.config.profiles(m.provider)[0]
            p = by.get((m.provider, prof))
            if p is None:
                status, reason = "unknown", "not checked yet"
            elif p["status"] != "online":
                status, reason = p["status"], p.get("error")
            elif mid not in p["models"]:
                status, reason = "unavailable", "not in this account's model list"
            else:
                status, reason = "online", None
            out[mid] = {"status": status, "reason": reason, "provider": m.provider, "profile": prof,
                        "checked_at": p["checked_at"] if p else None}
        return out

    async def astart(self) -> None:
        async def loop() -> None:
            while True:
                try:
                    await self.check_all()
                except Exception:  # noqa: BLE001
                    log.exception("auth check failed")
                await asyncio.sleep(CHECK_EVERY_S)

        self._task = asyncio.create_task(loop())

    async def aclose(self) -> None:
        if self._task:
            self._task.cancel()
